"""Decision store, canonical lesson and the single converter to a BE pack.

Flow for one lesson:  Structured JSON  ->  merge preview (held items)  ->  decisions.json (+ authoring.json)
->  canonical.json  ->  canonical_to_pack()  ->  Candidate and Release Pack (same pack, same digest).

Nothing here invents rights, reviewers, outcomes or dates. A decision made by an agent is recorded as an agent
decision (``reviewKind``) and is never a human approval. ``contentResolved`` only says that every held item and
every component has a decision; ``schemaValid`` and ``releaseReady`` are separate facts reported elsewhere.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

from .structured_merge import ALGORITHM_VERSION, PLACEHOLDER, build_lesson, lesson_fingerprint, norm

SCHEMA_VERSION = 1
ACTIONS = {"source", "learning", "replace", "exclude"}
COMPONENTS = ("headings", "summary", "knowledgeUnits", "formulas", "tables", "images", "basicExercises")
COMPONENT_STATES = {"resolved", "not_applicable", "unresolved"}


class LessonContractError(Exception):
    """A blocking problem with a stable code, so callers and reports can rely on it."""

    def __init__(self, code: str, detail: str, items: list[dict[str, Any]] | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.items = code, detail, items or []


def _short(block_id: str) -> str:
    """pNNNN-bNNNN tail of a block id, independent of the book prefix."""
    found = re.search(r"(p\d{4}-b\d{4})$", block_id)
    return found.group(1) if found else block_id


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _read(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_structured(workspace_root: Path, lesson_id: str) -> tuple[Path, dict[str, Any]]:
    path = workspace_root / "exports" / "structured" / f"{lesson_id}.json"
    if not path.is_file():
        raise LessonContractError("STRUCTURED_MISSING", f"{path} does not exist")
    return path, json.loads(path.read_text(encoding="utf-8"))


def find_canonical(workspace_root: Path, lesson_id: str) -> Path | None:
    for path in sorted((workspace_root / "release-prep").glob("*/canonical.json")):
        if (_read(path) or {}).get("lessonId") == lesson_id:
            return path
    return None


# --------------------------------------------------------------------------------------------- decisions

def check_decisions(built: dict[str, Any], doc: dict[str, Any] | None, lesson_id: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Returns decisions by held item id and the blocking problems (STALE_DECISION, UNRESOLVED_ITEM, INVALID_DECISION)."""
    errors: list[dict[str, Any]] = []
    held = {h["id"]: h for s in built["sections"] for h in s["held"]}
    block_ids = {b["id"] for b in built["blocks"]}
    fingerprint = built["fingerprint"]
    decisions = (doc or {}).get("decisions") or []
    stale_input = bool(doc) and doc.get("inputFingerprint") != fingerprint
    if doc and doc.get("lessonId") != lesson_id:
        errors.append({"code": "INVALID_DECISION", "detail": f"decisions belong to {doc.get('lessonId')}"})
    if stale_input:
        errors.append({"code": "STALE_DECISION", "detail": "inputFingerprint differs from the current lesson input; every decision is void"})
    by_id: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        item_id = decision.get("itemId")
        if stale_input:
            continue
        if item_id not in held:
            errors.append({"code": "STALE_DECISION", "itemId": item_id, "detail": "item no longer exists in the preview"})
        elif decision.get("fingerprint") != held[item_id]["fingerprint"]:
            errors.append({"code": "STALE_DECISION", "itemId": item_id, "detail": "item fingerprint changed"})
        elif decision.get("action") not in ACTIONS:
            errors.append({"code": "INVALID_DECISION", "itemId": item_id, "detail": f"action {decision.get('action')!r} is not one of {sorted(ACTIONS)}"})
        elif not str(decision.get("reason") or "").strip():
            errors.append({"code": "INVALID_DECISION", "itemId": item_id, "detail": "reason is required"})
        elif decision["action"] == "replace" and not str(decision.get("replacement") or "").strip():
            errors.append({"code": "INVALID_DECISION", "itemId": item_id, "detail": "replace needs non-empty replacement"})
        elif decision["action"] == "learning" and not held[item_id].get("learning"):
            errors.append({"code": "INVALID_DECISION", "itemId": item_id, "detail": "item has no learning side"})
        elif decision["action"] == "source" and not held[item_id].get("source"):
            errors.append({"code": "INVALID_DECISION", "itemId": item_id, "detail": "item has no source side"})
        elif any(b not in block_ids for b in decision.get("sourceBlockIds") or []):
            errors.append({"code": "INVALID_DECISION", "itemId": item_id, "detail": "sourceBlockIds contain a block that does not exist"})
        elif item_id in by_id:
            errors.append({"code": "INVALID_DECISION", "itemId": item_id, "detail": "duplicate decision"})
        else:
            by_id[item_id] = decision
    for item_id, item in held.items():
        if item_id not in by_id and not any(e.get("itemId") == item_id for e in errors):
            errors.append({"code": "UNRESOLVED_ITEM", "itemId": item_id, "kind": item["kind"], "sourceText": (item.get("source") or {}).get("text"), "learningText": (item.get("learning") or {}).get("text")})
    return by_id, errors


def check_corrections(lesson: dict[str, Any], doc: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Text corrections against the source blocks (OCR errors found on the PDF that no held item points at)."""
    errors: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    blocks = {b["id"]: norm(b.get("normalizedText") or "") for b in lesson.get("sourceBlocks") or []}
    stale = bool(doc) and doc.get("inputFingerprint") != lesson_fingerprint(lesson)
    for index, item in enumerate((doc or {}).get("corrections") or []):
        if stale:
            continue
        block = item.get("blockId")
        if block not in blocks or not item.get("from") or not item.get("to") or item["from"] == item["to"]:
            errors.append({"code": "INVALID_DECISION", "correction": index, "detail": "correction needs an existing block and different from/to text"})
        elif item["from"] not in blocks[block]:
            errors.append({"code": "STALE_DECISION", "correction": index, "detail": f"{item['from']!r} is no longer in block {block}"})
        elif not str(item.get("reason") or "").strip():
            errors.append({"code": "INVALID_DECISION", "correction": index, "detail": "reason is required"})
        else:
            valid.append({**item, "index": index})
    return valid, errors


def _apply_corrections(text: str, block_ids: list[str], corrections: list[dict[str, Any]], used: set[int]) -> str:
    for item in corrections:
        if item["blockId"] in block_ids and item["from"] in text:
            text = text.replace(item["from"], item["to"])
            used.add(item["index"])
    return text


def _render_section(section: dict[str, Any], by_id: dict[str, dict[str, Any]], formula_by_block: dict[str, str], corrections: list[dict[str, Any]] | None = None, used: set[int] | None = None) -> tuple[str, list[str], list[dict[str, Any]]]:
    corrections = corrections or []
    used = used if used is not None else set()
    held = {h["id"]: h for h in section["held"]}
    handled: set[str] = set()
    pieces: list[tuple[str, bool]] = []
    blocks: list[str] = []
    applied: list[dict[str, Any]] = []

    def apply(hid: str) -> tuple[str, bool]:
        item, decision = held[hid], by_id[hid]
        handled.add(hid)
        applied.append({"itemId": hid, "action": decision["action"], "reason": decision["reason"], "reviewKind": decision.get("reviewKind"), "actor": decision.get("actor")})
        if decision["action"] == "source":
            texts = [u["text"] for u in section["sourceUnits"] if u.get("heldId") == hid]
            blocks.extend(b for u in section["sourceUnits"] if u.get("heldId") == hid for b in u["blockIds"])
            return " ".join(texts), True
        if decision["action"] == "learning":
            return item["learning"]["text"], True
        if decision["action"] == "replace":
            blocks.extend(decision.get("sourceBlockIds") or [])
            return decision["replacement"].strip(), True
        return "", True

    for unit in section["sourceUnits"]:
        state = unit.get("disposition")
        if state == "emitted":
            ids = unit["blockIds"]
            text = unit["text"]
            if ids and all(b in formula_by_block for b in ids):
                text = f"${formula_by_block[ids[0]]}$"
            blocks.extend(ids)
            pieces.append((_apply_corrections(text, ids, corrections, used), bool(unit.get("paraEnd", True))))
        elif state == "held" and unit["heldId"] not in handled:
            text, para = apply(unit["heldId"])
            if text:
                pieces.append((text, para))
    for hid, item in held.items():
        if hid not in handled and item["source"] is None:
            text, para = apply(hid)
            if text:
                pieces.append((text, para))
    out = ""
    for index, (text, para) in enumerate(pieces):
        out += text if index == 0 else ("\n\n" if pieces[index - 1][1] else " ") + text
    return out, sorted(set(blocks)), applied


# --------------------------------------------------------------------------------------------- canonical

def _claim_text(text: str, block_text: str) -> tuple[str, bool]:
    """Claim text corrected against its own source block. Returns (text, changed)."""
    current = norm(text)
    if current in norm(block_text):
        return current, False
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", norm(block_text)) if s]
    import difflib

    best = max(sentences, key=lambda s: difflib.SequenceMatcher(None, current, s).ratio(), default="")
    if best and difflib.SequenceMatcher(None, current, best).ratio() >= 0.85:
        return best, True
    raise LessonContractError("CLAIM_EVIDENCE_MISSING", f"claim text does not match its source block: {current[:80]}")


def build_canonical(lesson: dict[str, Any], decisions_doc: dict[str, Any] | None, authoring: dict[str, Any], lesson_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    built = build_lesson(lesson)
    by_id, errors = check_decisions(built, decisions_doc, lesson_id)
    components = {name: ((decisions_doc or {}).get("components") or {}).get(name) or {"state": "unresolved", "reason": "no component decision"} for name in COMPONENTS}
    for name, value in components.items():
        if value.get("state") not in COMPONENT_STATES:
            errors.append({"code": "INVALID_DECISION", "component": name, "detail": "component state must be resolved, not_applicable or unresolved"})
        elif value["state"] == "unresolved":
            errors.append({"code": "UNRESOLVED_ITEM", "component": name, "detail": value.get("reason")})
        elif not str(value.get("reason") or "").strip():
            errors.append({"code": "INVALID_DECISION", "component": name, "detail": "reason is required"})
    block_by_id = {b["id"]: b for b in lesson.get("sourceBlocks") or []}
    book = lesson["book"]
    book_key = book["key"]
    source_cfg = authoring.get("source") or {}
    formulas = authoring.get("formulas") or []
    formula_by_block = {b: f["latex"] for f in formulas for b in f.get("renderBlockIds", [])}

    corrections, correction_errors = check_corrections(lesson, decisions_doc)
    errors.extend(correction_errors)
    used_corrections: set[int] = set()
    owned = {s["id"]: s.get("sourceBlockIds") or [] for s in (lesson.get("sourceReading") or {}).get("sections") or []}
    sections, applied = [], []
    for section in built["sections"]:
        content, blocks, done = _render_section(section, by_id, formula_by_block, corrections, used_corrections) if not errors_for_section(errors, section) else ("", [], [])
        applied.extend(done)
        sections.append({"id": section["id"], "heading": section["heading"], "content": content, "sourceBlockIds": blocks, "ownedBlockIds": owned.get(section["id"], [])})

    if not errors:
        for item in corrections:
            if item["index"] not in used_corrections:
                errors.append({"code": "STALE_DECISION", "correction": item["index"], "detail": "correction matched no emitted text"})
    image_cfg = authoring.get("images") or {}
    images = []
    figure_entries = [e for e in ((lesson.get("learningContentOriginal") or lesson["learningContent"]).get("sourceImages") or []) if e["id"] in block_by_id]  # figures of pages outside the lesson range are stale
    known = {e["id"] for e in figure_entries}
    figure_entries += [{"id": b["id"], "pdfPage": b["physicalPageIndex"]} for b in lesson.get("sourceBlocks") or [] if b["type"] == "chart" and b["id"] not in known]
    for entry in figure_entries:
        cfg = image_cfg.get(entry["id"])
        block = block_by_id.get(entry["id"], {})
        if not cfg or cfg.get("role") not in {"content", "decorative"}:
            errors.append({"code": "UNRESOLVED_ITEM", "component": "images", "itemId": entry["id"], "detail": "image block has no classification"})
            continue
        if cfg["role"] == "content" and not str(cfg.get("description") or "").strip():
            errors.append({"code": "UNRESOLVED_ITEM", "component": "images", "itemId": entry["id"], "pdfPage": entry.get("pdfPage"), "detail": "content image needs a description from the PDF"})
            continue
        if cfg["role"] == "decorative" and not str(cfg.get("reason") or "").strip():
            errors.append({"code": "UNRESOLVED_ITEM", "component": "images", "itemId": entry["id"], "detail": "decorative image needs a reason"})
            continue
        images.append({"sectionId": _section_of_block(entry["id"], lesson.get("sourceBlocks") or [], owned), "id": entry["id"], "pdfPage": entry.get("pdfPage"), "bbox": block.get("bbox"), "role": cfg["role"], "description": cfg.get("description"), "reason": cfg.get("reason"), "figureLabel": cfg.get("figureLabel"), "sourceBlockIds": [entry["id"]]})

    claim_cfg = authoring.get("claims") or {}
    unit_cfg = authoring.get("unitOutcomes") or {}
    units, claim_fixes = [], []
    original = lesson.get("learningContentOriginal") or lesson["learningContent"]
    for unit in original.get("knowledgeUnits") or []:
        outcomes = unit_cfg.get(unit["id"]) or unit_cfg.get(unit["title"])
        if not outcomes:
            errors.append({"code": "MISSING_UNIT_OUTCOME", "itemId": unit["id"], "detail": f"no outcome mapping for unit {unit['title']!r}"})
            outcomes = []
        claims = []
        for claim in unit["claims"]:
            plain = norm(PLACEHOLDER.sub("", claim["text"]))
            if not plain or plain.startswith("|"):
                claim_fixes.append({"claimId": claim["id"], "dropped": True, "reason": "claim is an image placeholder or a table row, not a statement of knowledge", "was": norm(claim["text"])[:120]})
                continue
            blocks = claim.get("sourceBlockIds") or []
            if blocks and all(b not in block_by_id for b in blocks):
                # Stale claim from before a page-range fix: its blocks are on pages that no longer belong to this lesson.
                claim_fixes.append({"claimId": claim["id"], "dropped": True, "reason": "claim's source blocks lie outside this lesson's page range", "was": norm(claim["text"])[:120]})
                continue
            if not blocks or any(b not in block_by_id for b in blocks):
                raise LessonContractError("CLAIM_EVIDENCE_MISSING", f"claim {claim['id']} has no existing source block")
            key = _short(blocks[0])
            cfg = claim_cfg.get(key)
            if cfg is None or not isinstance(cfg.get("important"), bool):
                raise LessonContractError("CLAIM_IMPORTANCE_MISSING", f"claim {claim['id']} ({key}) has no authored importance")
            try:
                text, changed = _claim_text(claim["text"], block_by_id[blocks[0]]["normalizedText"])
            except LessonContractError:
                # The stored claim no longer matches its block (glued heading, stale edit): take the closest source sentence.
                import difflib

                sentences = [s for s in re.split(r"(?<=[.!?])\s+", norm(block_by_id[blocks[0]]["normalizedText"])) if len(s) > 15]
                scored = [(difflib.SequenceMatcher(None, norm(claim["text"]), s).ratio(), s) for s in sentences]
                ratio, best = max(scored, default=(0, ""))
                if ratio < 0.5:
                    claim_fixes.append({"claimId": claim["id"], "dropped": True, "reason": "no source sentence is close to the stored claim", "was": norm(claim["text"])[:120]})
                    continue
                text, changed = best, True
                claim_fixes.append({"claimId": claim["id"], "repairedFromClosestSentence": round(ratio, 3), "from": norm(claim["text"])[:120], "to": best[:120]})
            if len(text) > 1000:  # the BE allows 1000 characters per claim: cut at a sentence boundary, or drop
                cut = max((m.end() for m in re.finditer(r"[.!?](?=\s)", text[:1000])), default=0)
                if cut < 40:
                    claim_fixes.append({"claimId": claim["id"], "dropped": True, "reason": "claim longer than 1000 characters with no sentence boundary", "was": text[:120]})
                    continue
                claim_fixes.append({"claimId": claim["id"], "truncatedAtSentence": cut, "was": len(text)})
                text, changed = text[:cut].strip(), True
            fixed = _apply_corrections(text, blocks, corrections, set())
            changed, text = changed or fixed != text, fixed
            if changed:
                claim_fixes.append({"claimId": claim["id"], "from": norm(claim["text"]), "to": text})
            claims.append({"id": claim["id"], "text": text, "important": cfg["important"], "importanceBasis": cfg.get("basis"), "sourceIds": [book_key], "sourceBlockIds": blocks})
        if not claims and not (authoring.get("addedClaims") or {}).get(unit["title"]):
            claim_fixes.append({"unitId": unit["id"], "dropped": True, "reason": "every claim of the unit was dropped"})
            continue
        for extra in (authoring.get("addedClaims") or {}).get(unit["title"], []):
            blocks = extra["sourceBlockIds"]
            if any(b not in block_by_id for b in blocks) or norm(extra["text"]) not in norm(block_by_id[blocks[0]]["normalizedText"]):
                raise LessonContractError("CLAIM_EVIDENCE_MISSING", f"added claim {extra['id']} is not contained in its source block")
            claims.append({"id": extra["id"], "text": norm(extra["text"]), "important": bool(extra["important"]), "importanceBasis": extra.get("basis"), "sourceIds": [book_key], "sourceBlockIds": blocks})
        units.append({"id": unit["id"], "title": unit["title"], "outcomeCodes": outcomes, "terms": unit.get("terms", []), "misconceptions": unit.get("misconceptions", []), "claims": claims})

    summary = authoring.get("summary") or {}
    if not str(summary.get("text") or "").strip() or any(b not in block_by_id for b in summary.get("sourceBlockIds") or []) or not summary.get("sourceBlockIds"):
        errors.append({"code": "UNRESOLVED_ITEM", "component": "summary", "detail": "authored summary with existing source blocks is required"})

    canonical: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "lessonId": lesson_id,
        "packKey": authoring["packKey"],
        "inputFingerprint": built["fingerprint"],
        "algorithm": ALGORITHM_VERSION,
        "contentStatus": "unresolved" if errors else "resolved",
        "metadata": {
            "title": authoring["title"], "grade": authoring["grade"], "domain": authoring["domain"],
            "chapter": lesson["chapter"]["title"], "topic": authoring.get("topic") or lesson["chapter"]["title"],
            "subjectId": authoring["subjectId"], "outcomeCodes": authoring["outcomeCodes"],
            "curriculumVerification": authoring.get("curriculumVerification", "unverified"),
            "learningObjective": authoring["learningObjective"], "prerequisites": authoring.get("prerequisites", ""),
            "pdfPageRange": lesson.get("pdfPageRange"), "printedPageRange": lesson.get("printedPageRange"),
        },
        "sources": [{
            "id": book_key, "version": book["version"], "sha256": book["sha256"], "title": book["title"], "author": book["author"],
            "accessedAt": source_cfg.get("accessedAt"), "accessedAtNote": source_cfg.get("accessedAtNote"),
            "license": source_cfg.get("license"), "attribution": source_cfg.get("attribution"), "authoritative": bool(source_cfg.get("authoritative", False)),
        }],
        "sections": sections,
        "summary": {"text": summary.get("text"), "sourceBlockIds": summary.get("sourceBlockIds") or []},
        "knowledgeUnits": units,
        "formulas": formulas,
        "tables": authoring.get("tables") or [],
        "images": images,
        "basicExercises": authoring.get("basicExercises"),
        "componentDecisions": components,
        "decisionsApplied": applied,
        "claimFixes": claim_fixes,
        "correctionsApplied": [{"blockId": c["blockId"], "from": c["from"], "to": c["to"], "reason": c["reason"], "pdfCheck": c.get("pdfCheck"), "reviewKind": c.get("reviewKind")} for c in corrections if c["index"] in used_corrections],
        "decisionProvenance": "agent decisions are recorded with reviewKind; none is a human approval",
        "unresolvedItems": errors,
    }
    canonical["releaseBlockers"] = release_blockers(canonical)
    canonical["contentHash"] = _digest({k: v for k, v in canonical.items() if k != "contentHash"})
    return canonical, errors


def _section_of_block(block_id: str, blocks: list[dict[str, Any]], owned: dict[str, list[str]]) -> str | None:
    """Section that holds this block; a block no section lists goes with the nearest earlier block that has a section."""
    owner = {b: sid for sid, ids in owned.items() for b in ids}
    order = [b["id"] for b in blocks]
    if block_id not in order:
        return None
    index = order.index(block_id)
    for candidate in order[index::-1] + order[index + 1:]:
        if candidate in owner:
            return owner[candidate]
    return None


def errors_for_section(errors: list[dict[str, Any]], section: dict[str, Any]) -> bool:
    ids = {h["id"] for h in section["held"]}
    return any(e.get("itemId") in ids for e in errors)


def release_blockers(canonical: dict[str, Any]) -> list[dict[str, str]]:
    """severity=hard: the BE plan rejects it (content-pack.ts packGateErrors / content-release.ts). severity=advisory:
    the Content Tool reports it, but the BE does not gate on it."""
    blockers = []
    source = canonical["sources"][0]

    def add(code: str, severity: str, detail: str) -> None:
        blockers.append({"code": code, "severity": severity, "detail": detail})

    if source.get("license") in (None, "UNKNOWN"):
        add("LICENSE_UNKNOWN", "hard", "BE rejects any source licence outside ORIGINAL, CC0, PUBLIC_DOMAIN, CC_BY, CC_BY_SA, SCHOOL_OWNED, REFERENCE_ONLY; rights need a decision by the rights owner")
    if source.get("license") not in ("ORIGINAL", "SCHOOL_OWNED") and not source.get("url"):
        add("SOURCE_URL_MISSING", "hard", "BE requires an original URL for every source whose licence is not ORIGINAL or SCHOOL_OWNED")
    add("REVIEWS_MISSING", "hard", "BE requires editorial, subject, rights and accessibility reviews from active TEACHER/ADMIN accounts; subject and rights reviewers must differ")
    for unit in canonical["knowledgeUnits"]:
        for claim in unit["claims"]:
            if claim["important"]:
                add("IMPORTANT_CLAIM_NEEDS_TWO_SOURCES", "hard", f"claim {claim['id']} is important: BE needs two independent sources, one authoritative (has {len(claim['sourceIds'])})")
    if canonical["metadata"]["curriculumVerification"] != "verified":
        add("OUTCOME_UNVERIFIED", "advisory", "outcome codes exist in the BE table (seeded from an agent mapping) but no subject reviewer has verified the mapping")
    add("SOURCE_POLICY_NOT_REQUIRED", "advisory", "BE packs do not need a SourcePolicy; one is only needed to ingest automatically from a source")
    if canonical["basicExercises"] is None:
        add("BASIC_EXERCISE_ABSENT", "advisory", "BE does not require exercises; none was invented and none was turned into a QUIZ")
    if any(i["role"] == "content" for i in canonical["images"]):
        add("IMAGE_DESCRIPTIONS_UNREVIEWED", "advisory", "descriptions were written by an agent from the PDF; the accessibility review should confirm them")
    return blockers


# --------------------------------------------------------------------------------------------- pack

def _html_paragraph(text: str) -> str:
    return "<p>" + html.escape(text, quote=False).replace("\n", "<br>") + "</p>"


def render_content(canonical: dict[str, Any]) -> str:
    placed: dict[str, list[dict[str, Any]]] = {}
    for image in canonical["images"]:
        if image["role"] != "content":
            continue
        owner = next((s for s in canonical["sections"] if image["id"] in raw_blocks(s)), None) or next((s for s in canonical["sections"] if s["id"] == image.get("sectionId")), None)
        if owner is None:
            raise LessonContractError("CANONICAL_IMAGE_UNPLACED", f"content image {image['id']} belongs to no section")
        if not image.get("description"):
            continue
        placed.setdefault(owner["id"], []).append(image)
    parts = []
    for section in canonical["sections"]:
        body = [_html_paragraph(p) for p in section["content"].split("\n\n") if p.strip()]
        for image in placed.get(section["id"], []):
            label = f"{image['figureLabel']}. " if image.get("figureLabel") else ""
            body.append(_html_paragraph(f"Mô tả hình: {label}{image['description']}"))
        if body:
            parts.append(f"<section><h2>{html.escape(str(section['heading']), quote=False)}</h2>{''.join(body)}</section>")
    return "\n".join(parts)


def raw_blocks(section: dict[str, Any]) -> set[str]:
    return set(section.get("ownedBlockIds") or []) | set(section["sourceBlockIds"])


def canonical_to_pack(canonical: dict[str, Any], source_blocks: list[dict[str, Any]], allow_unresolved: bool = False) -> dict[str, Any]:
    """The only converter. Candidate and Release Pack both come from this result."""
    if (canonical["contentStatus"] != "resolved" or canonical["unresolvedItems"]) and not allow_unresolved:
        raise LessonContractError("UNRESOLVED_CONTENT", "canonical lesson still has unresolved items", canonical["unresolvedItems"])
    source = canonical["sources"][0]
    if not source.get("accessedAt"):
        raise LessonContractError("MISSING_SOURCE_ACCESSED_AT", "source.accessedAt must be declared in authoring metadata")
    if not source.get("license") or not source.get("attribution"):
        raise LessonContractError("MISSING_SOURCE_LICENSE", "source license and attribution must be declared")
    block_by_id = {b["id"]: b for b in source_blocks}
    metadata = canonical["metadata"]
    lesson_outcomes = set(metadata["outcomeCodes"])
    units = []
    evidence: list[dict[str, Any]] = []

    def marker(block_id: str) -> dict[str, Any]:
        block = block_by_id[block_id]
        return {
            "sourceId": source["id"], "sourceVersion": source["version"], "sourceSha256": source["sha256"],
            "physicalPageIndex": block["physicalPageIndex"], "printedPageLabel": block.get("printedPageLabel"),
            "extractionMethod": block["extractionMethod"], "locator": f"PDF page {block['physicalPageIndex']}, block {block_id}",
        }

    for unit in canonical["knowledgeUnits"]:
        if not unit["outcomeCodes"] or not set(unit["outcomeCodes"]) <= lesson_outcomes:
            raise LessonContractError("MISSING_UNIT_OUTCOME", f"unit {unit['id']} outcomes must be a non-empty subset of the pack outcomes")
        claims = []
        for claim in unit["claims"]:
            if not claim["sourceBlockIds"] or any(b not in block_by_id for b in claim["sourceBlockIds"]):
                raise LessonContractError("CLAIM_EVIDENCE_MISSING", f"claim {claim['id']} has no resolvable source block")
            claims.append({"id": claim["id"], "text": claim["text"], "important": claim["important"], "sourceIds": claim["sourceIds"]})
            seen: set[tuple[int, str]] = set()
            for block_id in claim["sourceBlockIds"]:
                item = marker(block_id)
                if (item["physicalPageIndex"], block_id) not in seen:
                    seen.add((item["physicalPageIndex"], block_id))
                    evidence.append({**item, "claimId": claim["id"]})
        units.append({"id": unit["id"], "outcomeCodes": unit["outcomeCodes"], "claims": claims, "terms": unit["terms"], "misconceptions": unit["misconceptions"]})
    content_blocks = sorted({b for s in canonical["sections"] if s["content"].strip() for b in s["sourceBlockIds"]} | {b for i in canonical["images"] if i["role"] == "content" for b in i["sourceBlockIds"]} | set(canonical["summary"]["sourceBlockIds"]))
    for page in sorted({block_by_id[b]["physicalPageIndex"] for b in content_blocks}):
        first = next(b for b in content_blocks if block_by_id[b]["physicalPageIndex"] == page)
        ids = ",".join(_short(b) for b in content_blocks if block_by_id[b]["physicalPageIndex"] == page)
        evidence.append({**marker(first), "locator": f"PDF page {page}, blocks {ids}", "contentRef": "lesson.content"})
    pack: dict[str, Any] = {
        "key": canonical["packKey"], "title": metadata["title"], "grade": metadata["grade"], "domain": metadata["domain"],
        "chapter": metadata["chapter"], "topic": metadata["topic"], "subjectId": metadata["subjectId"],
        "outcomeCodes": metadata["outcomeCodes"], "synthetic": False,
        "sources": [{"id": source["id"], "title": source["title"], "author": source["author"], "accessedAt": source["accessedAt"], "license": source["license"], "attribution": source["attribution"], "authoritative": source["authoritative"]}],
        "knowledgeUnits": units,
        "lesson": {"learningObjective": metadata["learningObjective"], "prerequisites": metadata["prerequisites"], "content": render_content(canonical), "materials": [], "videos": canonical.get("videos", []), "sections": [{"id": s["id"], "videos": s.get("videos", [])} for s in canonical["sections"]], "questions": [], "labId": None},
        "reviews": {},
    }
    if canonical["basicExercises"]:
        pack["lesson"]["basicExercises"] = canonical["basicExercises"]
    return {"pack": pack, "evidence": evidence, "reviewLog": [], "canonicalContentHash": canonical["contentHash"], "packDigest": _digest(pack)}


# --------------------------------------------------------------------------------------------- apply to Structured JSON

def apply_to_structured(path: Path, lesson: dict[str, Any], canonical: dict[str, Any], workspace_root: Path) -> None:
    """Writes resolved components back into the Structured JSON. The old learningContent is kept untouched under
    learningContentOriginal; the review state is reset to needs_review and the approved artifact is removed."""
    from datetime import datetime, timezone

    if canonical["contentStatus"] != "resolved":
        raise LessonContractError("UNRESOLVED_CONTENT", "only a resolved canonical lesson can be applied")
    original = lesson.get("learningContentOriginal") or json.loads(json.dumps(lesson["learningContent"]))
    lesson["learningContentOriginal"] = original
    old = lesson["learningContent"]
    lesson["learningContent"] = {
        **old,
        "sections": [{"id": s["id"], "heading": s["heading"], "content": s["content"], "sourceBlockIds": s["sourceBlockIds"]} for s in canonical["sections"] if s["content"].strip()],
        "summary": canonical["summary"]["text"],
        "summarySourceBlockIds": canonical["summary"]["sourceBlockIds"],
        "knowledgeUnits": [{"id": u["id"], "title": u["title"], "claims": [{"id": c["id"], "text": c["text"], "sourceBlockIds": c["sourceBlockIds"]} for c in u["claims"]], "terms": u["terms"], "misconceptions": u["misconceptions"], "sourceBlockIds": sorted({b for c in u["claims"] for b in c["sourceBlockIds"]})} for u in canonical["knowledgeUnits"]],
        "formulas": canonical["formulas"],
        "tables": canonical["tables"],
        "sourceImages": [{"id": i["id"], "pdfPage": i["pdfPage"], "bbox": i["bbox"], "sourceBlockIds": i["sourceBlockIds"], "status": "described" if i["role"] == "content" else "decorative", "description": i["description"], "reason": i["reason"]} for i in canonical["images"]],
        "basicExercises": canonical["basicExercises"] or [],
    }
    lesson["resolvedFrom"] = {"canonicalContentHash": canonical["contentHash"], "inputFingerprint": canonical["inputFingerprint"], "appliedContentDigest": _digest(lesson["learningContent"])}
    review = lesson.get("contentReview") if isinstance(lesson.get("contentReview"), dict) else {"history": []}
    history = list(review.get("history", []))
    history.append({"action": "canonical_applied", "contentHash": canonical["contentHash"], "at": datetime.now(timezone.utc).isoformat()})
    lesson["contentReview"] = {"status": "needs_review", "history": history}
    lesson["updatedAt"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(lesson, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (workspace_root / "exports" / "approved-structured" / path.name).unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------- orchestration

def resolve_lesson(workspace_root: Path, lesson_id: str, lesson_dir: Path, apply: bool = True) -> dict[str, Any]:
    """Builds canonical.json when every item has a valid, current decision. Otherwise writes the blocked report."""
    path, lesson = load_structured(workspace_root, lesson_id)
    authoring = _read(lesson_dir / "authoring.json")
    if authoring is None:
        raise LessonContractError("AUTHORING_MISSING", f"{lesson_dir / 'authoring.json'} is required")
    decisions_doc = _read(lesson_dir / "decisions.json")
    canonical, errors = build_canonical(lesson, decisions_doc, authoring, lesson_id)
    if errors:
        report = {"kind": "blocked-report", "lessonId": lesson_id, "contentResolved": False, "inputFingerprint": canonical["inputFingerprint"], "problems": errors}
        return {"resolved": False, "report": report, "canonical": canonical}
    _write(lesson_dir / "canonical.json", canonical)
    if apply:
        apply_to_structured(path, lesson, canonical, workspace_root)
    return {"resolved": True, "canonical": canonical, "canonicalPath": str(lesson_dir / "canonical.json")}


def load_resolved(workspace_root: Path, lesson_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Canonical plus the Structured JSON it must still match. A stale or unresolved canonical raises."""
    canonical_path = find_canonical(workspace_root, lesson_id)
    if canonical_path is None:
        raise LessonContractError("CANONICAL_MISSING", f"no canonical lesson for {lesson_id}")
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    _, lesson = load_structured(workspace_root, lesson_id)
    if canonical["contentStatus"] != "resolved" or canonical["unresolvedItems"]:
        raise LessonContractError("UNRESOLVED_CONTENT", "canonical lesson is not resolved", canonical["unresolvedItems"])
    if canonical["inputFingerprint"] != lesson_fingerprint(lesson):
        raise LessonContractError("STALE_DECISION", "the Structured JSON input changed after the canonical lesson was built")
    resolved_from = lesson.get("resolvedFrom") or {}
    if resolved_from.get("canonicalContentHash") != canonical["contentHash"]:
        raise LessonContractError("CANONICAL_NOT_APPLIED", "Structured JSON does not carry this canonical content; run resolve-lesson")
    if resolved_from.get("appliedContentDigest") != _digest(lesson["learningContent"]):
        raise LessonContractError("STALE_DECISION", "learningContent was edited after the canonical lesson was applied; resolve again")
    expected = _digest({k: v for k, v in canonical.items() if k != "contentHash"})
    if expected != canonical["contentHash"]:
        raise LessonContractError("STALE_DECISION", "canonical contentHash does not match its content")
    return canonical, lesson
