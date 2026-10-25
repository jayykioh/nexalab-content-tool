"""Batch scaffolding for the whole book.

For every lesson it builds, from the Structured JSON and the outcome registry, what Bài 02 needed by hand:
``authoring.json`` (metadata, outcome per unit, claims, formulas, images, summary) and ``decisions.json`` (an
auto-proposed decision for each held item the rules can settle). Items the rules cannot settle go to the review
queue, which is the minimum a person must still do. Nothing here invents a licence, a reviewer or a verified
outcome; auto-proposed decisions are labelled ``reviewKind: auto-proposal`` and counted in the canonical lesson.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from .resolved_lesson import LessonContractError, build_canonical, canonical_to_pack, find_canonical, load_structured
from .structured_merge import build_lesson, fold, norm

PROTECTED = {"src-lesson-khtn9-02"}  # hand-authored with PDF checks; a scaffold never overwrites it
ACCESSED_AT = "2026-10-23"
ACCESSED_NOTE = "Date the local source.pdf was imported (release-prep/source-policy.draft.json sourceAccessDate). The original download source and date were not recorded."
RECAP = {"em da hoc", "em co the", "muc tieu", "noi dung bai hoc", "khoi dong", "em co biet"}
STOP = set("va la cua cac mot nhung duoc trong co de cho voi khi the nao hay bang tu nay do ve theo qua tai den nhu".split())
ICON_AREA = 0.006  # image blocks smaller than 0.6% of the page are icons in this book (Bài 02: icons 0.001-0.002, pictures >= 0.012)
COMPONENTS = ("headings", "summary", "knowledgeUnits", "formulas", "tables", "images", "basicExercises")


def slug(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def lesson_ids(root: Path) -> list[str]:
    return sorted(p.stem for p in (root / "exports" / "structured").glob("src-lesson-*.json"))


def _score(statement: str, text: str) -> float:
    a = {w for w in fold(statement).split() if w not in STOP and len(w) > 2}
    b = set(fold(text).split())
    return len(a & b) / len(a) if a else 0.0


def _objective(lesson: dict[str, Any], title: str) -> tuple[str, bool]:
    for s in lesson["sourceReading"]["sections"]:
        if fold(s["heading"]) == "muc tieu":
            bullets = [norm(l).lstrip("■ ").strip() for l in s["content"].split("\n") if l.strip().startswith("■")] or [norm(s["content"])]
            text = ""
            for bullet in bullets:  # the BE allows 500 characters: keep whole bullets, never cut mid-sentence
                if len((text + " " + bullet).strip()) > 480:
                    break
                text = (text + " " + bullet).strip()
            if text:
                return text, True
    return f"Trình bày được nội dung chính của bài {title}.", False


def _summary(lesson: dict[str, Any], blocks: dict[str, dict]) -> tuple[dict[str, Any] | None, str]:
    for s in lesson["sourceReading"]["sections"]:
        if fold(s["heading"]) == "em da hoc":
            ids = [b for b in s["sourceBlockIds"] if blocks.get(b, {}).get("type") == "text"]
            text = norm(" ".join(blocks[b]["normalizedText"] for b in ids))
            if text:
                return {"text": text, "sourceBlockIds": ids}, "em-da-hoc"
    texts = [b for b in lesson["sourceBlocks"] if b["type"] == "text" and len(b["normalizedText"]) > 60][:2]
    if texts:
        return {"text": norm(" ".join(b["normalizedText"] for b in texts)), "sourceBlockIds": [b["id"] for b in texts]}, "first-paragraphs"
    return None, "none"


def scaffold_lesson(root: Path, lesson_id: str, registry: dict[str, Any]) -> dict[str, Any]:
    _, lesson = load_structured(root, lesson_id)
    number = lesson_id.rsplit("-", 1)[-1]
    reg = registry["lessons"][lesson_id]
    title = lesson["sourceLesson"]["title"]
    blocks = {b["id"]: b for b in lesson["sourceBlocks"]}
    statements = {o["code"]: o["statement"] for o in registry["outcomes"]}
    original = lesson.get("learningContentOriginal") or lesson["learningContent"]
    queue: list[dict[str, Any]] = []
    objective, objective_ok = _objective(lesson, title)
    if not objective_ok:
        queue.append({"kind": "objective_fallback", "detail": "no MỤC TIÊU section; generic objective used"})
    summary, summary_from = _summary(lesson, blocks)
    if summary_from != "em-da-hoc":
        queue.append({"kind": "summary_auto", "detail": f"summary taken from {summary_from}; check it covers the lesson"})
    # outcome per unit, by overlap with the unit's own text; recap-like units carry every lesson outcome
    unit_outcomes: dict[str, list[str]] = {}
    low_confidence = []
    for unit in original.get("knowledgeUnits") or []:
        codes = reg["outcomeCodes"]
        if len(codes) == 1 or fold(unit["title"]) in RECAP:
            unit_outcomes[unit["id"]] = list(codes)
            continue
        text = unit["title"] + " " + " ".join(c["text"] for c in unit["claims"])
        scores = {c: _score(statements.get(c, ""), text) for c in codes}
        best = max(scores.values())
        picked = [c for c, v in scores.items() if v >= max(best * 0.8, 0.15)]
        if not picked or best < 0.15:
            unit_outcomes[unit["id"]] = list(codes)
            low_confidence.append(unit["title"])
        else:
            unit_outcomes[unit["id"]] = picked
    if low_confidence:
        queue.append({"kind": "unit_outcome_low_confidence", "count": len(low_confidence), "detail": f"units mapped to all lesson outcomes for lack of overlap: {low_confidence[:6]}"})
    claims, cues = {}, 0
    for unit in original.get("knowledgeUnits") or []:
        for claim in unit["claims"]:
            key = _short(claim["sourceBlockIds"][0])
            cue = bool(re.search(r"\$|\\frac|gọi là|được gọi|công thức|biểu thức|định luật|khái niệm", claim["text"], re.I))
            cues += cue
            claims[key] = {"important": False, "basis": "scaffold default; importance policy is pending (see batch decisions)", "importanceCue": cue}
    formulas = []
    for block in lesson["sourceBlocks"]:
        if block["type"] == "equation":
            formulas.append({"id": f"formula-{_short(block['id'])}", "latex": block["normalizedText"].strip(), "sourceBlockIds": [block["id"]], "renderBlockIds": [block["id"]], "verifiedBy": None, "pdfPages": [block["physicalPageIndex"]]})
    if formulas:
        queue.append({"kind": "formulas_unverified", "count": len(formulas), "detail": "OCR LaTeX of equation blocks is unverified against the PDF"})
    images, content_images = {}, []
    for block in lesson["sourceBlocks"]:
        if block["type"] not in {"image", "chart"}:
            continue
        if block["type"] == "chart":  # graphs carry data: always a content figure
            images[block["id"]] = {"role": "content", "description": None, "figureLabel": None}
            content_images.append(block["physicalPageIndex"])
            continue
        x0, y0, x1, y1 = block["bbox"]
        if (x1 - x0) * (y1 - y0) < ICON_AREA:
            images[block["id"]] = {"role": "decorative", "reason": "icon-size block (< 0.6% of the page area), no scientific content"}
        else:
            images[block["id"]] = {"role": "content", "description": None, "figureLabel": None}
            content_images.append(block["physicalPageIndex"])
    if content_images:
        queue.append({"kind": "image_descriptions_needed", "count": len(content_images), "detail": f"content images on PDF pages {sorted(set(content_images))}"})
    tables = [{"id": f"table-{_short(b['id'])}", "text": b["normalizedText"], "sourceBlockIds": [b["id"]]} for b in lesson["sourceBlocks"] if b["type"] == "table"]
    if tables:
        queue.append({"kind": "tables_review", "count": len(tables), "detail": "table blocks must be checked against the PDF"})
    authoring = {
        "schemaVersion": 1, "lessonId": lesson_id, "generatedBy": "batch scaffold; values below are rules, not review",
        "packKey": f"khtn9-l{number}-{slug(title)}"[:56].rstrip("-"), "title": title, "grade": 9, "domain": reg["domain"], "subjectId": reg["subjectId"],
        "topic": reg.get("topic") or lesson["chapter"]["title"], "outcomeCodes": reg["outcomeCodes"], "curriculumVerification": "unverified",
        "learningObjective": objective, "prerequisites": "",
        "source": {"accessedAt": ACCESSED_AT, "accessedAtNote": ACCESSED_NOTE, "license": "UNKNOWN", "attribution": f"{lesson['book']['title']} — {lesson['book']['author']}", "authoritative": False},
        "summary": summary or {"text": "", "sourceBlockIds": []}, "unitOutcomes": unit_outcomes, "claims": claims, "addedClaims": {},
        "formulas": formulas, "tables": tables, "images": images, "basicExercises": None,
    }
    if not reg.get("domainVerified"):
        queue.append({"kind": "domain_unverified", "detail": reg.get("note") or "domain not verified in the mapping draft"})
    return {"authoring": authoring, "queue": queue, "stats": {"cues": cues, "claims": len(claims)}}


def _short(block_id: str) -> str:
    found = re.search(r"(p\d{4}-b\d{4})$", block_id)
    return found.group(1) if found else block_id


def propose(built: dict[str, Any], lesson: dict[str, Any], title: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Auto-proposed decisions by rule, and the held items the rules cannot settle."""
    headings = {fold(s["heading"]) for s in built["sections"]}
    title_fold = fold(title)
    proposals, manual = [], []
    for section in built["sections"]:
        for item in section["held"]:
            src = (item["source"] or {}).get("text", "")
            lrn = (item["learning"] or {}).get("text", "")
            action, reason, confidence = None, "", "none"
            kind = item["kind"]
            if kind == "block_type_review":
                if re.match(r"^(Chương [IVXLC]+|Bài \d+)\b", src) or (fold(src) and fold(src) in title_fold):
                    action, reason, confidence = "exclude", "running header or title piece already carried by metadata (chapter/title)", "high"
                elif re.match(r"^(Hình|Bảng)\s*\d", src):
                    action, reason, confidence = "source", "figure/table caption typed as footer by OCR; kept as lesson text", "medium"
            elif kind == "near_pair":
                changed = [d for d in item["diff"]]
                risky = any(re.search(r"[\d=+\-−×÷<>≠≤≥/^_]", d["learning"] + d["source"]) for d in changed)
                # Words present on only one side (insert/delete beyond a bullet mark) may be content: a person checks the PDF.
                risky = risky or any((not d["source"].strip() and re.search(r"[^\W\d_■]", d["learning"])) or (not d["learning"].strip() and re.search(r"[^\W\d_■]", d["source"])) or (len(d["learning"].split()) != len(d["source"].split()) and d["op"] != "replace") for d in changed)
                if not risky:
                    action, reason, confidence = "source", "stored OCR text kept; the learning text predates the OCR review (Bài 02: 6 of 6 such pairs, source matched the PDF)", "medium"
            elif kind == "covering_extra":
                if fold(item.get("remainder", "")) in headings:
                    action, reason, confidence = "source", "extra words are a section heading glued to the sentence by the OCR line wrap", "high"
            if action:
                proposals.append({"itemId": item["id"], "fingerprint": item["fingerprint"], "action": action, "replacement": None, "sourceBlockIds": [], "reason": reason, "confidence": confidence, "autoProposed": True, "actor": "batch-scaffold", "reviewKind": "auto-proposal"})
            else:
                manual.append({"itemId": item["id"], "kind": kind, "sectionId": section["id"], "sourceText": src[:160], "learningText": lrn[:160], "evidence": item.get("evidence")})
    return proposals, manual


def scaffold_all(root: Path, registry: dict[str, Any], only: list[str] | None = None, force: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"lessons": {}, "totals": Counter()}
    for lesson_id in only or lesson_ids(root):
        folder = root / "release-prep" / f"bai{lesson_id.rsplit('-', 1)[-1]}"
        if lesson_id in PROTECTED or (folder / ".protected").exists() or ((folder / "decisions.json").exists() and not force):
            out["lessons"][lesson_id] = {"status": "skipped", "reason": "hand-authored decisions.json exists"}
            continue
        _, lesson = load_structured(root, lesson_id)
        scaffold = scaffold_lesson(root, lesson_id, registry)
        built = build_lesson(lesson)
        proposals, manual = propose(built, lesson, lesson["sourceLesson"]["title"])
        components = {
            "headings": {"state": "resolved", "reason": "auto: headings are the source block texts; title is the Structured lesson title", "sourceBlockIds": []},
            "summary": {"state": "resolved" if scaffold["authoring"]["summary"]["text"] else "unresolved", "reason": "auto summary from the recap blocks", "sourceBlockIds": scaffold["authoring"]["summary"]["sourceBlockIds"]},
            "knowledgeUnits": {"state": "resolved", "reason": "auto: claims from source blocks; outcomes by text overlap", "sourceBlockIds": []},
            "formulas": {"state": "unresolved" if scaffold["authoring"]["formulas"] else "not_applicable", "reason": "OCR LaTeX unverified" if scaffold["authoring"]["formulas"] else "no equation block", "sourceBlockIds": []},
            "tables": {"state": "unresolved" if scaffold["authoring"]["tables"] else "not_applicable", "reason": "table blocks need a PDF check" if scaffold["authoring"]["tables"] else "no table block", "sourceBlockIds": []},
            "images": {"state": "resolved", "reason": "auto: icons by size; content images need descriptions (enforced per image)", "sourceBlockIds": []},
            "basicExercises": {"state": "not_applicable", "reason": "no verified exercises supplied; none converted to a QUIZ", "sourceBlockIds": []},
        }
        decisions = {"schemaVersion": 1, "lessonId": lesson_id, "inputFingerprint": built["fingerprint"], "decisions": proposals, "corrections": [], "components": components, "generatedBy": "batch scaffold"}
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "authoring.json").write_text(json.dumps(scaffold["authoring"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (folder / "decisions.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        queue = scaffold["queue"] + ([{"kind": "held_needs_human", "count": len(manual), "items": manual}] if manual else [])
        (folder / "review-queue.json").write_text(json.dumps({"lessonId": lesson_id, "queue": queue}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out["lessons"][lesson_id] = {"status": "scaffolded", "folder": folder.name, "held": sum(len(s["held"]) for s in built["sections"]), "autoProposed": len(proposals), "needsHuman": len(manual), "queue": {q["kind"]: q.get("count", 1) for q in queue}}
        out["totals"].update({"lessons": 1, "held": out["lessons"][lesson_id]["held"], "autoProposed": len(proposals), "needsHuman": len(manual)})
        for q in queue:
            out["totals"][f"queue.{q['kind']}"] += q.get("count", 1)
    out["totals"] = dict(out["totals"])
    return out


def preview_manifest(root: Path, lesson_ids_: list[str]) -> dict[str, Any]:
    """One manifest of preview packs for BE `plan`. NOT RELEASABLE: unresolved content is allowed so that the BE gates
    (outcomes, rights, sources, reviews) can be listed for every lesson at once."""
    from .resolved_lesson import apply_to_structured  # noqa: F401  (kept explicit: preview never applies)

    packs, skipped = [], {}
    for lesson_id in lesson_ids_:
        folder = root / "release-prep" / f"bai{lesson_id.rsplit('-', 1)[-1]}"
        try:
            _, lesson = load_structured(root, lesson_id)
            authoring = json.loads((folder / "authoring.json").read_text(encoding="utf-8"))
            decisions = json.loads((folder / "decisions.json").read_text(encoding="utf-8"))
            canonical, _ = build_canonical(lesson, decisions, authoring, lesson_id)
            packs.append(canonical_to_pack(canonical, lesson["sourceBlocks"], allow_unresolved=True)["pack"])
        except (LessonContractError, FileNotFoundError, KeyError) as error:
            skipped[lesson_id] = str(error)[:200]
    return {"name": "khtn9-all-preview-not-releasable", "namespace": "baseline", "sources": [], "packs": packs, "_skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import shutil
    from datetime import datetime

    from .outcome_registry import write_registry

    parser = argparse.ArgumentParser(description="Scaffold authoring/decisions for every lesson and build a preview manifest for BE plan.")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--force", action="store_true", help="overwrite scaffolds (never overwrites hand-authored Bài 02 unless --force)")
    args = parser.parse_args(argv)
    root = args.workspace.resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / f"backups-batch-{stamp}"
    shutil.copytree(root / "exports" / "structured", backup / "structured")
    registry = json.loads(write_registry(root).read_text(encoding="utf-8"))
    summary = scaffold_all(root, registry, force=args.force)
    out = root / "exports" / "batch"
    out.mkdir(parents=True, exist_ok=True)
    manifest = preview_manifest(root, lesson_ids(root))
    skipped = manifest.pop("_skipped")
    (out / "release-contract-preview.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary["previewPacks"] = len(manifest["packs"])
    summary["previewSkipped"] = skipped
    summary["backup"] = backup.name
    (out / "batch-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"totals": summary["totals"], "previewPacks": summary["previewPacks"], "skipped": len(skipped), "backup": backup.name}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
