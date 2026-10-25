"""Preview merge of edited Structured Lesson content with the full source reading.

Inputs per lesson: ``learningContent`` (edited, may be stale) and ``sourceReading``
(full OCR of the same sections, with ``sourceBlocks`` giving block ids and pages).

The preview is read-only: it writes only the folder it is given. Nothing is
decided by similarity. Similarity only proposes a pair for a person to decide,
and such a pair is held out of the merged text together with both texts, the
word-level diff and the source block ids and pages.

Every sentence unit on both sides gets exactly one disposition:

* source units:   ``emitted`` (in merged text), ``held`` (waiting for a decision),
                  ``excluded`` (with a reason taken from the block type)
* learning units: ``matched`` (same text as an emitted source unit),
                  ``superseded`` (contained in source units, no extra words),
                  ``matched_elsewhere`` (exact text found in another section),
                  ``held`` (waiting for a decision), ``excluded``

A unit without a disposition is reported in ``losses.json``. The report says
"accounted for", not "preserved": held items are accounted for, not resolved.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)")
PLACEHOLDER = re.compile(r"\[Hình từ PDF trang (\d+); cần mô tả thủ công\]")
EXCLUDED_TYPES = {"page_number"}  # pure page numbers only
REVIEW_TYPES = {"header", "footer", "doc_title"}  # may hold captions or titles: a person decides
NEAR_RATIO = 0.9
ALGORITHM_VERSION = "structured-merge@4"
MIN_CUT_TOKENS = 3
DECISION = {
    "near_pair": "Chọn bản nguồn hoặc bản biên tập; bản không chọn ghi lý do.",
    "covering_extra": "Phần chữ thêm trong bản biên tập: xác nhận đưa vào hoặc loại có lý do.",
    "learning_only": "Bản biên tập không có trong nguồn: xác nhận có nguồn (block nào) hoặc loại có lý do.",
    "table_review": "Bảng trong bản biên tập: đối chiếu với block bảng nguồn và ảnh PDF.",
    "block_type_review": "Khối nguồn loại tiêu đề, chân trang hoặc tiêu đề tài liệu: giữ vào nội dung hay loại có lý do.",
    "provenance_review": "Đơn vị không khớp block nào trong section; chỉ khớp block ngoài section có loại không-nội-dung. Người duyệt xác định nguồn.",
}


def norm(text: Any) -> str:
    """Canonical form for equality: NFC, single spaces. Nothing else is removed."""
    return " ".join(unicodedata.normalize("NFC", str(text or "")).replace(" ", " ").split())


def fold(text: Any) -> str:
    """Accent-free form. Only for finding candidates; never used to decide equality."""
    decomposed = unicodedata.normalize("NFD", norm(text))
    plain = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").replace("đ", "d").replace("Đ", "D")
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", plain.lower()).split())


def _tokens(text: str) -> int:
    return len(text.split())


def _unit(text: str, *, table: bool = False, para_end: bool = False) -> dict[str, Any]:
    pages = [int(page) for page in PLACEHOLDER.findall(text)]
    return {"text": norm(PLACEHOLDER.sub("", text)), "table": table, "paraEnd": para_end, "placeholderPages": pages}


def split_units(text: str | None) -> list[dict[str, Any]]:
    """Sentence units. A blank line ends a paragraph, a single newline is an OCR wrap, table rows stay whole."""
    units: list[dict[str, Any]] = []
    for paragraph in re.split(r"\n\s*\n", text or ""):
        buffer: list[str] = []
        for line in paragraph.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("|"):
                _flush(buffer, units)
                units.append(_unit(line, table=True, para_end=True))
            else:
                buffer.append(line)
        _flush(buffer, units)
        if units:
            units[-1]["paraEnd"] = True
    return units


def _flush(buffer: list[str], units: list[dict[str, Any]]) -> None:
    if not buffer:
        return
    parts = [part.strip() for part in SENTENCE_END.split(" ".join(buffer)) if part.strip()]
    for position, part in enumerate(parts):
        units.append(_unit(part, para_end=position == len(parts) - 1))
    buffer.clear()


def build_block_index(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": block.get("id"), "type": block.get("type"), "text": norm(block.get("normalizedText") or block.get("text") or ""), "page": block.get("physicalPageIndex")}
        for block in lesson.get("sourceBlocks") or []
    ]


def trace(text: str, blocks: list[dict[str, Any]], preferred: set[str]) -> dict[str, Any]:
    """Blocks that hold this text. Blocks of the unit's own section are searched first; a block outside the
    section is used only when none of them holds the text, and is marked as such."""
    empty = {"blockIds": [], "pages": [], "types": [], "provenance": "none"}
    if not text:
        return empty

    def hits_in(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        exact = [b for b in pool if b["text"] == text]
        return exact or [b for b in pool if f" {text} " in f" {b['text']} "]

    inside = hits_in([b for b in blocks if b["id"] in preferred]) if preferred else []
    if inside:
        chosen, provenance = inside, "section"
    else:
        chosen = hits_in(blocks)
        if not chosen:
            return empty
        provenance = "outside_section"
    return {
        "blockIds": [b["id"] for b in chosen],
        "pages": sorted({b["page"] for b in chosen if b["page"] is not None}),
        "types": sorted({b["type"] for b in chosen if b["type"]}),
        "provenance": provenance,
    }


def _prepare(units: list[dict[str, Any]], blocks: list[dict[str, Any]], preferred: set[str], side: str) -> list[dict[str, Any]]:
    for index, unit in enumerate(units):
        unit["index"] = index
        unit["side"] = side
        unit["trace"] = trace(unit["text"], blocks, preferred)
        types = set(unit["trace"]["types"])
        section_bound = unit["trace"]["provenance"] == "section"
        if not unit["text"]:
            unit["excluded"] = "placeholder hình (tạo tự động)" if unit["placeholderPages"] else "không có nội dung"
        elif section_bound and types and types <= EXCLUDED_TYPES:
            unit["excluded"] = "block loại " + "/".join(sorted(types))
        else:
            unit["excluded"] = None
        unit["reviewType"] = section_bound and bool(types) and types <= REVIEW_TYPES
        # A non-content block match from outside the section decides nothing: a person must place the unit.
        unit["provenanceReview"] = bool(types) and not section_bound and bool(types & (EXCLUDED_TYPES | REVIEW_TYPES))
    return units


def classify(learning: dict[str, Any], source: dict[str, Any]) -> str | None:
    if not learning["text"] or not source["text"]:
        return None
    if learning["text"] == source["text"]:
        return "exact"
    if _tokens(learning["text"]) >= MIN_CUT_TOKENS and f" {learning['text']} " in f" {source['text']} " and len(learning["text"]) >= 0.5 * len(source["text"]):
        return "cut"
    lt, st = learning["text"].split(), source["text"].split()
    # Same word count with at most two different words: a structural near copy (e.g. "+" vs "-", "bị" vs "bi", a changed number).
    if len(lt) == len(st) >= 2 and sum(a != b for a, b in zip(lt, st)) <= 2:
        return "near"
    if 0.9 <= len(learning["text"]) / len(source["text"]) <= 1.1 and _tokens(source["text"]) >= 2:
        if difflib.SequenceMatcher(None, learning["text"], source["text"], autojunk=False).ratio() >= NEAR_RATIO:
            return "near"
    return None


def candidate_blocks(text: str, blocks: list[dict[str, Any]], preferred: set[str], limit: int = 2) -> list[dict[str, Any]]:
    """Evidence for a reviewer, never a decision: section blocks whose accent-free text is most similar, with the score."""
    target = fold(text)
    pool = [b for b in blocks if b["id"] in preferred] if preferred else blocks
    scored = []
    for block in pool:
        score = difflib.SequenceMatcher(None, target, fold(block["text"]), autojunk=False).ratio()
        if score >= 0.5:
            scored.append({"blockId": block["id"], "page": block["page"], "score": round(score, 3)})
    return sorted(scored, key=lambda item: -item["score"])[:limit]


def _evidence(unit: dict[str, Any], blocks: list[dict[str, Any]], preferred: set[str]) -> dict[str, Any]:
    """How a reviewer can check this side: an exact block trace, candidate blocks, or an explicit 'none'."""
    if unit["trace"]["blockIds"]:
        return {"status": "block", "candidateBlocks": []}
    candidates = candidate_blocks(unit["text"], blocks, preferred)
    return {"status": "candidate" if candidates else "none", "candidateBlocks": candidates}


def _view(unit: dict[str, Any]) -> dict[str, Any]:
    return {"text": unit["text"], "index": unit["index"], "blockIds": unit["trace"]["blockIds"], "pages": unit["trace"]["pages"], "types": unit["trace"]["types"], "provenance": unit["trace"]["provenance"]}


def _word_diff(learning: str, source: str) -> list[dict[str, str]]:
    left, right = learning.split(" "), source.split(" ")
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag != "equal":
            ops.append({"op": tag, "learning": " ".join(left[i1:i2]), "source": " ".join(right[j1:j2])})
    return ops


def merge_section(learning: dict[str, Any] | None, source: dict[str, Any] | None, blocks: list[dict[str, Any]], lesson_source_flat: str = "", scope: str = "") -> dict[str, Any]:
    preferred = set((source or {}).get("sourceBlockIds") or []) | set((learning or {}).get("sourceBlockIds") or [])
    section_id = (source or learning or {}).get("id")
    S = _prepare(split_units((source or {}).get("content")), blocks, preferred, "S")
    L = _prepare(split_units((learning or {}).get("content")), blocks, preferred, "L")
    disp_S: dict[int, dict[str, Any]] = {}
    disp_L: dict[int, dict[str, Any]] = {}
    held: list[dict[str, Any]] = []

    seen_ids: Counter = Counter()

    def hold(kind: str, s: dict[str, Any] | None, l: dict[str, Any] | None, **extra: Any) -> None:
        item = {
            "kind": kind,
            "decisionNeeded": DECISION[kind],
            "source": _view(s) if s else None,
            "learning": _view(l) if l else None,
            "evidence": {"source": _evidence(s, blocks, preferred) if s else None, "learning": _evidence(l, blocks, preferred) if l else None},
            **extra,
        }
        # The id comes from content, not from position: adding an earlier item cannot move later ids.
        basis = "\x1f".join([scope, str(section_id), kind, s["text"] if s else "", l["text"] if l else ""])
        digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
        seen_ids[digest] += 1
        hid = f"{kind}-{digest}" + (f"-{seen_ids[digest]}" if seen_ids[digest] > 1 else "")
        held.append(item)
        item["id"] = hid
        if s:
            disp_S[s["index"]] = {"disposition": "held", "heldId": hid}
        if l:
            disp_L[l["index"]] = {"disposition": "held", "heldId": hid}

    for unit in S + L:
        if unit["excluded"]:
            target = disp_S if unit["side"] == "S" else disp_L
            target[unit["index"]] = {"disposition": "excluded", "reason": unit["excluded"]}

    s_work = [u for u in S if not u["excluded"] and not u["table"]]
    l_work = [u for u in L if not u["excluded"] and not u["table"]]
    s_by_idx = {u["index"]: u for u in s_work}
    l_by_idx = {u["index"]: u for u in l_work}

    pairs: list[tuple[int, int, str]] = []
    near: list[tuple[int, int]] = []
    matcher = difflib.SequenceMatcher(None, [u["text"] for u in l_work], [u["text"] for u in s_work], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs += [(l_work[i1 + k]["index"], s_work[j1 + k]["index"], "exact") for k in range(i2 - i1)]
            continue
        cursor = j1
        for i in range(i1, i2):
            for j in range(cursor, j2):
                kind = classify(l_work[i], s_work[j])
                if kind:
                    (near if kind == "near" else pairs).append((l_work[i]["index"], s_work[j]["index"]) if kind == "near" else (l_work[i]["index"], s_work[j]["index"], kind))
                    cursor = j + 1
                    break

    def paired_sets() -> tuple[set[int], set[int]]:
        return {p[0] for p in pairs} | {n[0] for n in near}, {p[1] for p in pairs} | {n[1] for n in near}

    # Same text at another position, then fragments anywhere in the section.
    for l in l_work:
        pl, ps = paired_sets()
        if l["index"] in pl:
            continue
        for s in s_work:
            if s["index"] not in ps and classify(l, s) in {"exact", "cut"}:
                pairs.append((l["index"], s["index"], classify(l, s)))
                break
    pl, ps = paired_sets()
    unpaired_l = [l for l in l_work if l["index"] not in pl]
    unpaired_s = [s for s in s_work if s["index"] not in ps]

    # Source sentences held inside one learning sentence, and learning sentences held as near copies.
    covers: dict[int, list[int]] = {}
    for l in unpaired_l:
        inside = [s["index"] for s in unpaired_s if _tokens(s["text"]) >= MIN_CUT_TOKENS and f" {s['text']} " in f" {l['text']} "]
        if inside:
            covers[l["index"]] = inside
    covered_s = {j for js in covers.values() for j in js}
    for l in unpaired_l:
        if l["index"] in covers:
            continue
        for s in unpaired_s:
            if s["index"] not in covered_s and s["index"] not in {n[1] for n in near} and classify(l, s) == "near":
                near.append((l["index"], s["index"]))
                break

    for l_idx, s_idx in near:
        hold("near_pair", s_by_idx[s_idx], l_by_idx[l_idx], diff=_word_diff(l_by_idx[l_idx]["text"], s_by_idx[s_idx]["text"]))
    covered_held: set[int] = set()
    for l_idx, s_idxs in covers.items():
        remainder = l_by_idx[l_idx]["text"]
        for s_idx in s_idxs:
            remainder = remainder.replace(s_by_idx[s_idx]["text"], " ", 1)
        remainder = " ".join(remainder.split())
        # Only sentence punctuation may disappear silently. Operators, signs, letters and digits left over are a decision.
        if re.fullmatch(r"[\s.;:,!?…]*", remainder):
            disp_L[l_idx] = {"disposition": "superseded", "coveredSourceIndexes": s_idxs}
        else:
            covered_held.update(s_idxs)
            hold("covering_extra", s_by_idx[s_idxs[0]], l_by_idx[l_idx], remainder=remainder, coveredSourceIndexes=s_idxs)
            for s_idx in s_idxs:
                disp_S[s_idx] = {"disposition": "held", "heldId": held[-1]["id"]}
    for l in unpaired_l:
        if l["index"] in covers or l["index"] in {n[0] for n in near}:
            continue
        if _tokens(l["text"]) >= MIN_CUT_TOKENS and f" {l['text']} " in lesson_source_flat:
            disp_L[l["index"]] = {"disposition": "matched_elsewhere"}
        else:
            hold("learning_only", None, l)

    for l_idx, s_idx, kind in pairs:
        disp_S[s_idx] = {"disposition": "emitted", "how": kind, "learningIndex": l_idx}
        disp_L[l_idx] = {"disposition": "matched", "how": kind, "sourceIndex": s_idx}
    for j in covered_s - covered_held:
        disp_S[j] = {"disposition": "emitted", "how": "covering_learning", "learningIndexes": [l for l, js in covers.items() if j in js]}
    for s in unpaired_s:
        if s["index"] not in disp_S:
            disp_S[s["index"]] = {"disposition": "emitted", "how": "added"}

    for l in L:
        if l["table"] and not l["excluded"]:
            twin = next((s for s in S if s["text"] == l["text"]), None)
            if twin:
                disp_L[l["index"]] = {"disposition": "matched", "how": "exact_table", "sourceIndex": twin["index"]}
                disp_S[twin["index"]] = {"disposition": "emitted", "how": "exact_table", "learningIndex": l["index"]}
            else:
                hold("table_review", None, l)

    for s in S:
        if s["reviewType"] and disp_S.get(s["index"], {}).get("disposition") == "emitted":
            hold("block_type_review", s, None)
        elif s["provenanceReview"] and disp_S.get(s["index"], {}).get("disposition") == "emitted":
            hold("provenance_review", s, None)
    for s in S:
        if s["table"] and not s["excluded"] and s["index"] not in disp_S:
            disp_S[s["index"]] = {"disposition": "emitted", "how": "table_source"}

    # Held items for near pairs were added first; mark the source side of every near pair as held.
    for item in held:
        if item["kind"] == "near_pair" and item["source"]:
            disp_S[item["source"]["index"]] = {"disposition": "held", "heldId": item["id"]}

    merged_parts: list[str] = []
    previous: dict[str, Any] | None = None
    for unit in S:
        if disp_S.get(unit["index"], {}).get("disposition") != "emitted":
            continue
        if previous is not None:
            merged_parts.append("\n\n" if previous["paraEnd"] else " ")
        merged_parts.append(unit["text"])
        previous = unit

    lost_S = [u["index"] for u in S if u["index"] not in disp_S]
    lost_L = [u["index"] for u in L if u["index"] not in disp_L]
    return {
        "id": (source or learning or {}).get("id"),
        "heading": (source or learning or {}).get("heading"),
        "status": "added_section" if learning is None else "L_only_section" if source is None else "merged",
        "merged": "".join(merged_parts),
        "sourceUnits": [{"index": u["index"], "text": u["text"], **disp_S.get(u["index"], {"disposition": None}), "blockIds": u["trace"]["blockIds"], "pages": u["trace"]["pages"], "provenance": u["trace"]["provenance"], "paraEnd": u["paraEnd"]} for u in S],
        "learningUnits": [{"index": u["index"], "text": u["text"], **disp_L.get(u["index"], {"disposition": None}), "blockIds": u["trace"]["blockIds"], "pages": u["trace"]["pages"], "provenance": u["trace"]["provenance"]} for u in L],
        "held": held,
        "lostSource": lost_S,
        "sectionInputHash": hashlib.sha256(json.dumps([(learning or {}).get("content"), (source or {}).get("content")], ensure_ascii=False).encode("utf-8")).hexdigest(),
        "lostLearning": lost_L,
        "countsSource": dict(Counter(d.get("disposition") for d in disp_S.values())),
        "countsLearning": dict(Counter(d.get("disposition") for d in disp_L.values())),
    }


def lesson_fingerprint(lesson: dict[str, Any]) -> str:
    """Hash of everything a decision depends on: algorithm version, book hash and version, every source block
    (id, type, text, page), both section lists with headings. The learning side is the original content."""
    learning = (lesson.get("learningContentOriginal") or lesson.get("learningContent") or {}).get("sections") or []
    source = (lesson.get("sourceReading") or {}).get("sections") or []
    book = lesson.get("book") or {}

    def sec(s: dict[str, Any]) -> dict[str, Any]:
        return {"id": s.get("id"), "heading": s.get("heading"), "content": s.get("content"), "sourceBlockIds": s.get("sourceBlockIds")}

    basis = {
        "algorithm": ALGORITHM_VERSION,
        "book": {"sha256": book.get("sha256"), "version": book.get("version")},
        "blocks": [
            {"id": b.get("id"), "type": b.get("type"), "text": b.get("normalizedText") or b.get("text"), "page": b.get("physicalPageIndex"), "bbox": b.get("bbox"), "method": b.get("extractionMethod")}
            for b in lesson.get("sourceBlocks") or []
        ],
        "source": [sec(s) for s in source],
        "learning": [sec(s) for s in learning],
    }
    return hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_lesson(lesson: dict[str, Any]) -> dict[str, Any]:
    learning = (lesson.get("learningContentOriginal") or lesson.get("learningContent") or {}).get("sections") or []
    source = (lesson.get("sourceReading") or {}).get("sections") or []
    blocks = build_block_index(lesson)
    for side, sections_ in (("sourceReading", source), ("learningContent", learning)):
        for position, section in enumerate(sections_):
            if not isinstance(section, dict):
                raise ValueError(f"{side}.sections[{position}] is not an object")
            if not isinstance(section.get("id"), str) or not section["id"].strip():
                raise ValueError(f"{side}.sections[{position}] has a missing or empty id")
        seen = Counter(s["id"] for s in sections_)
        dup = [k for k, v in seen.items() if v > 1]
        if dup:
            raise ValueError(f"{side} has duplicate section ids: {dup[:5]}")
    learning_by_id = {section["id"]: section for section in learning}
    source_by_id = {section["id"]: section for section in source}
    ids = list(dict.fromkeys([s["id"] for s in source] + [s["id"] for s in learning]))
    lesson_flat = " " + " ".join(norm(s.get("content")) for s in source) + " "
    scope = str((lesson.get("sourceLesson") or {}).get("id", ""))
    sections = [merge_section(learning_by_id.get(sid), source_by_id.get(sid), blocks, lesson_flat, scope) for sid in ids]
    fingerprint = lesson_fingerprint(lesson)
    for section in sections:
        section["fingerprint"] = fingerprint
        for item in section["held"]:
            item["fingerprint"] = fingerprint
    return {"sourceLesson": lesson.get("sourceLesson"), "sections": sections, "blocks": blocks, "fingerprint": fingerprint}


def build_preview(structured_dir: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    held_all: list[dict[str, Any]] = []
    losses: list[dict[str, Any]] = []
    pending_blocks: list[dict[str, Any]] = []
    totals: Counter = Counter()
    summary: dict[str, Any] = {"lessons": 0, "sections": 0, "lostSource": 0, "lostLearning": 0, "held": 0}
    for path in sorted(structured_dir.glob("*.json")):
        lesson = json.loads(path.read_text(encoding="utf-8"))
        built = build_lesson(lesson)
        lesson_id = (lesson.get("sourceLesson") or {}).get("id", path.stem)
        merged_flat = " " + " ".join(norm(s["merged"]) for s in built["sections"]) + " "
        held_ids: set[str] = set()
        for section in built["sections"]:
            summary["sections"] += 1
            summary["lostSource"] += len(section["lostSource"])
            summary["lostLearning"] += len(section["lostLearning"])
            for index in section["lostSource"]:
                losses.append({"lesson": lesson_id, "sectionId": section["id"], "side": "source", "index": index})
            for index in section["lostLearning"]:
                losses.append({"lesson": lesson_id, "sectionId": section["id"], "side": "learning", "index": index})
            totals.update({f"source.{k}": v for k, v in section["countsSource"].items()})
            totals.update({f"learning.{k}": v for k, v in section["countsLearning"].items()})
            for item in section["held"]:
                held_all.append({"lesson": lesson_id, "sectionId": section["id"], "heading": section["heading"], **item})
                held_ids.add(item["id"])
        summary["lessons"] += 1
        for block in built["blocks"]:
            if block["type"] in EXCLUDED_TYPES:
                status = "excluded"
            elif block["type"] in REVIEW_TYPES:
                status = "review_type"
            elif block["type"] in {"image", "figure"}:
                status = "pending_image"
            elif not block["text"]:
                status = "excluded"
            elif f" {block['text']} " in merged_flat:
                status = "in_merged"
            else:
                status = "held_or_unplaced"
            if status in {"pending_image", "held_or_unplaced"}:
                pending_blocks.append({"lesson": lesson_id, "blockId": block["id"], "type": block["type"], "page": block["page"], "status": status, "text": block["text"][:200]})
        (out_dir / path.name).write_text(json.dumps({"sourceLesson": built["sourceLesson"], "sections": built["sections"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["held"] = len(held_all)
    summary["dispositions"] = dict(totals)
    summary["heldByKind"] = dict(Counter(item["kind"] for item in held_all))
    files = {"held-items.json": held_all, "losses.json": losses, "pending-blocks.json": pending_blocks, "summary.json": summary}
    for name, payload in files.items():
        (out_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(out_dir, summary, pending_blocks)
    return summary


def _write_report(out_dir: Path, summary: dict[str, Any], pending_blocks: list[dict[str, Any]]) -> None:
    lines = [
        "# Merge preview (KHTN 9)",
        "",
        "Read-only. Exports, candidates, packs and review state are not changed.",
        "",
        "## What the numbers mean",
        "- Every source and learning unit has one disposition. `losses.json` lists units without one; it must be empty.",
        "- `held` items are accounted for, not resolved. They are kept out of the merged text until a decision is recorded.",
        "- Equality is exact after NFC normalisation. Symbols, operators, digits and Greek letters are kept.",
        "- Page numbers, headers, footers and document titles are excluded only when their source block has that type.",
        "",
        "## Counts",
        f"- Lessons: {summary['lessons']}, sections: {summary['sections']}",
        f"- Units without a disposition: source {summary['lostSource']}, learning {summary['lostLearning']}",
        f"- Held items: {summary['held']} `{json.dumps(summary.get('heldByKind', {}), ensure_ascii=False)}`",
        f"- Dispositions: `{json.dumps(summary.get('dispositions', {}), ensure_ascii=False)}`",
        "",
        "## Blocks not placed in merged text",
        f"- By status: `{json.dumps(dict(Counter(b['status'] for b in pending_blocks)), ensure_ascii=False)}`",
        "- Details in pending-blocks.json.",
        "",
    ]
    (out_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only preview of learningContent merged with sourceReading.")
    parser.add_argument("structured_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_preview(args.structured_dir, args.out_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
