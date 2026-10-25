from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections import defaultdict
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .workspace import ContentToolError, Workspace, read_json, write_json


_JUNK = re.compile(r"^[\W_\d]+$", re.UNICODE)
_LEADING_NUMBER = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]?|[a-z][.)])\s*", re.IGNORECASE)
_OCR_GARBAGE = re.compile(r"(?:�|\b(?:lorem|ipsum)\b|[\u0000-\u0008\u000b\u000c\u000e-\u001f])", re.IGNORECASE)
_OBJECTIVE_VERBS = (
    "nêu", "kể", "mô tả", "giải thích", "trình bày", "phân tích", "vận dụng", "thực hiện", "lấy ví dụ",
    "phát biểu", "tiến hành", "đọc", "viết", "xác định", "liệt kê", "thảo luận", "quan sát", "chứng minh",
    "xây dựng", "điều tra", "nhận biết", "so sánh", "phân loại", "tính", "đánh giá", "đề xuất", "mắc",
    "vẽ", "dự đoán", "tìm hiểu", "nhận xét", "kết luận", "sử dụng", "khẳng định", "rút ra", "đo",
    "trả lời", "thu thập", "báo cáo", "trình diễn", "phân biệt", "lựa chọn", "giải quyết", "sắp xếp",
    "describe", "explain", "identify", "calculate", "compare", "analyze", "apply", "demonstrate",
    "construct", "measure", "classify", "evaluate", "predict", "use", "list", "define", "interpret", "investigate",
)
_BE_OUTCOME_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,39}$")
_WEAK_OBJECTIVE_VERBS = ("tìm hiểu", "thảo luận", "understand", "learn about")
_LAB_SIGNALS = {
    "experiment": ("thí nghiệm", "thuc hanh", "thực hành", "experiment"),
    "observation": ("quan sát", "quan sat", "observe", "nhận xét"),
    "measurement": ("đo", "đo đạc", "measure", "xác định bằng dụng cụ"),
    "modeling": ("mô hình", "mo hinh", "mô phỏng", "mo phong", "simulation"),
}


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _clean_text(value: Any, *, allow_concept_label: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value)
    text = _LEADING_NUMBER.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n:;,.|–—-")
    min_length = 3 if allow_concept_label else 5
    if not min_length <= len(text) <= 500 or _JUNK.fullmatch(text) or _OCR_GARBAGE.search(text):
        return None
    letters = sum(char.isalpha() for char in text)
    if letters < 4 or letters / max(1, len(text)) < 0.25:
        return None
    words = _fold(text).split()
    if (len(words) < 2 and not allow_concept_label) or len(set(words)) == 1 and len(words) > 3:
        return None
    return text


def _source_block_text(block: dict[str, Any]) -> str:
    return str(block.get("reviewedText") or block.get("normalizedText") or block.get("originalText") or "").strip()


def _is_objective_statement(value: str) -> bool:
    text = _fold(_LEADING_NUMBER.sub("", value.strip().lstrip("■•-+\\"))).strip()
    return any(text == _fold(verb) or text.startswith(_fold(verb) + " ") for verb in _OBJECTIVE_VERBS)


def _is_measurable_objective_statement(value: str) -> bool:
    text = _fold(_LEADING_NUMBER.sub("", value.strip().lstrip("■•-+\\"))).strip()
    return _is_objective_statement(value) and not any(text == _fold(verb) or text.startswith(_fold(verb) + " ") for verb in _WEAK_OBJECTIVE_VERBS)


def _extract_source_objectives(lesson: dict[str, Any], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select existing text under a Mục tiêu heading; never OCR or infer wording."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, block in enumerate(blocks):
        if _fold(_source_block_text(block)).strip(" .:") != "muc tieu":
            continue
        for candidate in blocks[index + 1:]:
            if candidate.get("type") in {"paragraph_title", "header", "doc_title"}:
                break
            if candidate.get("type") != "text":
                continue
            text = _source_block_text(candidate)
            if _is_objective_statement(text):
                block_id = candidate.get("id")
                identity = (str(block_id or ""), _fold(text))
                if identity not in seen:
                    seen.add(identity)
                    rows.append({"id": block_id or f"objective-block-{index}", "text": text, "sourceBlockIds": [block_id] if block_id else [], "sourceMethod": "existing_structured_source_block_under_objective_heading"})
                continue
            if rows and len(text) > 20:
                break
    return rows


_STOP_WORDS = {_fold(word) for word in (
    "các", "một", "được", "về", "trong", "là", "và", "của", "sự", "để", "cho", "từ", "theo", "này", "đó",
    "những", "có", "tại", "với", "trên", "đến", "cơ", "bản", "vai", "trò", "nêu", "trình", "thực", "hiện",
    "được", "một số", "số", "và", "hoặc", "về", "của", "các", "làm", "khi", "nào", "như", "để",
)}


def _content_terms(value: str) -> set[str]:
    return {word for word in _fold(value).split() if len(word) > 2 and word not in _STOP_WORDS}


def _mapping_overlap(source_text: str, outcome_text: str) -> tuple[float, list[str]]:
    source_terms, outcome_terms = _content_terms(source_text), _content_terms(outcome_text)
    shared = sorted(source_terms & outcome_terms)
    score = len(shared) / max(1, min(len(source_terms), len(outcome_terms)))
    return score, shared


def _quality_gate(candidate: dict[str, Any], *, measurable: bool) -> None:
    evidence = candidate["evidence"]
    grounded = bool(candidate["evidenceSourceBlockIds"]) and all(
        evidence_item["sourceBlockIds"]
        and re.fullmatch(r"[a-fA-F0-9]{64}", str(evidence_item.get("bookSha256", "")))
        for evidence_item in evidence
    )
    has_objective = candidate["candidateType"] == "textbook_derived_internal_outcome"
    candidate["qualityGate"] = {
        "measurability": "pass" if measurable and has_objective else "needs_review" if has_objective else "not_an_objective",
        "sourceGrounding": "pass" if grounded else "fail",
        "sourceTextFidelity": "not_independently_verified",
        "structuredContentReview": sorted({str(item.get("sourceTextReviewStatus", "unknown")) for item in evidence}),
        "semanticReuse": "ambiguous" if candidate["ambiguity"] else "exact_existing_match" if candidate["existingOutcomeMatches"] else "deduplicated_across_sources" if len(evidence) > 1 else "unique_candidate",
        "stableIdentity": "pass",
        "validLessonLink": "pass" if all(item.get("sourceLessonId") and item.get("lessonIdentity") for item in evidence) else "fail",
        "officialCurriculumClaim": "none",
        "internalOutcomeEligible": bool(has_objective and measurable and grounded),
        "internalReviewApproved": False,
    }
    candidate["officialCode"] = None
    candidate["status"] = "needs_human_review"


def _build_review_queue(outcomes: list[dict[str, Any]], concepts: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(evidence: dict[str, Any], topic_title: str, item: dict[str, Any]) -> None:
        key = (str(evidence.get("bookKey", "")), str(evidence.get("chapterId", "")), str(evidence.get("lessonIdentity", "")))
        group = grouped.setdefault(key, {
            "bookKey": evidence.get("bookKey"),
            "bookVersion": evidence.get("bookVersion"),
            "bookSha256": evidence.get("bookSha256"),
            "chapterId": evidence.get("chapterId"),
            "chapterTitle": evidence.get("chapterTitle"),
            "lessonIdentity": evidence.get("lessonIdentity"),
            "sourceLessonId": evidence.get("sourceLessonId"),
            "sourceLessonTitle": evidence.get("sourceLessonTitle"),
            "topics": {},
        })
        topic = group["topics"].setdefault(topic_title or "Lesson objectives", {"sourceTopicTitle": topic_title or "Lesson objectives", "items": []})
        topic["items"].append(item)

    for candidate in outcomes:
        priority = 0 if candidate["ambiguity"] else 1
        for evidence in candidate["evidence"]:
            add(evidence, evidence.get("sourceTopicTitle"), {
                "priority": priority,
                "type": "internal_outcome_candidate",
                "candidateId": candidate["id"],
                "statement": candidate["statement"],
                "qualityGate": candidate["qualityGate"],
                "ambiguity": candidate["ambiguity"],
                "evidence": {"sourceBlockIds": evidence["sourceBlockIds"], "pages": evidence["pages"], "bookSha256": evidence["bookSha256"]},
            })
    for candidate in concepts:
        priority = 0 if candidate["ambiguity"] else 2
        for evidence in candidate["evidence"]:
            add(evidence, evidence.get("sourceTopicTitle"), {
                "priority": priority,
                "type": "source_concept_heading",
                "candidateId": candidate["id"],
                "statement": candidate["statement"],
                "qualityGate": candidate["qualityGate"],
                "ambiguity": candidate["ambiguity"],
                "evidence": {"sourceBlockIds": evidence["sourceBlockIds"], "pages": evidence["pages"], "bookSha256": evidence["bookSha256"]},
            })
    concepts_by_id = {item["id"]: item for item in concepts}
    for mapping in mappings:
        concept = concepts_by_id.get(mapping["sourceConceptId"])
        evidence = next((row for row in (concept or {}).get("evidence", []) if row["lessonIdentity"] == mapping["lessonIdentity"] and row["knowledgeUnitId"] == mapping["knowledgeUnitId"]), None)
        if not evidence:
            continue
        add(evidence, evidence.get("sourceTopicTitle"), {
            "priority": 0 if mapping["ambiguity"] or not mapping["outcomeId"] else 1,
            "type": "knowledge_unit_outcome_mapping",
            **mapping,
            "evidence": {"sourceBlockIds": mapping["sourceBlockIds"], "pages": evidence["pages"], "bookSha256": evidence["bookSha256"]},
        })

    result = []
    for group in grouped.values():
        topics = []
        for topic in group.pop("topics").values():
            topic["items"].sort(key=lambda item: (item["priority"], item["type"], item.get("candidateId", item.get("mappingId", ""))))
            topics.append(topic)
        group["topics"] = sorted(topics, key=lambda item: item["sourceTopicTitle"].casefold())
        group["priority"] = min((item["priority"] for topic in topics for item in topic["items"]), default=3)
        result.append(group)
    return sorted(result, key=lambda item: (item["priority"], str(item["bookKey"]), str(item["chapterId"]), str(item["sourceLessonTitle"])))


def _candidate_id(text: str) -> str:
    # Preserve word order so claims with reversed relationships do not merge.
    semantic_key = _fold(text)
    return "out-" + hashlib.sha256(semantic_key.encode("utf-8")).hexdigest()[:20]


def _mapping_id(kind: str, *parts: str) -> str:
    return "map-" + hashlib.sha256("|".join((kind, *parts)).encode("utf-8")).hexdigest()[:20]


def _pages(unit: dict[str, Any], blocks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for block_id in unit.get("sourceBlockIds", []):
        block = blocks.get(block_id, {})
        if block:
            ref = {"sourceBlockId": block_id}
            for key in ("physicalPageIndex", "printedPageLabel", "sourceSha256"):
                if block.get(key) is not None:
                    ref[key] = block[key]
            result.append(ref)
    return result


def _lab_opportunity(text: str) -> dict[str, Any]:
    folded = _fold(text)
    signals = [kind for kind, phrases in _LAB_SIGNALS.items() if any(_fold(phrase) in folded for phrase in phrases)]
    return {
        "classification": signals[0] if len(signals) == 1 else "ambiguous" if signals else "no_clear_signal",
        "signals": signals,
        "status": "proposal_only",
    }


def validate_llm_normalization(candidate: dict[str, Any], result: Any) -> dict[str, Any]:
    """Validate optional model output; model text is a proposal, never an approval."""
    allowed_evidence = set(candidate.get("evidenceSourceBlockIds", []))
    if not isinstance(result, dict) or set(result) != {"normalizedStatement", "evidenceSourceBlockIds", "confidence", "ambiguity", "mergeWithOutcomeId", "suggestedOutcomeIds"}:
        raise ContentToolError("LLM normalization must match the strict outcome proposal schema")
    statement = _clean_text(result.get("normalizedStatement"))
    evidence = result.get("evidenceSourceBlockIds")
    confidence = result.get("confidence")
    ambiguity = result.get("ambiguity")
    merge_id = result.get("mergeWithOutcomeId")
    suggested_outcomes = result.get("suggestedOutcomeIds")
    if (
        not statement
        or not isinstance(evidence, list)
        or not evidence
        or any(not isinstance(item, str) for item in evidence)
        or len(evidence) != len(set(evidence))
        or not set(evidence) <= allowed_evidence
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
        or not isinstance(ambiguity, list)
        or any(not isinstance(item, str) or len(item) > 200 for item in ambiguity)
        or (merge_id is not None and merge_id not in candidate.get("possibleDuplicateIds", []))
        or not isinstance(suggested_outcomes, list)
        or any(not isinstance(item, str) for item in suggested_outcomes)
        or len(suggested_outcomes) != len(set(suggested_outcomes))
        or not set(suggested_outcomes) <= set(candidate.get("possibleOutcomeIds", []))
    ):
        raise ContentToolError("LLM normalization failed statement, confidence or source-grounding validation")
    return {"statement": statement, "evidenceSourceBlockIds": sorted(evidence), "confidence": float(confidence), "ambiguity": ambiguity, "mergeWithOutcomeId": merge_id, "suggestedOutcomeIds": sorted(suggested_outcomes), "status": "needs_human_review"}


def _load_sources(workspace: Workspace, source_paths: list[str] | None = None) -> list[tuple[Path, dict[str, Any]]]:
    if source_paths:
        paths = [workspace.inside(path) for path in source_paths]
    else:
        root = workspace.inside("exports", "structured")
        paths = sorted(root.glob("*.json")) if root.is_dir() else []
    if not paths:
        raise ContentToolError("No Structured Lesson JSON files were found")
    result = []
    for path in paths:
        data = read_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("sourceLesson"), dict) or not isinstance(data.get("learningContent"), dict):
            raise ContentToolError(f"Invalid Structured Lesson candidate: {path.name}")
        result.append((path, data))
    return result


def propose_outcomes(
    workspace: Workspace,
    *,
    source_paths: list[str] | None = None,
    taxonomy: dict[str, Any] | None = None,
    llm_normalizer: Callable[[dict[str, Any]], Any] | None = None,
    curriculum_source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract evidence-backed candidates and mappings without writing to BE."""
    grouped: dict[str, dict[str, Any]] = {}
    unit_links: list[dict[str, Any]] = []
    lessons_seen: set[str] = set()
    source_units_seen: set[tuple[str, str]] = set()
    objective_sources_seen: set[str] = set()
    rejected: list[dict[str, str]] = []
    for path, lesson in _load_sources(workspace, source_paths):
        book = lesson.get("book", {})
        source_lesson = lesson["sourceLesson"]
        identity = f"{book.get('key', '')}:{book.get('version', '')}:{source_lesson.get('id', '')}"
        if identity in lessons_seen:
            raise ContentToolError(f"Duplicate source Lesson identity: {identity}")
        lessons_seen.add(identity)
        content = lesson["learningContent"]
        blocks = {str(item.get("id")): item for item in lesson.get("sourceBlocks", []) if isinstance(item, dict) and item.get("id")}
        explicit_objectives = content.get("objectives", lesson.get("objectives", []))
        objective_rows = []
        if isinstance(explicit_objectives, str):
            explicit_objectives = [explicit_objectives]
        if isinstance(explicit_objectives, list):
            for objective in explicit_objectives:
                if isinstance(objective, str):
                    objective_rows.append({"text": objective, "sourceBlockIds": content.get("objectiveSourceBlockIds", [])})
                elif isinstance(objective, dict):
                    objective_rows.append(objective)
        if isinstance(content.get("learningObjective"), str):
            objective_rows.append({"text": content["learningObjective"], "sourceBlockIds": content.get("objectiveSourceBlockIds", [])})
        objective_rows.extend(_extract_source_objectives(lesson, lesson.get("sourceBlocks", [])))
        unique_objectives: dict[tuple[str, str], dict[str, Any]] = {}
        for row in objective_rows:
            refs = row.get("sourceBlockIds", []) if isinstance(row, dict) else []
            row_text = row.get("text", "") if isinstance(row, dict) else ""
            key = ("|".join(str(ref) for ref in refs) if isinstance(refs, list) else "", _fold(str(row_text)))
            unique_objectives.setdefault(key, row)
        objective_rows = list(unique_objectives.values())
        objective_sources_seen.update(f"{identity}:{row.get('id', index)}" for index, row in enumerate(objective_rows) if isinstance(row, dict))
        for row in objective_rows:
            text = _clean_text(row.get("text"))
            refs = row.get("sourceBlockIds", [])
            if not text or not isinstance(refs, list) or not any(ref in blocks for ref in refs):
                reason = "noise_or_invalid_objective" if not text else "missing_source_evidence"
                rejected.append({"lessonId": source_lesson["id"], "sourceId": str(row.get("id", "objective")), "reason": reason})
                continue
            _add_evidence_candidate(grouped, unit_links, text, refs, [], book, source_lesson, identity, "lesson_objective", blocks, taxonomy, lesson=lesson)
        units = content.get("knowledgeUnits", [])
        if not isinstance(units, list):
            continue
        for unit in units:
            if not isinstance(unit, dict):
                continue
            unit_id = str(unit.get("id", "")).strip()
            if unit_id:
                source_units_seen.add((identity, unit_id))
            claims = unit.get("claims", [])
            claims = [item for item in claims if isinstance(item, dict)] if isinstance(claims, list) else []
            claim_evidence = [
                {"id": str(item.get("id", "")), "text": text, "sourceBlockIds": sorted(str(ref) for ref in item.get("sourceBlockIds", []) if isinstance(ref, str))}
                for item in claims if (text := _clean_text(item.get("text")))
            ]
            title = _clean_text(unit.get("title"), allow_concept_label=bool(claim_evidence))
            source_ids = sorted({str(source_id) for source_id in unit.get("sourceBlockIds", []) if isinstance(source_id, str)} | {str(source_id) for claim in claims for source_id in claim.get("sourceBlockIds", []) if isinstance(source_id, str)})
            if not title:
                rejected.append({"lessonId": source_lesson["id"], "sourceId": unit_id or "knowledge_unit", "reason": "noise_or_invalid_unit_title"})
                continue
            if not unit_id or not any(item in blocks for item in source_ids):
                rejected.append({"lessonId": source_lesson["id"], "sourceId": unit_id or "knowledge_unit", "reason": "missing_unit_identity_or_source_evidence"})
                continue
            _add_evidence_candidate(grouped, unit_links, title, source_ids, claim_evidence, book, source_lesson, identity, "knowledge_unit_title", blocks, taxonomy, unit_id, lesson)

    candidates = sorted(grouped.values(), key=lambda item: item["id"])
    outcomes = [item for item in candidates if any(evidence["origin"] == "lesson_objective" for evidence in item["evidence"])]
    concepts = [item for item in candidates if item not in outcomes]
    _mark_ambiguities(outcomes)
    _mark_ambiguities(concepts)
    for candidate in outcomes:
        candidate["candidateType"] = "textbook_derived_internal_outcome"
        _quality_gate(candidate, measurable=_is_measurable_objective_statement(candidate["statement"]))
    for candidate in concepts:
        candidate["candidateType"] = "knowledge_unit_heading_not_an_outcome"
        _quality_gate(candidate, measurable=False)

    outcome_map = {item["id"]: item for item in outcomes}
    concept_map = {item["id"]: item for item in concepts}
    lesson_map: dict[tuple[str, str], dict[str, Any]] = {}
    objective_by_lesson: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for outcome in outcomes:
        for evidence in outcome["evidence"]:
            objective_by_lesson[evidence["lessonIdentity"]].append(outcome)
            key = (evidence["lessonIdentity"], outcome["id"])
            lesson_map.setdefault(key, {
                "mappingId": _mapping_id("lesson", *key),
                "lessonIdentity": evidence["lessonIdentity"],
                "sourceLessonId": evidence["sourceLessonId"],
                "outcomeId": outcome["id"],
                "mappingConfidence": 1.0,
                "confidenceMethod": "explicit_objective_marker_and_source_lesson_identity; not calibrated",
                "sourceBlockIds": evidence["sourceBlockIds"],
                "status": "needs_human_review",
            })

    knowledge_unit_mappings: list[dict[str, Any]] = []
    for link in (item for item in unit_links if item["knowledgeUnitId"] is not None):
        concept = concept_map.get(link["outcomeId"])
        evidence = next((item for item in (concept or {}).get("evidence", []) if item["lessonIdentity"] == link["lessonIdentity"] and item["knowledgeUnitId"] == link["knowledgeUnitId"]), None)
        if not evidence:
            continue
        source_blocks = set(evidence["sourceBlockIds"])
        claims = [item["text"] for item in concept.get("claimEvidence", []) if source_blocks.intersection(item["sourceBlockIds"])]
        source_text = " ".join([evidence["sourcePhrase"], *claims])
        suggestions = []
        for outcome in objective_by_lesson.get(link["lessonIdentity"], []):
            objective_text = outcome["statement"]
            score, terms = _mapping_overlap(source_text, objective_text)
            if terms and score >= 0.25:
                objective_evidence = next(item for item in outcome["evidence"] if item["lessonIdentity"] == link["lessonIdentity"])
                suggestions.append({"outcomeId": outcome["id"], "mappingConfidence": round(score, 3), "confidenceMethod": "shared_content_terms_over_smaller_term_set; not calibrated", "sharedTerms": terms, "sourceBlockIds": sorted(source_blocks | set(objective_evidence["sourceBlockIds"])), "ambiguity": []})
        suggestions.sort(key=lambda item: (-item["mappingConfidence"], item["outcomeId"]))
        close = len(suggestions) > 1 and suggestions[0]["mappingConfidence"] - suggestions[1]["mappingConfidence"] <= 0.10
        if close:
            for suggestion in suggestions:
                if suggestions[0]["mappingConfidence"] - suggestion["mappingConfidence"] <= 0.10:
                    suggestion["ambiguity"].append("multiple_objectives_have_similar_lexical_match")
        if not suggestions:
            suggestions = [{"outcomeId": None, "mappingConfidence": 0.0, "confidenceMethod": "no_lexical_match", "sharedTerms": [], "sourceBlockIds": evidence["sourceBlockIds"], "ambiguity": ["human_mapping_required"]}]
        for suggestion in suggestions:
            mapping_id = _mapping_id("unit", link["lessonIdentity"], link["knowledgeUnitId"], suggestion["outcomeId"] or "unmapped")
            knowledge_unit_mappings.append({
                "mappingId": mapping_id,
                "lessonIdentity": link["lessonIdentity"],
                "sourceLessonId": link["sourceLessonId"],
                "knowledgeUnitId": link["knowledgeUnitId"],
                "sourceConceptId": concept["id"],
                **suggestion,
                "status": "needs_human_review" if suggestion["outcomeId"] else "unmapped",
            })

    if llm_normalizer:
        for candidate in [*outcomes, *concepts]:
            evidence_lessons = {item["lessonIdentity"] for item in candidate["evidence"]}
            candidate["possibleDuplicateIds"] = [item["id"] for item in candidates if item["id"] != candidate["id"] and f"possible_duplicate:{item['id']}" in candidate["ambiguity"]]
            candidate["possibleOutcomeIds"] = sorted({item["id"] for lesson_id in evidence_lessons for item in objective_by_lesson.get(lesson_id, []) if item["id"] != candidate["id"]})
            candidate["llmProposal"] = validate_llm_normalization(candidate, llm_normalizer(candidate))
            candidate["normalizedStatementProposal"] = candidate["llmProposal"]["statement"]
            candidate["normalizationStatus"] = "llm_proposal_needs_human_review"
            del candidate["possibleDuplicateIds"]
            del candidate["possibleOutcomeIds"]

    review_queue = _build_review_queue(outcomes, concepts, knowledge_unit_mappings)
    accepted_unit_refs = {
        (item["lessonIdentity"], item["knowledgeUnitId"])
        for item in unit_links
        if item["knowledgeUnitId"] is not None
    }
    mapped_unit_refs = {
        (item["lessonIdentity"], item["knowledgeUnitId"])
        for item in knowledge_unit_mappings
        if item["outcomeId"] is not None
    }
    source_books = sorted({(item["bookKey"], item["bookVersion"], item["bookSha256"]) for candidate in candidates for item in candidate["evidence"]})
    return {
        "schemaVersion": 1,
        "kind": "curriculum-outcome-normalization-proposal",
        "status": "needs_human_review",
        "outcomes": outcomes,
        "sourceConcepts": concepts,
        "lessonMappings": sorted(lesson_map.values(), key=lambda item: (item["lessonIdentity"], item["outcomeId"])),
        "knowledgeUnitMappings": sorted(knowledge_unit_mappings, key=lambda item: (item["lessonIdentity"], item["knowledgeUnitId"], item["outcomeId"] or "")),
        "curriculumSource": curriculum_source_metadata or {"status": "not_provided", "officialSha256": None, "officialCodesClaimed": False},
        "sourceBooks": [{"bookKey": key, "version": version, "sha256": digest, "digestStatus": "pinned_from_structured_lesson" if re.fullmatch(r"[a-fA-F0-9]{64}", str(digest or "")) else "missing_source_digest"} for key, version, digest in source_books],
        "coverage": {
            "sourceLessons": len(lessons_seen),
            "explicitObjectiveCandidates": len(objective_sources_seen),
            "measurableOutcomeCandidates": sum(item["qualityGate"]["measurability"] == "pass" for item in outcomes),
            "qualityFlaggedOutcomeCandidates": sum(item["qualityGate"]["measurability"] != "pass" or item["qualityGate"]["sourceGrounding"] != "pass" or bool(item["ambiguity"]) for item in outcomes),
            "sourceTextReviewRequiredOutcomeCandidates": sum(item["qualityGate"]["sourceTextFidelity"] != "verified" for item in outcomes),
            "reviewReadyOutcomeCandidates": sum(item["qualityGate"]["internalOutcomeEligible"] and not item["ambiguity"] for item in outcomes),
            "sourceGroundedOutcomeCandidates": sum(item["qualityGate"]["sourceGrounding"] == "pass" for item in outcomes),
            "sourceConceptCandidates": len(concepts),
            "sourceConceptsNotMeasurableOutcomes": sum(item["qualityGate"]["measurability"] == "not_an_objective" for item in concepts),
            "knowledgeUnits": len(source_units_seen),
            "acceptedKnowledgeUnits": len(accepted_unit_refs),
            "knowledgeUnitsWithOutcomeSuggestion": len(mapped_unit_refs),
            "unmappedKnowledgeUnits": len(accepted_unit_refs - mapped_unit_refs),
            "lessonMappings": len(lesson_map),
            "knowledgeUnitOutcomeMappings": sum(item["outcomeId"] is not None for item in knowledge_unit_mappings),
            "ambiguousKnowledgeUnitMappings": sum(bool(item["ambiguity"]) for item in knowledge_unit_mappings),
            "ambiguousOutcomeCandidates": sum(bool(item["ambiguity"]) for item in outcomes),
            "ambiguousSourceConcepts": sum(bool(item["ambiguity"]) for item in concepts),
            "rejectedKnowledgeUnits": sum(item["reason"] in {"noise_or_invalid_unit_title", "missing_unit_identity_or_source_evidence"} for item in rejected),
            "officialVerifiedOutcomes": 0,
            "rejected": len(rejected),
        },
        "humanReview": {
            "outcomeIds": [item["id"] for item in outcomes],
            "ambiguousOutcomeIds": [item["id"] for item in outcomes if item["ambiguity"]],
            "ambiguousSourceConceptIds": [item["id"] for item in concepts if item["ambiguity"]],
            "lessonMappingIds": [item["mappingId"] for item in sorted(lesson_map.values(), key=lambda item: (item["lessonIdentity"], item["outcomeId"]))],
            "knowledgeUnitMappingIds": [item["mappingId"] for item in knowledge_unit_mappings],
            "rejectedKnowledgeUnitRefs": [f"{item['lessonId']}:{item['sourceId']}" for item in rejected if item["reason"] in {"noise_or_invalid_unit_title", "missing_unit_identity_or_source_evidence"}],
            "requiredDecisions": ["verify OCR text and source locators for every objective candidate", "review candidate granularity and duplicate flags", "review or assign Knowledge Unit to Outcome mappings", "keep textbook-derived internal outcomes distinct from official Curriculum Registry records"],
        },
        "reviewQueue": review_queue,
        "rejected": rejected,
        "registrySync": {"ready": False, "blocker": "Textbook-derived internal outcomes require explicit human review and the development-target/provenance preflight before internal Registry sync. Official curriculum crosswalk is a separate optional verification stage."},
    }


def _add_evidence_candidate(
    grouped: dict[str, dict[str, Any]],
    mappings: list[dict[str, Any]],
    text: str,
    source_ids: list[str],
    claim_texts: list[dict[str, Any]],
    book: dict[str, Any],
    source_lesson: dict[str, Any],
    lesson_identity: str,
    origin: str,
    blocks: dict[str, dict[str, Any]],
    taxonomy: dict[str, Any] | None,
    unit_id: str | None = None,
    lesson: dict[str, Any] | None = None,
) -> None:
    normalized = " ".join(text.split())
    statement_key = _fold(normalized)
    key = statement_key
    cid = _candidate_id(normalized)
    evidence_ids = sorted({str(item) for item in source_ids if isinstance(item, str) and item in blocks})
    evidence = {"lessonIdentity": lesson_identity, "sourceLessonId": source_lesson["id"], "sourceLessonTitle": source_lesson.get("title"), "bookKey": book.get("key"), "bookVersion": book.get("version"), "bookSha256": book.get("sha256"), "chapterId": (lesson or {}).get("chapter", {}).get("id"), "chapterTitle": (lesson or {}).get("chapter", {}).get("title"), "knowledgeUnitId": unit_id, "sourceTopicTitle": normalized if unit_id else None, "sourcePhrase": normalized, "pdfPageRange": (lesson or {}).get("pdfPageRange"), "printedPageRange": (lesson or {}).get("printedPageRange"), "sourceBlockIds": evidence_ids, "pages": _pages({"sourceBlockIds": evidence_ids}, blocks), "sourceTextReviewStatus": (lesson or {}).get("contentReview", {}).get("status", "unknown"), "origin": origin}
    candidate = grouped.setdefault(cid, {
        "id": cid,
        "internalIdentity": cid,
        "statement": normalized,
        "normalizedStatementProposal": normalized,
        "normalizationMethod": "unicode_normalization_whitespace_and_section_prefix_cleanup",
        "normalizationStatus": "deterministic_source_phrase_needs_human_review",
        "normalizedKey": key,
        "statementKey": statement_key,
        "officialCode": None,
        "confidence": 0.95 if origin == "lesson_objective" else 0.75 if claim_texts and len(_fold(normalized).split()) > 1 else 0.5 if claim_texts else 0.6,
        "confidenceBasis": "explicit_objective_source" if origin == "lesson_objective" else "unit_title_with_claims" if claim_texts and len(_fold(normalized).split()) > 1 else "short_concept_with_claims" if claim_texts else "source_heading_only",
        "ambiguity": [],
        "evidenceSourceBlockIds": [],
        "evidence": [],
        "claimEvidence": [],
        "existingOutcomeMatches": [],
        "labOpportunity": _lab_opportunity(normalized),
        "status": "needs_human_review",
    })
    score = 0.95 if origin == "lesson_objective" else 0.75 if claim_texts and len(_fold(normalized).split()) > 1 else 0.5 if claim_texts else 0.6
    if score > candidate["confidence"]:
        candidate["confidence"] = score
        candidate["confidenceBasis"] = "explicit_objective_source" if origin == "lesson_objective" else "unit_title_with_claims" if claim_texts and len(_fold(normalized).split()) > 1 else "short_concept_with_claims" if claim_texts else "source_heading_only"
    if evidence not in candidate["evidence"]:
        candidate["evidence"].append(evidence)
    candidate["evidenceSourceBlockIds"] = sorted(set(candidate["evidenceSourceBlockIds"]) | set(evidence_ids))
    claims_by_id = {item["id"] + "|" + ",".join(item["sourceBlockIds"]): item for item in candidate["claimEvidence"]}
    for item in claim_texts:
        key = item["id"] + "|" + ",".join(item["sourceBlockIds"])
        claims_by_id[key or hashlib.sha256(item["text"].encode()).hexdigest()[:16]] = item
    candidate["claimEvidence"] = sorted(claims_by_id.values(), key=lambda item: (item["id"], item["text"], item["sourceBlockIds"]))
    for outcome in (taxonomy or {}).get("outcomes", []):
        existing_key = _fold(str(outcome.get("statement", "")))
        if outcome.get("status") == "active" and outcome.get("synthetic") is False and existing_key == statement_key:
            candidate["existingOutcomeMatches"].append({"code": outcome.get("code"), "match": "exact_normalized", "confidence": 1.0})
    mappings.append({"lessonIdentity": lesson_identity, "sourceLessonId": source_lesson["id"], "knowledgeUnitId": unit_id, "outcomeId": cid, "mappingConfidence": score, "confidenceMethod": "source-origin heuristic; not a calibrated probability", "ambiguity": list(candidate["ambiguity"]), "status": "needs_human_review"})


def _mark_ambiguities(candidates: list[dict[str, Any]]) -> None:
    for index, left in enumerate(candidates):
        a = set(left["normalizedKey"].split())
        for right in candidates[index + 1:]:
            b = set(right["normalizedKey"].split())
            overlap = len(a & b) / max(1, len(a | b))
            ratio = SequenceMatcher(None, left["normalizedKey"], right["normalizedKey"]).ratio()
            if left["normalizedKey"] != right["normalizedKey"] and max(overlap, ratio) >= 0.82:
                left["ambiguity"].append(f"possible_duplicate:{right['id']}")
                right["ambiguity"].append(f"possible_duplicate:{left['id']}")
    for candidate in candidates:
        candidate["ambiguity"] = sorted(set(candidate["ambiguity"]))
        candidate["evidence"] = sorted(candidate["evidence"], key=lambda item: (item["bookKey"] or "", item["lessonIdentity"], item["knowledgeUnitId"] or ""))
        candidate["existingOutcomeMatches"] = sorted({match["code"]: match for match in candidate["existingOutcomeMatches"]}.values(), key=lambda item: item["code"] or "")


def save_outcome_proposal(workspace: Workspace, proposal: dict[str, Any], name: str = "proposal") -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "proposal"
    path = workspace.inside(".local", "outcomes", f"{safe_name}.json")
    proposal["proposalVersion"] = _proposal_digest(proposal)
    versions = workspace.inside(".local", "outcomes", "versions", safe_name)
    versions.mkdir(parents=True, exist_ok=True)
    version_path = versions / f"{proposal['proposalVersion']}.json"
    if not version_path.exists():
        write_json(version_path, _proposal_base(proposal))
    if path.exists():
        current = read_json(path)
        if current.get("proposalVersion") == proposal["proposalVersion"] and current.get("reviewHistory"):
            return path
    write_json(path, proposal)
    return path


def _proposal_base(proposal: dict[str, Any]) -> dict[str, Any]:
    base = json.loads(json.dumps(proposal, ensure_ascii=False))
    for key in ("proposalVersion", "reviewHistory", "registrySync"):
        base.pop(key, None)
    base["status"] = "needs_human_review"
    for candidate in [*base.get("outcomes", []), *base.get("sourceConcepts", [])]:
        candidate.pop("reviewDecision", None)
        candidate["status"] = "needs_human_review"
        if "qualityGate" in candidate:
            candidate["qualityGate"]["internalReviewApproved"] = False
    for mapping in [*base.get("lessonMappings", []), *base.get("knowledgeUnitMappings", [])]:
        mapping.pop("reviewDecision", None)
        mapping["status"] = "needs_human_review" if mapping.get("outcomeId") else "unmapped"
    return base


def _proposal_digest(proposal: dict[str, Any]) -> str:
    canonical = json.dumps(_proposal_base(proposal), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def review_outcome_proposal(
    workspace: Workspace,
    name: str,
    *,
    outcome_decisions: dict[str, str],
    mapping_decisions: dict[str, str],
    reviewer_name: str,
    reviewer_email: str,
    reason: str,
    source_text_verified: bool = False,
) -> dict[str, Any]:
    """Record explicit, source-bound human decisions; model/heuristic scores never approve."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "proposal"
    path = workspace.inside(".local", "outcomes", f"{safe_name}.json")
    proposal = read_json(path)
    version = proposal.get("proposalVersion")
    immutable_version = workspace.inside(".local", "outcomes", "versions", safe_name, f"{version}.json") if isinstance(version, str) else None
    if not immutable_version or not immutable_version.exists() or _proposal_digest(read_json(immutable_version)) != version:
        raise ContentToolError("The outcome proposal version is missing or does not match its immutable snapshot")
    if not reviewer_name.strip() or len(reviewer_name.strip()) > 200 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reviewer_email.strip()) or len(reviewer_email.strip()) > 254 or not 5 <= len(reason.strip()) <= 500:
        raise ContentToolError("A named reviewer, valid email and review reason are required")
    if source_text_verified is not True:
        raise ContentToolError("sourceTextVerified must be an explicit human confirmation")
    if not isinstance(outcome_decisions, dict) or not isinstance(mapping_decisions, dict):
        raise ContentToolError("Outcome and mapping review decisions must be JSON objects")
    outcomes = {item["id"]: item for item in proposal.get("outcomes", [])}
    mappings = [*proposal.get("lessonMappings", []), *proposal.get("knowledgeUnitMappings", [])]
    mappings_by_id = {item["mappingId"]: item for item in mappings}
    if not outcome_decisions and not mapping_decisions:
        raise ContentToolError("Select at least one outcome or mapping for an explicit human decision")
    if set(outcome_decisions) - set(outcomes) or set(mapping_decisions) - set(mappings_by_id):
        raise ContentToolError("Review references an unknown outcome or mapping ID")

    review_id = "review-" + uuid.uuid4().hex
    reviewed_at = datetime.now(timezone.utc).isoformat()
    event_outcomes: dict[str, dict[str, Any]] = {}
    event_mappings: dict[str, dict[str, Any]] = {}

    def evidence_verified(item: dict[str, Any], decision: dict[str, Any], label: str) -> bool:
        expected = set(item.get("evidenceSourceBlockIds", item.get("sourceBlockIds", [])))
        selected = decision.get("verifiedSourceBlockIds", [])
        if not source_text_verified or not isinstance(selected, list) or any(not isinstance(ref, str) for ref in selected) or set(selected) != expected:
            raise ContentToolError(f"{label} requires human verification of every cited source block")
        return True

    prepared_outcomes: dict[str, dict[str, Any]] = {}
    for candidate_id, raw_decision in outcome_decisions.items():
        if not isinstance(raw_decision, dict):
            raise ContentToolError(f"Outcome {candidate_id} needs an explicit decision object")
        decision = dict(raw_decision)
        candidate = outcomes[candidate_id]
        action = decision.get("decision")
        if action not in {"approve", "revise", "reject", "merge", "reuse"}:
            raise ContentToolError(f"Unsupported outcome review decision for {candidate_id}")
        evidence_verified(candidate, decision, f"Outcome {candidate_id}")
        reason_text = str(decision.get("reason", reason)).strip()
        if not 5 <= len(reason_text) <= 500:
            raise ContentToolError(f"Outcome {candidate_id} requires a review reason")
        if action == "revise":
            revised = _clean_text(decision.get("statement"))
            if not revised:
                raise ContentToolError(f"Outcome {candidate_id} revision requires a valid statement")
            candidate["statement"] = revised
            candidate["normalizedStatementProposal"] = revised
            candidate["qualityGate"]["measurability"] = "pass" if _is_measurable_objective_statement(revised) else "needs_review"
            candidate["status"] = "needs_revision"
        elif action == "approve":
            ambiguity_reason = str(decision.get("ambiguityReason", "")).strip()
            if candidate["ambiguity"] and (decision.get("ambiguityResolution") != "distinct" or not 8 <= len(ambiguity_reason) <= 500):
                raise ContentToolError(f"Outcome {candidate_id} must resolve duplicate flags by merge/reuse or record why it is distinct")
            quality_override = str(decision.get("qualityOverrideReason", "")).strip()
            if candidate["qualityGate"]["measurability"] != "pass" and not 8 <= len(quality_override) <= 500:
                raise ContentToolError(f"Outcome {candidate_id} needs revision or a reasoned human quality override")
            candidate["status"] = "approved_internal"
            candidate["qualityGate"]["internalReviewApproved"] = True
            attributes = decision.get("registryAttributes", {})
            if not isinstance(attributes, dict):
                raise ContentToolError(f"Outcome {candidate_id}.registryAttributes must be an object")
            grade = attributes.get("grade")
            domain = attributes.get("domain")
            chapter = attributes.get("chapter")
            if grade is not None and (isinstance(grade, bool) or not isinstance(grade, int) or not 1 <= grade <= 12):
                raise ContentToolError(f"Outcome {candidate_id} grade must be an integer from 1 to 12")
            if domain is not None and (not isinstance(domain, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,39}", domain)):
                raise ContentToolError(f"Outcome {candidate_id} domain must be a stable uppercase identifier")
            if chapter is not None and (not isinstance(chapter, str) or not chapter.strip() or len(chapter.strip()) > 200):
                raise ContentToolError(f"Outcome {candidate_id} chapter must be a non-empty string of at most 200 characters")
            if any(value is not None for value in (grade, domain, chapter)):
                candidate["registryAttributes"] = {key: value for key, value in (("grade", grade), ("domain", domain), ("chapter", chapter)) if value is not None}
        elif action == "reject":
            candidate["status"] = "rejected_by_reviewer"
        elif action == "merge":
            target_id = decision.get("targetOutcomeId")
            if not isinstance(target_id, str) or target_id not in outcomes or target_id == candidate_id:
                raise ContentToolError(f"Outcome {candidate_id} merge requires another known outcome candidate")
            candidate["mergedIntoOutcomeId"] = target_id
            candidate["status"] = "merged_into"
        elif action == "reuse":
            target_id, target_code = decision.get("targetOutcomeId"), decision.get("targetOutcomeCode")
            if bool(target_id) == bool(target_code):
                raise ContentToolError(f"Outcome {candidate_id} reuse requires exactly one selected outcome ID or BE outcome code")
            if target_id and (not isinstance(target_id, str) or target_id not in outcomes or target_id == candidate_id):
                raise ContentToolError(f"Outcome {candidate_id} reuse target must be another known outcome candidate")
            if target_code and (not isinstance(target_code, str) or not _BE_OUTCOME_CODE.fullmatch(target_code)):
                raise ContentToolError(f"Outcome {candidate_id} reuse code must be a stable BE outcome code")
            candidate["reusedOutcomeId"] = target_id
            candidate["reusedOutcomeCode"] = target_code
            candidate["status"] = "reused_outcome"
            attributes = decision.get("registryAttributes", {})
            if not isinstance(attributes, dict):
                raise ContentToolError(f"Outcome {candidate_id}.registryAttributes must be an object")
            grade, domain, chapter = attributes.get("grade"), attributes.get("domain"), attributes.get("chapter")
            if grade is not None and (isinstance(grade, bool) or not isinstance(grade, int) or not 1 <= grade <= 12):
                raise ContentToolError(f"Outcome {candidate_id} grade must be an integer from 1 to 12")
            if domain is not None and (not isinstance(domain, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,39}", domain)):
                raise ContentToolError(f"Outcome {candidate_id} domain must be a stable uppercase identifier")
            if chapter is not None and (not isinstance(chapter, str) or not chapter.strip() or len(chapter.strip()) > 200):
                raise ContentToolError(f"Outcome {candidate_id} chapter must be a non-empty string of at most 200 characters")
            if any(value is not None for value in (grade, domain, chapter)):
                candidate["registryAttributes"] = {key: value for key, value in (("grade", grade), ("domain", domain), ("chapter", chapter)) if value is not None}
        review_record = {
            "decision": action,
            "reviewType": "textbook_derived_internal_outcome",
            "reviewId": review_id,
            "proposalVersion": proposal.get("proposalVersion"),
            "reviewerName": reviewer_name.strip(),
            "reviewerEmail": reviewer_email.strip(),
            "reason": reason_text,
            "sourceTextVerified": True,
            "verifiedSourceBlockIds": sorted(decision["verifiedSourceBlockIds"]),
            "reviewedAt": reviewed_at,
        }
        if action == "approve":
            review_record["ambiguityResolution"] = decision.get("ambiguityResolution", "not_ambiguous")
            if quality_override:
                review_record["qualityOverrideReason"] = quality_override
        candidate["reviewDecision"] = review_record
        candidate["qualityGate"]["sourceTextFidelity"] = "verified"
        candidate["qualityGate"]["internalReviewApproved"] = action == "approve"
        prepared_outcomes[candidate_id] = candidate
        event_outcomes[candidate_id] = {**review_record, "selection": decision}

    # Resolve aliases only to candidates explicitly approved in this or an earlier review.
    for candidate_id, candidate in prepared_outcomes.items():
        target_id = candidate.get("mergedIntoOutcomeId") or candidate.get("reusedOutcomeId")
        if target_id and not _is_approved_target(outcomes, target_id):
            raise ContentToolError(f"Outcome {candidate_id} may only merge/reuse an approved internal outcome")

    for mapping_id, raw_decision in mapping_decisions.items():
        if not isinstance(raw_decision, dict):
            raise ContentToolError(f"Mapping {mapping_id} needs an explicit decision object")
        decision = dict(raw_decision)
        mapping = mappings_by_id[mapping_id]
        action = decision.get("decision")
        if action not in {"approve", "revise", "reject", "ambiguous", "unmapped"}:
            raise ContentToolError(f"Unsupported mapping review decision for {mapping_id}")
        if not source_text_verified:
            raise ContentToolError(f"Mapping {mapping_id} requires human source verification")
        expected = set(mapping.get("sourceBlockIds", []))
        selected = decision.get("verifiedSourceBlockIds", [])
        if not isinstance(selected, list) or any(not isinstance(ref, str) for ref in selected) or set(selected) != expected:
            raise ContentToolError(f"Mapping {mapping_id} requires human verification of every cited source block")
        reason_text = str(decision.get("reason", reason)).strip()
        if not 5 <= len(reason_text) <= 500:
            raise ContentToolError(f"Mapping {mapping_id} requires a review reason")
        if action in {"approve", "revise"}:
            target_id = decision.get("targetOutcomeId", mapping.get("outcomeId"))
            if not isinstance(target_id, str) or target_id not in outcomes:
                raise ContentToolError(f"Mapping {mapping_id} must select a known outcome candidate")
            target = outcomes[target_id]
            if not _is_approved_target(outcomes, target_id):
                raise ContentToolError(f"Mapping {mapping_id} cannot target an outcome without explicit approval")
            mapping["outcomeId"] = target_id
            mapping["status"] = "accepted_internal_mapping" if action == "approve" else "needs_revision"
            mapping["suggestedOutcomeId"] = target_id if action == "revise" else None
        elif action == "unmapped":
            mapping["outcomeId"] = None
            mapping["status"] = "accepted_unmapped"
        elif action == "reject":
            mapping["status"] = "rejected_by_reviewer"
        else:
            mapping["status"] = "ambiguous"
        review_record = {
            "decision": action,
            "reviewType": "textbook_derived_internal_mapping",
            "reviewId": review_id,
            "proposalVersion": proposal.get("proposalVersion"),
            "reviewerName": reviewer_name.strip(),
            "reviewerEmail": reviewer_email.strip(),
            "reason": reason_text,
            "sourceTextVerified": True,
            "verifiedSourceBlockIds": sorted(selected),
            "reviewedAt": reviewed_at,
        }
        mapping["reviewDecision"] = review_record
        event_mappings[mapping_id] = {**review_record, "selection": decision}

    event = {
        "reviewId": review_id,
        "proposalVersion": proposal.get("proposalVersion"),
        "reviewerName": reviewer_name.strip(),
        "reviewerEmail": reviewer_email.strip(),
        "reason": reason.strip(),
        "sourceTextVerified": source_text_verified,
        "reviewedAt": reviewed_at,
        "outcomeDecisions": event_outcomes,
        "mappingDecisions": event_mappings,
    }
    proposal.setdefault("reviewHistory", []).append(event)
    proposal["status"] = "review_in_progress"
    proposal["registrySync"] = {"ready": False, "blocker": "Generate an outcomes export and pass the current BE provenance/target preflight before sync."}
    event_path = workspace.inside(".local", "outcomes", "review-events.jsonl")
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    write_json(path, proposal)
    return {"path": str(path), "proposal": proposal, "reviewEvent": event}


def _is_approved_target(outcomes: dict[str, dict[str, Any]], candidate_id: str, visited: set[str] | None = None) -> bool:
    visited = set() if visited is None else visited
    if candidate_id in visited or candidate_id not in outcomes:
        return False
    visited.add(candidate_id)
    candidate = outcomes[candidate_id]
    if candidate.get("status") == "approved_internal":
        return True
    if candidate.get("status") == "merged_into":
        return _is_approved_target(outcomes, candidate.get("mergedIntoOutcomeId", ""), visited)
    if candidate.get("status") == "reused_outcome":
        return bool(candidate.get("reusedOutcomeCode")) or _is_approved_target(outcomes, candidate.get("reusedOutcomeId", ""), visited)
    return False


def _outcome_registry_code(candidate_id: str) -> str:
    return "NXO-" + hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:20].upper()


def _review_reference(candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    action = decision.get("decision")
    return {
        "proposalVersion": decision.get("proposalVersion"),
        "reviewId": decision.get("reviewId"),
        "reviewerName": decision.get("reviewerName"),
        "reviewerEmail": decision.get("reviewerEmail"),
        "reason": decision.get("reason"),
        "reviewedAt": decision.get("reviewedAt"),
        "decision": "reused_internal" if action == "reuse" else "approved_internal",
    }


def _source_evidence(candidate: dict[str, Any], review: dict[str, Any]) -> list[dict[str, Any]]:
    review_reference = _review_reference(candidate, review)
    evidence = []
    for source in candidate.get("evidence", []):
        locators = []
        pages_by_block = {item.get("sourceBlockId"): item for item in source.get("pages", [])}
        for block_id in source.get("sourceBlockIds", []):
            page = pages_by_block.get(block_id, {})
            locators.append({
                "sourceBlockId": block_id,
                **({"physicalPageIndex": page["physicalPageIndex"]} if page.get("physicalPageIndex") is not None else {}),
                **({"printedPageLabel": page["printedPageLabel"]} if page.get("printedPageLabel") is not None else {}),
            })
        identity = f"{source.get('bookKey', '')}@{source.get('bookVersion', '')}:{source.get('sourceLessonId', '')}"
        payload = {
            "originType": "textbook_derived_internal",
            "sourceDigest": source.get("bookSha256"),
            "sourceIdentity": identity,
            "sourceLocators": locators,
            "reviewReference": review_reference,
        }
        payload["evidenceId"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        evidence.append(payload)
    return evidence


def build_outcome_sync_bundle(proposal: dict[str, Any]) -> dict[str, Any]:
    """Materialize approved-only BE records and review evidence without writing to BE."""
    outcome_by_id = {item["id"]: item for item in proposal.get("outcomes", [])}
    concept_by_id = {item["id"]: item for item in proposal.get("sourceConcepts", [])}

    def resolve_code(candidate_id: str, visited: set[str] | None = None) -> str | None:
        visited = set() if visited is None else visited
        if candidate_id in visited or candidate_id not in outcome_by_id:
            return None
        visited.add(candidate_id)
        candidate = outcome_by_id[candidate_id]
        if candidate.get("status") == "approved_internal":
            decision = candidate.get("reviewDecision", {})
            return decision.get("targetOutcomeCode") or _outcome_registry_code(candidate_id)
        if candidate.get("status") == "merged_into":
            return resolve_code(candidate.get("mergedIntoOutcomeId", ""), visited)
        if candidate.get("status") == "reused_outcome":
            if candidate.get("reusedOutcomeCode"):
                return candidate["reusedOutcomeCode"]
            return resolve_code(candidate.get("reusedOutcomeId", ""), visited)
        return None

    approved, rejected, merged, reuse_requests, pending = [], [], [], [], []
    blockers: list[str] = []
    for candidate in proposal.get("outcomes", []):
        status = candidate.get("status")
        review = candidate.get("reviewDecision") or {}
        if status == "approved_internal":
            attrs = candidate.get("registryAttributes", {})
            item = {
                "code": resolve_code(candidate["id"]),
                "candidateId": candidate["id"],
                "statement": candidate["statement"],
                "grade": attrs.get("grade"),
                "domain": attrs.get("domain"),
                "chapter": attrs.get("chapter"),
                "officialCode": None,
                "originType": "textbook_derived_internal",
                "sourceEvidence": _source_evidence(candidate, review),
                "reviewReference": _review_reference(candidate, review),
            }
            candidate_blockers = []
            if not all((item["grade"], item["domain"], item["chapter"])):
                candidate_blockers.append("grade, domain and chapter are required for BE Registry creation")
            if not item["sourceEvidence"] or any(not re.fullmatch(r"[a-fA-F0-9]{64}", str(source.get("sourceDigest", ""))) or not source.get("sourceLocators") for source in item["sourceEvidence"]):
                candidate_blockers.append("every source evidence row needs a digest and source block/page locator")
            if not item["reviewReference"].get("reviewId") or not item["reviewReference"].get("reviewerName"):
                candidate_blockers.append("named outcome approval reference is missing")
            item["syncBlockers"] = candidate_blockers
            approved.append(item)
        elif status == "rejected_by_reviewer":
            rejected.append({"candidateId": candidate["id"], "statement": candidate["statement"], "reviewDecision": review, "sourceEvidence": candidate.get("evidence", [])})
        elif status == "merged_into":
            merged.append({"candidateId": candidate["id"], "statement": candidate["statement"], "mergedIntoOutcomeId": candidate.get("mergedIntoOutcomeId"), "resolvedCode": resolve_code(candidate["mergedIntoOutcomeId"] or ""), "reviewDecision": review, "sourceEvidence": candidate.get("evidence", [])})
        elif status == "reused_outcome":
            attrs = candidate.get("registryAttributes", {})
            reuse_requests.append({"candidateId": candidate["id"], "statement": candidate["statement"], "grade": attrs.get("grade"), "domain": attrs.get("domain"), "chapter": attrs.get("chapter"), "targetOutcomeId": candidate.get("reusedOutcomeId"), "targetOutcomeCode": resolve_code(candidate["reusedOutcomeId"] or "") or candidate.get("reusedOutcomeCode"), "sourceEvidence": _source_evidence(candidate, review), "reviewReference": _review_reference(candidate, review)})
        else:
            pending.append({"candidateId": candidate["id"], "statement": candidate["statement"], "status": status or "needs_human_review", "ambiguity": candidate.get("ambiguity", [])})

    lesson_ids = {item["mappingId"] for item in proposal.get("lessonMappings", [])}
    reviewed_lesson, reviewed_units, pending_mappings = [], [], []
    mapped_unit_refs: set[tuple[str, str]] = set()
    unmapped_unit_refs: set[tuple[str, str]] = set()

    def mapping_source_evidence(mapping: dict[str, Any]) -> list[dict[str, Any]]:
        mapping_refs = set(mapping.get("sourceBlockIds", []))
        candidates = [concept_by_id.get(mapping.get("sourceConceptId")), outcome_by_id.get(mapping.get("outcomeId"))]
        sources = []
        for candidate in candidates:
            if not candidate:
                continue
            for evidence in candidate.get("evidence", []):
                if evidence.get("lessonIdentity") != mapping.get("lessonIdentity"):
                    continue
                if mapping.get("knowledgeUnitId") and evidence.get("knowledgeUnitId") != mapping.get("knowledgeUnitId"):
                    continue
                block_ids = sorted(mapping_refs & set(evidence.get("sourceBlockIds", [])))
                if not block_ids:
                    continue
                page_by_block = {page.get("sourceBlockId"): page for page in evidence.get("pages", [])}
                sources.append({
                    "originType": "textbook_derived_mapping",
                    "sourceDigest": evidence.get("bookSha256"),
                    "sourceIdentity": evidence.get("lessonIdentity"),
                    "sourceLocators": [
                        {"sourceBlockId": block_id, **({"physicalPageIndex": page_by_block[block_id]["physicalPageIndex"]} if page_by_block.get(block_id, {}).get("physicalPageIndex") is not None else {}), **({"printedPageLabel": page_by_block[block_id]["printedPageLabel"]} if page_by_block.get(block_id, {}).get("printedPageLabel") is not None else {})}
                        for block_id in block_ids
                    ],
                })
        return sources

    for mapping in [*proposal.get("lessonMappings", []), *proposal.get("knowledgeUnitMappings", [])]:
        item = {**mapping, "mappingType": "lesson_outcome" if mapping["mappingId"] in lesson_ids else "knowledge_unit_outcome", "sourceEvidence": mapping_source_evidence(mapping)}
        item["targetOutcomeCode"] = resolve_code(str(mapping.get("outcomeId") or ""))
        status = mapping.get("status")
        if status in {"accepted_internal_mapping", "accepted_unmapped", "rejected_by_reviewer"}:
            (reviewed_lesson if item["mappingType"] == "lesson_outcome" else reviewed_units).append(item)
            if item["mappingType"] == "knowledge_unit_outcome":
                ref = (mapping["lessonIdentity"], mapping["knowledgeUnitId"])
                if status == "accepted_unmapped":
                    unmapped_unit_refs.add(ref)
                elif status == "accepted_internal_mapping" and item["targetOutcomeCode"]:
                    mapped_unit_refs.add(ref)
        else:
            pending_mappings.append(item)

    resolved_outcomes = {item["candidateId"] for item in approved + rejected}
    resolved_outcomes.update(item["candidateId"] for item in merged + reuse_requests)
    remaining_queue = []
    outcome_status = {item["id"]: item.get("status", "needs_human_review") for item in proposal.get("outcomes", [])}
    mapping_status = {item["mappingId"]: item.get("status", "needs_human_review") for item in [*proposal.get("lessonMappings", []), *proposal.get("knowledgeUnitMappings", [])]}
    for group in proposal.get("reviewQueue", []):
        remaining_topics = []
        for topic in group.get("topics", []):
            pending_items = []
            for item in topic.get("items", []):
                if item.get("type") == "internal_outcome_candidate" and outcome_status.get(item.get("candidateId")) not in {"approved_internal", "rejected_by_reviewer", "merged_into", "reused_outcome"}:
                    pending_items.append(item)
                elif item.get("type") == "knowledge_unit_outcome_mapping" and mapping_status.get(item.get("mappingId")) not in {"accepted_internal_mapping", "accepted_unmapped", "rejected_by_reviewer"}:
                    pending_items.append(item)
            if pending_items:
                context = [item for item in topic.get("items", []) if item.get("type") == "source_concept_heading"]
                remaining_topics.append({**topic, "items": [*context, *pending_items]})
        if remaining_topics:
            remaining_queue.append({**group, "topics": remaining_topics})

    total_units = proposal.get("coverage", {}).get("acceptedKnowledgeUnits", 0)
    blockers.extend(f"{item['candidateId']}: {blocker}" for item in approved for blocker in item["syncBlockers"])
    if not approved and not reuse_requests:
        blockers.append("no human-approved internal outcomes or reuse decisions are available")
    blockers.extend((
        "BE target and database project identity have not been checked",
        "CurriculumOutcome.sourceEvidence migration has been prepared but not verified on the target",
    ))
    if any(item.get("status") != "accepted_internal_mapping" and item.get("status") != "accepted_unmapped" and item.get("status") != "rejected_by_reviewer" for item in pending_mappings):
        mapping_block = f"{len(pending_mappings)} Lesson/Knowledge Unit mappings still need human review"
    else:
        mapping_block = None
    return {
        "schemaVersion": 1,
        "kind": "nexalab-approved-internal-outcome-sync-bundle",
        "proposalVersion": proposal.get("proposalVersion"),
        "status": "needs_human_review" if pending or pending_mappings else "reviewed",
        "approvedInternalOutcomes": approved,
        "rejectedOutcomes": rejected,
        "mergedOutcomes": merged,
        "reuseRequests": reuse_requests,
        "reviewedLessonOutcomeMappings": reviewed_lesson,
        "reviewedKnowledgeUnitOutcomeMappings": reviewed_units,
        "mappingApprovalCoverage": {
            "totalSourceKnowledgeUnits": total_units,
            "unitsWithApprovedOutcomeMapping": len(mapped_unit_refs),
            "unitsDocumentedUnmapped": len(unmapped_unit_refs),
            "unitsPendingMappingReview": max(0, total_units - len(mapped_unit_refs) - len(unmapped_unit_refs)),
            "pendingMappingRows": len(pending_mappings),
        },
        "remainingHumanReviewQueue": remaining_queue,
        "registrySyncPreflight": {
            "ready": False,
            "status": "blocked" if blockers or pending_mappings else "ready_for_target_check",
            "provenancePersistenceContract": "migration_prepared_not_verified_on_target",
            "targetVerification": "not_run",
            "blockers": blockers + ([mapping_block] if mapping_block else []),
            "unapprovedOutcomeCount": len(pending),
            "approvedOutcomeCount": len(approved),
            "approvedReuseCount": len(reuse_requests),
            "unapprovedMappingCount": len(pending_mappings),
            "publishingPerformed": False,
        },
    }


def export_outcome_sync_bundle(workspace: Workspace, name: str) -> dict[str, Any]:
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "proposal"
    proposal = read_json(workspace.inside(".local", "outcomes", f"{safe_name}.json"))
    if not proposal.get("proposalVersion"):
        raise ContentToolError("Outcome proposal has no immutable version; regenerate it with outcomes-propose")
    bundle = build_outcome_sync_bundle(proposal)
    path = workspace.inside(".local", "outcomes", f"{safe_name}.sync-bundle.json")
    write_json(path, bundle)
    return {"path": str(path), "bundle": bundle}


def sync_approved_outcomes(
    workspace: Workspace,
    name: str,
    api_base: str,
    access_token: str,
    expected_project_ref: str | None = None,
) -> dict[str, Any]:
    """Create/reuse only explicitly reviewed internal outcomes; never writes Lessons or publishes."""
    if not access_token.strip():
        raise ContentToolError("A current BE admin access token is required")
    bundle_result = export_outcome_sync_bundle(workspace, name)
    bundle = bundle_result["bundle"]
    preflight = bundle["registrySyncPreflight"]
    approved = bundle["approvedInternalOutcomes"]
    reuse_requests = bundle["reuseRequests"]
    blockers = [
        *[f"{item['candidateId']}: {reason}" for item in approved for reason in item["syncBlockers"]],
        *[f"{item['candidateId']}: reuse target, registry attributes or source evidence are incomplete" for item in reuse_requests if not item.get("targetOutcomeCode") or not all((item.get("grade"), item.get("domain"), item.get("chapter"))) or not item.get("sourceEvidence") or any(not re.fullmatch(r"[a-fA-F0-9]{64}", str(source.get("sourceDigest", ""))) or not source.get("sourceLocators") for source in item.get("sourceEvidence", []))],
    ]
    if not approved and not reuse_requests:
        blockers.append("No explicitly approved outcome or reuse decision is available")
    if blockers:
        preflight["blockers"] = blockers
        raise ContentToolError("Outcome sync preflight blocked before API calls: " + "; ".join(blockers))

    # Reuse the existing guarded BE transport and target identity contract.
    from .curriculum_bootstrap import BE_SYNC_DOMAINS, _api_request

    unsupported = [item["candidateId"] for item in approved if item["grade"] not in (8, 9) or item["domain"] not in BE_SYNC_DOMAINS]
    unsupported.extend(item["candidateId"] for item in reuse_requests if item.get("grade") not in (8, 9) or item.get("domain") not in BE_SYNC_DOMAINS)
    if unsupported:
        raise ContentToolError("Current BE Curriculum Registry API only accepts grades 8-9 and its configured domains; blocked outcomes: " + ", ".join(unsupported))
    target = _api_request(api_base, access_token, "/admin/curriculum-target", expected_project_ref=expected_project_ref)
    local_target = isinstance(target, dict) and target.get("localDevelopmentTarget") is True
    remote_target = isinstance(target, dict) and bool(expected_project_ref) and target.get("remoteDevelopmentTarget") is True and target.get("projectRef") == expected_project_ref
    if not isinstance(target, dict) or target.get("environment") != "development" or target.get("configuredConnections") != 2 or not (local_target or remote_target) or target.get("outcomeSourceEvidencePersisted") is not True:
        raise ContentToolError("BE did not confirm the requested development database and CurriculumOutcome.sourceEvidence migration; no outcome writes were started")
    taxonomy = _api_request(api_base, access_token, "/admin/taxonomy", expected_project_ref=expected_project_ref)
    existing = {item.get("code"): item for item in taxonomy.get("outcomes", [])}
    created: list[str] = []
    reused: list[str] = []
    evidence_added: list[str] = []
    reason = f"Approved internal outcome proposal {bundle['proposalVersion']}"

    def append_evidence(outcome: dict[str, Any], evidence: list[dict[str, Any]], code: str) -> None:
        prior = outcome.get("sourceEvidence") if isinstance(outcome.get("sourceEvidence"), list) else []
        prior_by_id = {item.get("evidenceId"): item for item in prior}
        missing = [item for item in evidence if item.get("evidenceId") not in prior_by_id]
        conflicting = [item["evidenceId"] for item in evidence if item.get("evidenceId") in prior_by_id and prior_by_id[item["evidenceId"]] != item]
        if conflicting:
            raise ContentToolError(f"Existing Outcome {code} has conflicting source evidence IDs: {', '.join(conflicting)}")
        if missing:
            _api_request(api_base, access_token, f"/admin/outcomes/{code}", {
                "statement": outcome["statement"],
                "status": outcome.get("status", "active"),
                "sourceEvidence": missing,
                "reason": reason,
            }, expected_project_ref)
            evidence_added.extend(f"{code}:{item['evidenceId']}" for item in missing)
            outcome["sourceEvidence"] = [*prior, *missing]

    for item, is_reuse in [*((item, False) for item in approved), *((item, True) for item in reuse_requests)]:
        code = item.get("targetOutcomeCode") if is_reuse else item.get("code")
        current = existing.get(code)
        if current:
            if current.get("grade") != item.get("grade") or current.get("domain") != item.get("domain") or current.get("status") != "active" or current.get("synthetic") is True:
                raise ContentToolError(f"Existing Outcome {code} is archived, synthetic or has a different grade/domain; no records were overwritten")
            if not is_reuse and current.get("statement") != item.get("statement"):
                raise ContentToolError(f"Existing generated Outcome {code} has a different statement; no records were overwritten")
            reused.append(code)
            append_evidence(current, item.get("sourceEvidence", []), code)
        else:
            if is_reuse:
                raise ContentToolError(f"Human-selected reuse target {code} is absent from the BE taxonomy")
            payload = {key: item[key] for key in ("code", "grade", "domain", "chapter", "statement", "sourceEvidence")}
            _api_request(api_base, access_token, "/admin/outcomes", {**payload, "reason": reason}, expected_project_ref)
            created.append(code)
            existing[code] = {**payload, "status": "active", "synthetic": False}
    persisted_taxonomy = _api_request(api_base, access_token, "/admin/taxonomy", expected_project_ref=expected_project_ref)
    persisted_by_code = {item.get("code"): item for item in persisted_taxonomy.get("outcomes", [])}
    for item, is_reuse in [*((item, False) for item in approved), *((item, True) for item in reuse_requests)]:
        code = item.get("targetOutcomeCode") if is_reuse else item.get("code")
        persisted = persisted_by_code.get(code)
        expected_ids = {row.get("evidenceId") for row in item.get("sourceEvidence", [])}
        actual_rows = persisted.get("sourceEvidence") if isinstance(persisted, dict) else None
        actual_ids = {row.get("evidenceId") for row in actual_rows} if isinstance(actual_rows, list) else set()
        if not persisted or not expected_ids <= actual_ids:
            raise ContentToolError(f"Outcome {code} source evidence readback did not match the approved proposal")
    result = {
        "proposalVersion": bundle["proposalVersion"],
        "created": created,
        "reused": reused,
        "sourceEvidenceAdded": evidence_added,
        "sourceEvidenceVerified": True,
        "writeTarget": api_base,
        "publishPerformed": False,
        "lessonWritesPerformed": False,
    }
    receipt = workspace.inside(".local", "outcomes", f"{re.sub(r'[^A-Za-z0-9_-]+', '-', name).strip('-') or 'proposal'}.sync-receipt.json")
    write_json(receipt, result)
    bundle["registrySyncPreflight"].update({"ready": True, "status": "synced", "targetVerification": "passed", "blockers": []})
    bundle["syncReceipt"] = result
    write_json(workspace.inside(".local", "outcomes", f"{re.sub(r'[^A-Za-z0-9_-]+', '-', name).strip('-') or 'proposal'}.sync-bundle.json"), bundle)
    return result
