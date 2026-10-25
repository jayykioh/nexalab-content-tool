from __future__ import annotations

import re
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .enrichment import build_enrichment_proposal, normalize_text
from .m1_workflow import _book, _chapter, page_record, whole_book_report
from .workspace import Workspace, read_json, write_json


def export_chapter_candidates(workspace: Workspace, book_key: str, chapter_id: str) -> dict[str, Any]:
    """Export source-grounded review candidates; never promote OCR to an approved release."""
    book = _book(workspace, book_key)
    chapter = _chapter(book, chapter_id)
    outputs: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    blockers: dict[str, list[str]] = {}
    for lesson in chapter.get("lessons", []):
        pages = list(range(lesson["start"], lesson["end"] + 1))
        records = [page_record(workspace, book_key, number) for number in pages]
        coverage = [{
            "pdfPage": number,
            "printedPage": book["printedPageLabels"].get(str(number)),
            "sourceSha256": record.get("sourceSha256") if record else book["sha256"],
            "sourceVersion": book["version"],
            "method": record.get("method") if record else None,
            "blockCount": len(record.get("blocks", [])) if record else 0,
            "sourceBlockIds": [block.get("id") for block in record.get("blocks", []) if block.get("id")] if record else [],
            "textCharacters": sum(len(str(block.get("text", ""))) for block in record.get("blocks", [])) if record else 0,
            "reviewStatus": record.get("review", {}).get("status", "missing") if record else "missing",
            "warnings": record.get("flags", []) if record else ["Missing OCR page"],
        } for number, record in zip(pages, records)]
        missing = [item["pdfPage"] for item in coverage if item["textCharacters"] == 0]
        output = {"sourceLessonId": lesson["id"], "title": lesson["title"], "pdfPageRange": {"start": lesson["start"], "end": lesson["end"]}, "coverage": coverage, "structuredPath": None}
        outputs.append(output)
        lesson_blockers = [f"PDF pages without OCR text: {missing}"] if missing else []
        if not missing:
            proposal = build_enrichment_proposal(workspace, book_key, chapter_id, pages, allow_pending=True)
            blocks = proposal["blocks"]
            sections = []
            units = []
            for section, unit in zip(proposal["sections"], proposal["knowledgeUnits"]):
                heading = normalize_text(section["heading"])
                if (heading == "Nội dung bài học" or re.match(r"^Bài\s+\d+$", heading, re.IGNORECASE)
                    or re.match(r"^(MỤC TIÊU|EM CÓ|KẾT NỐI)", heading, re.IGNORECASE)):
                    continue
                limit = 3 if re.match(r"^EM ĐÃ HỌC", heading, re.IGNORECASE) else 2
                claims = [claim for claim in unit["claims"] if normalize_text(claim["text"]) != heading][:limit]
                concise = " ".join(claim["text"] for claim in claims).strip()
                if not concise:
                    continue
                sections.append({"id": section["id"], "heading": section["heading"], "content": concise, "sourceBlockIds": list(dict.fromkeys(block_id for claim in claims for block_id in claim["sourceBlockIds"]))})
                units.append({"id": unit["id"], "title": unit["title"], "claims": claims, "sourceBlockIds": unit["sourceBlockIds"], "status": "needs_review"})
            formulas = [{"id": block["id"], "text": block["normalizedText"], "sourceBlockIds": [block["id"]], "pdfPage": block["physicalPageIndex"], "status": "needs_review"} for block in blocks if block["normalizedText"] and (str(block["type"]).lower() == "equation" or "\\frac" in block["normalizedText"])]
            tables = [{"id": block["id"], "text": block["normalizedText"], "sourceBlockIds": [block["id"]], "pdfPage": block["physicalPageIndex"], "status": "needs_review"} for block in blocks if "table" in str(block["type"]).lower()]
            images = [{"id": block["id"], "pdfPage": block["physicalPageIndex"], "bbox": block.get("bbox"), "sourceBlockIds": [block["id"]], "status": "needs_description"} for block in blocks if str(block["type"]).lower() in {"image", "figure"}]
            definitions = [{"text": block["normalizedText"][:500], "sourceBlockIds": [block["id"]], "status": "needs_review"} for block in blocks if re.search(r"\b(là|được gọi là)\b", block["normalizedText"], re.IGNORECASE) and 20 <= len(block["normalizedText"]) <= 500][:12]
            examples = [{"text": block["normalizedText"][:700], "sourceBlockIds": [block["id"]], "status": "needs_review"} for block in blocks if re.search(r"\b(Ví dụ|Thí dụ)\b", block["normalizedText"], re.IGNORECASE)][:8]
            warnings = [f"PDF {item['pdfPage']}: {flag}" for item in coverage for flag in item["warnings"]]
            warnings.extend(f"PDF {item['pdfPage']}: OCR pending human review" for item in coverage if item["reviewStatus"] != "accepted")
            for block in blocks:
                if re.search(r"\d\s+\d\s*[,=]|[,=]\s*\d\s+\d", block["normalizedText"]):
                    warnings.append(f"PDF {block['physicalPageIndex']} block {block['id']}: ambiguous spaced digits/formula")
            if not sections:
                warnings.append("No concise section could be extracted")
            warnings.append("BASIC_EXERCISE omitted: source questions need authored options and a verified answer")
            recap = next((section for section in sections if re.match(r"^EM ĐÃ HỌC", section["heading"], re.IGNORECASE)), None)
            summary = normalize_text(recap["content"] if recap else " ".join(section["content"] for section in sections[:2]))[:800]
            summary_sources = recap["sourceBlockIds"] if recap else list(dict.fromkeys(block_id for section in sections[:2] for block_id in section["sourceBlockIds"]))
            artifact = {
                "schemaVersion": 1, "kind": "structured-lesson-candidate", "status": "needs_review",
                "book": {"key": book_key, "title": book["title"], "author": book["author"], "version": book["version"], "sha256": book["sha256"]},
                "chapter": {"id": chapter_id, "title": chapter["title"]},
                "sourceLesson": {"id": lesson["id"], "title": lesson["title"], "tocProvenance": chapter.get("tocProvenance")},
                "printedPageRange": {"start": lesson.get("printedStart"), "end": lesson.get("printedEnd")},
                "pdfPageRange": output["pdfPageRange"], "sourcePdf": str(workspace.inside(".local", "books", book_key, "source.pdf")),
                "ocrCoverage": coverage,
                "sourceBlocks": blocks,
                "learningContent": {"sections": sections, "summary": summary, "summarySourceBlockIds": summary_sources, "knowledgeUnits": units, "definitions": definitions, "formulas": formulas, "tables": tables, "sourceImages": images, "examples": examples, "basicExercises": []},
                "warnings": list(dict.fromkeys(warnings)),
            }
            path = workspace.inside("exports", "structured", f"{lesson['id']}.json")
            existing = read_json(path) if path.exists() else None
            if existing:
                prior_content = existing.get("learningContent", {})
                for key, value in prior_content.items():
                    artifact["learningContent"][key] = copy.deepcopy(value)
                artifact = {**existing, **artifact}
                artifact["learningContent"] = {**artifact.get("learningContent", {}), **copy.deepcopy(prior_content)}
                artifact["sourceBlocks"] = _merge_source_blocks(existing.get("sourceBlocks", []), blocks)
                artifact["status"] = existing.get("status", artifact["status"])
                prior_review = existing.get("contentReview")
                artifact["contentReview"] = copy.deepcopy(prior_review) if isinstance(prior_review, dict) and prior_review.get("status") in {"accepted", "needs_review"} else {"status": "needs_review", "history": []}
            else:
                artifact["contentReview"] = {"status": "needs_review", "history": []}
            review = artifact["contentReview"]
            if review.get("status") == "accepted" and (
                review.get("acceptedContentSha256") != _content_hash(artifact.get("learningContent", {}))
                or review.get("acceptedSourceBlocksSha256") != _source_blocks_hash(artifact.get("sourceBlocks", []))
            ):
                history = list(review.get("history", []))
                history.append({"action": "acceptance_invalidated", "reason": "source_or_content_changed", "at": datetime.now(timezone.utc).isoformat()})
                artifact["contentReview"] = {"status": "needs_review", "history": history}
                workspace.inside("exports", "approved-structured", f"{lesson['id']}.json").unlink(missing_ok=True)
            write_json(path, artifact)
            output["structuredPath"] = str(path)
            output["contentReviewStatus"] = artifact.get("contentReview", {}).get("status", "needs_review")
            if any(item["reviewStatus"] != "accepted" for item in coverage):
                lesson_blockers.append("OCR pages require human correction and acceptance")
            if artifact.get("contentReview", {}).get("status") != "accepted":
                lesson_blockers.append("Local content review has not been accepted by a human")
            if artifact["warnings"]:
                lesson_blockers.append("Scientific content, formulas and OCR warnings require human review")
            content = artifact["learningContent"]
            used_units = content.get("knowledgeUnits", [])
            mapping.append({"sourceLessonId": lesson["id"], "structuredPath": str(path), "pack": {
                "key": lesson["id"], "title": lesson["title"], "grade": 8, "domain": None,
                "chapter": chapter["title"], "topic": chapter["title"], "subjectId": None,
                "outcomeCodes": [], "synthetic": False,
                "sources": [{"id": book_key, "title": book["title"], "author": book["author"], "license": "UNKNOWN", "attribution": f"{book['title']} — {book['author']}"}],
                "knowledgeUnits": [{"id": unit["id"], "outcomeCodes": [], "claims": [{"id": claim["id"], "text": claim["text"], "sourceIds": [book_key], "important": False} for claim in unit.get("claims", [])], "terms": [], "misconceptions": []} for unit in used_units],
                "lesson": {"learningObjective": proposal["learningObjective"], "prerequisites": "", "content": "\n".join(section.get("content", "") for section in content.get("sections", [])), "materials": [], "questions": [], "labId": None},
                "reviews": {},
            }})
        lesson_blockers.extend(["Curriculum domain, outcome and subject ID are unassigned or unverified", "Publication rights/license, source access date and pinned source asset are unresolved", "BE source policy has not been authored", "Editorial, subject, rights and accessibility reviews are missing"])
        blockers[lesson["id"]] = lesson_blockers
    candidate = {"kind": "non-release-ready-be-manifest-mapping", "targetSchema": "releaseManifestSchema", "ready": False, "releaseManifestCandidate": {"name": f"{book_key}-{chapter_id}-candidate", "namespace": "baseline", "sources": [], "packs": [item["pack"] for item in mapping]}, "mappings": mapping, "blockers": blockers, "coverage": outputs}
    path = workspace.inside("exports", f"{chapter_id}-be-candidate.json")
    write_json(path, candidate)
    return {"candidatePath": str(path), "lessons": outputs, "blockers": blockers}


def _merge_source_blocks(existing: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old = {block.get("id"): block for block in existing if isinstance(block, dict) and block.get("id")}
    merged = []
    for block in current:
        prior = old.get(block.get("id"), {})
        merged.append({**prior, **block})
    return merged


def _content_hash(content: dict[str, Any]) -> str:
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_blocks_hash(blocks: list[dict[str, Any]]) -> str:
    return _content_hash({"sourceBlocks": blocks})


def _lesson_artifact_path(workspace: Workspace, lesson_id: str):
    return workspace.inside("exports", "structured", f"{lesson_id}.json")


def load_structured_lesson(workspace: Workspace, book_key: str, chapter_id: str, lesson_id: str) -> dict[str, Any]:
    chapter = _chapter(_book(workspace, book_key), chapter_id)
    if lesson_id not in {lesson["id"] for lesson in chapter.get("lessons", [])}:
        raise ValueError("Choose a source Lesson in the selected chapter")
    path = _lesson_artifact_path(workspace, lesson_id)
    if not path.is_file():
        raise ValueError("Run structured export after the Lesson OCR batch is complete")
    return read_json(path)


def save_structured_content(workspace: Workspace, book_key: str, chapter_id: str, lesson_id: str, content: dict[str, Any]) -> dict[str, Any]:
    artifact = load_structured_lesson(workspace, book_key, chapter_id, lesson_id)
    if not isinstance(content, dict) or not isinstance(content.get("summary"), str) or not content["summary"].strip():
        raise ValueError("Add a non-empty Lesson summary")
    arrays = ("sections", "knowledgeUnits", "formulas", "tables")
    if any(not isinstance(content.get(key, []), list) for key in arrays):
        raise ValueError("Sections, knowledge units, formulas and tables must be JSON arrays")
    source_ids = {block.get("id") for block in artifact.get("sourceBlocks", []) if block.get("id")}
    summary_references = content.get("summarySourceBlockIds", artifact.get("learningContent", {}).get("summarySourceBlockIds", []))
    if not isinstance(summary_references, list) or any(reference not in source_ids for reference in summary_references):
        raise ValueError("Summary contains an unknown source block reference")
    for key in arrays:
        for item in content.get(key, []):
            if not isinstance(item, dict):
                raise ValueError(f"{key} entries must be JSON objects")
            if key in {"sections", "knowledgeUnits"} and not str(item.get("id", "")).strip():
                raise ValueError(f"Each {key} entry must keep its stable ID")
            references = item.get("sourceBlockIds", [])
            if not isinstance(references, list) or any(reference not in source_ids for reference in references):
                raise ValueError(f"{key} contains an unknown source block reference")
            if key == "knowledgeUnits" and any(not isinstance(claim, dict) or not str(claim.get("text", "")).strip() for claim in item.get("claims", [])):
                raise ValueError("Knowledge unit claims need text")
    if not content.get("sections") or not content.get("knowledgeUnits"):
        raise ValueError("A complete Lesson needs at least one section and one knowledge unit")
    prior_review = artifact.get("contentReview")
    previous = copy.deepcopy(prior_review) if isinstance(prior_review, dict) else {"status": "needs_review", "history": []}
    history = list(previous.get("history", []))
    history.append({"action": "edited", "at": datetime.now(timezone.utc).isoformat()})
    artifact["learningContent"] = {**artifact.get("learningContent", {}), **copy.deepcopy(content)}
    artifact["contentReview"] = {"status": "needs_review", "history": history}
    artifact["updatedAt"] = datetime.now(timezone.utc).isoformat()
    write_json(_lesson_artifact_path(workspace, lesson_id), artifact)
    workspace.inside("exports", "approved-structured", f"{lesson_id}.json").unlink(missing_ok=True)
    return artifact


def accept_structured_content(
    workspace: Workspace,
    book_key: str,
    chapter_id: str,
    lesson_id: str,
    *,
    human_review_confirmed: bool,
    reviewer_name: str,
    reviewer_email: str,
    reason: str,
) -> dict[str, Any]:
    if human_review_confirmed is not True:
        raise ValueError("Human source and warning review confirmation is required")
    reviewer_name, reviewer_email, reason = reviewer_name.strip(), reviewer_email.strip().lower(), reason.strip()
    if len(reviewer_name) < 2 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reviewer_email) or not 5 <= len(reason) <= 500:
        raise ValueError("A named reviewer, valid email and 5–500 character reason are required")
    artifact = load_structured_lesson(workspace, book_key, chapter_id, lesson_id)
    content = artifact.get("learningContent", {})
    if not str(content.get("summary", "")).strip() or not content.get("sections") or not content.get("knowledgeUnits"):
        raise ValueError("The Lesson summary, sections and knowledge units must be complete")
    page_range = artifact.get("pdfPageRange", {})
    expected = list(range(page_range.get("start", 0), page_range.get("end", -1) + 1))
    coverage = artifact.get("ocrCoverage", [])
    if [item.get("pdfPage") for item in coverage] != expected or any(not item.get("sourceSha256") or not item.get("sourceBlockIds") or not item.get("textCharacters") for item in coverage):
        raise ValueError("Complete OCR text and page/block provenance are required before accepting this Lesson")
    now = datetime.now(timezone.utc).isoformat()
    previous_review = artifact.get("contentReview")
    review = copy.deepcopy(previous_review) if isinstance(previous_review, dict) else {"history": []}
    review["status"] = "accepted"
    review["acceptedAt"] = now
    review["acceptedBy"] = {"name": reviewer_name, "email": reviewer_email}
    review["reason"] = reason
    review["acceptedContentSha256"] = _content_hash(content)
    review["acceptedSourceBlocksSha256"] = _source_blocks_hash(artifact.get("sourceBlocks", []))
    review.setdefault("history", []).append({"action": "accepted", "at": now, "reviewerName": reviewer_name, "reviewerEmail": reviewer_email, "reason": reason, "contentSha256": review["acceptedContentSha256"]})
    artifact["contentReview"] = review
    artifact["updatedAt"] = now
    write_json(_lesson_artifact_path(workspace, lesson_id), artifact)
    return artifact


def export_approved_lesson(workspace: Workspace, book_key: str, chapter_id: str, lesson_id: str) -> dict[str, Any]:
    artifact = load_structured_lesson(workspace, book_key, chapter_id, lesson_id)
    review = artifact.get("contentReview", {})
    if (
        review.get("status") != "accepted"
        or not isinstance(review.get("acceptedBy"), dict)
        or not review["acceptedBy"].get("name")
        or not review["acceptedBy"].get("email")
        or review.get("acceptedContentSha256") != _content_hash(artifact.get("learningContent", {}))
        or review.get("acceptedSourceBlocksSha256") != _source_blocks_hash(artifact.get("sourceBlocks", []))
    ):
        raise ValueError("This local Lesson has no current human content acceptance")
    target = workspace.inside("exports", "approved-structured", f"{lesson_id}.json")
    write_json(target, artifact)
    return {"path": str(target), "lessonId": lesson_id, "contentReviewStatus": "accepted"}


def export_book_candidates(workspace: Workspace, book_key: str) -> dict[str, Any]:
    book = _book(workspace, book_key)
    chapter_candidates = [export_chapter_candidates(workspace, book_key, chapter["id"]) for chapter in book.get("chapters", []) if chapter.get("lessons")]
    mappings, coverage, blockers = [], [], {}
    for result in chapter_candidates:
        candidate = read_json(workspace.inside("exports", Path(result["candidatePath"]).name))
        mappings.extend(candidate.get("mappings", []))
        coverage.extend(candidate.get("coverage", []))
        blockers.update(candidate.get("blockers", {}))
    report = whole_book_report(workspace, book_key)
    for lesson in report["lessons"]:
        path = _lesson_artifact_path(workspace, lesson["id"])
        lesson["structuredPath"] = str(path) if path.is_file() else None
    candidate = {"kind": "non-release-ready-be-manifest-mapping", "targetSchema": "releaseManifestSchema", "ready": False, "book": {"key": book_key, "title": book["title"], "version": book["version"], "sha256": book["sha256"]}, "releaseManifestCandidate": {"name": f"{book_key}-candidate", "namespace": "baseline", "sources": [], "packs": [item["pack"] for item in mappings]}, "mappings": mappings, "blockers": blockers, "coverage": coverage, "wholeBookReport": report["reportPath"]}
    candidate_path = workspace.inside("exports", f"{book_key}-be-candidate.json")
    blockers_path = workspace.inside("exports", f"{book_key}-blocker-report.json")
    write_json(candidate_path, candidate)
    blocker_report = {"schemaVersion": 1, "kind": "be-candidate-blocker-report", "candidatePath": str(candidate_path), "ready": False, "lessonBlockers": blockers, "wholeBookReport": report["reportPath"], "unconfirmedLessonIds": report["unconfirmedLessonIds"], "blockingLessonCount": sum(bool(items) for items in blockers.values())}
    write_json(blockers_path, blocker_report)
    lines = [f"# BE candidate blockers — {book['title']}", "", "Status: NOT release-ready. No curriculum outcomes, rights, or human formal reviews were inferred.", "", f"Lessons in candidate: {len(mappings)}", f"Lessons with blockers: {blocker_report['blockingLessonCount']}", f"TOC ranges not human-confirmed: {len(report['unconfirmedLessonIds'])}", "", "## Per-Lesson blockers", ""]
    for lesson_id, items in blockers.items():
        lines.append(f"- `{lesson_id}`: " + "; ".join(items))
    lines.extend(["", "## Book-wide blockers", "", "- Curriculum domain, outcome codes, and subject IDs are unassigned or unverified.", "- Publication rights/license and source-asset pinning remain unresolved.", "- Editorial, subject, rights, and accessibility release reviews are absent.", "- Local content acceptance does not satisfy BE release review.", ""])
    markdown_path = workspace.inside("exports", f"{book_key}-blocker-report.md")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"candidatePath": str(candidate_path), "blockerReportPath": str(blockers_path), "blockerMarkdownPath": str(markdown_path), "lessonCount": len(mappings), "blockers": blockers}


def validate_book_outputs(workspace: Workspace, book_key: str) -> dict[str, Any]:
    book = _book(workspace, book_key)
    report = whole_book_report(workspace, book_key, save=False)
    failures = []
    lessons = []
    for lesson in report["lessons"]:
        path = _lesson_artifact_path(workspace, lesson["id"])
        if not path.is_file():
            lessons.append({"id": lesson["id"], "status": "missing-json", "path": None})
            continue
        artifact = read_json(path)
        expected = list(range(lesson["pdfPageRange"]["start"], lesson["pdfPageRange"]["end"] + 1))
        coverage = artifact.get("ocrCoverage", [])
        page_ids = [item.get("pdfPage") for item in coverage]
        source_blocks = artifact.get("sourceBlocks", [])
        source_ids = [block.get("id") for block in source_blocks if isinstance(block, dict)]
        source_id_set = set(source_ids)
        issues = []
        if artifact.get("schemaVersion") != 1 or artifact.get("kind") != "structured-lesson-candidate":
            issues.append("schemaVersion/kind mismatch")
        if artifact.get("book", {}).get("sha256") != book["sha256"]:
            issues.append("book source SHA-256 mismatch")
        if artifact.get("sourceLesson", {}).get("id") != lesson["id"]:
            issues.append("stable source Lesson ID mismatch")
        if page_ids != expected:
            issues.append("page provenance incomplete or out of order")
        if len(source_ids) != len(set(source_ids)):
            issues.append("duplicate source block IDs")
        if any(item.get("sourceSha256") != book["sha256"] or not item.get("sourceVersion") or not item.get("sourceBlockIds") for item in coverage):
            issues.append("page source/block provenance incomplete")
        if any(not set(item.get("sourceBlockIds", [])).issubset(source_id_set) for item in coverage):
            issues.append("page provenance references missing source blocks")
        if any(not isinstance(block, dict) or block.get("sourceSha256") != book["sha256"] or not block.get("physicalPageIndex") or not block.get("extractionMethod") for block in source_blocks):
            issues.append("source block provenance incomplete")
        content = artifact.get("learningContent")
        if not isinstance(content, dict) or not isinstance(content.get("summary"), str) or not content.get("summary", "").strip():
            issues.append("Lesson summary missing or invalid")
        if not isinstance(content, dict) or not isinstance(content.get("sections"), list) or not content.get("sections"):
            issues.append("Lesson sections missing or invalid")
        if not isinstance(content, dict) or not isinstance(content.get("knowledgeUnits"), list) or not content.get("knowledgeUnits"):
            issues.append("knowledge units missing or invalid")
        if isinstance(content, dict):
            summary_refs = content.get("summarySourceBlockIds", [])
            if not isinstance(summary_refs, list) or not set(summary_refs).issubset(source_id_set):
                issues.append("summary source references are invalid")
            for key in ("sections", "knowledgeUnits", "formulas", "tables"):
                values = content.get(key, [])
                if not isinstance(values, list):
                    issues.append(f"{key} must be a JSON array")
                    continue
                for value in values:
                    if not isinstance(value, dict):
                        issues.append(f"{key} contains a non-object entry")
                        continue
                    if key in {"sections", "knowledgeUnits"} and not str(value.get("id", "")).strip():
                        issues.append(f"{key} entry has no stable ID")
                    refs = value.get("sourceBlockIds", [])
                    if not isinstance(refs, list) or (refs and not set(refs).issubset(source_id_set)):
                        issues.append(f"{key} source references are invalid")
                    if key == "knowledgeUnits" and (not isinstance(value.get("claims"), list) or not value.get("claims") or any(not isinstance(claim, dict) or not str(claim.get("id", "")).strip() or not str(claim.get("text", "")).strip() for claim in value.get("claims", []))):
                        issues.append("knowledge unit claim schema is invalid")
        review = artifact.get("contentReview")
        if not isinstance(review, dict) or review.get("status") not in {"accepted", "needs_review"}:
            issues.append("invalid local content review status")
        elif review.get("status") == "accepted" and (
            review.get("acceptedContentSha256") != _content_hash(content or {})
            or review.get("acceptedSourceBlocksSha256") != _source_blocks_hash(source_blocks)
        ):
            issues.append("human acceptance does not match current content or source blocks")
        if issues:
            failures.append({"lessonId": lesson["id"], "issues": issues})
        review_status = review.get("status", "needs_review") if isinstance(review, dict) else "needs_review"
        review_blockers = []
        if review_status != "accepted":
            review_blockers.append("local content has not been human accepted")
        pending_ocr = [item["pdfPage"] for item in coverage if item.get("reviewStatus") != "accepted"]
        if pending_ocr:
            review_blockers.append(f"OCR page review pending: {len(pending_ocr)} pages")
        if artifact.get("warnings"):
            review_blockers.append(f"unresolved content warnings: {len(artifact['warnings'])}")
        if lesson.get("tocStatus") != "confirmed":
            review_blockers.append("TOC Lesson range is not human confirmed")
        lessons.append({"id": lesson["id"], "path": str(path), "status": "valid" if not issues else "invalid", "contentReviewStatus": review_status, "readiness": "needs_review" if review_blockers else "locally_accepted", "reviewBlockers": review_blockers, "pendingOcrReviewPages": pending_ocr, "pages": len(coverage), "sourceBlocks": len(source_ids), "unresolvedWarnings": len(artifact.get("warnings", []))})
    result = {"schemaVersion": 1, "kind": "structured-lesson-validation-report", "bookKey": book_key, "sourceSha256": book["sha256"], "status": "valid" if not failures else "invalid", "lessonCount": len(report["lessons"]), "validJsonCount": sum(item["status"] == "valid" for item in lessons), "missingJsonCount": sum(item["status"] == "missing-json" for item in lessons), "reviewBlockerCount": sum(len(item.get("reviewBlockers", [])) for item in lessons), "unreviewedLessonCount": sum(item.get("readiness") != "locally_accepted" for item in lessons), "failures": failures, "lessons": lessons, "unconfirmedLessonIds": report["unconfirmedLessonIds"]}
    write_json(workspace.inside("exports", f"{book_key}-structured-validation.json"), result)
    return result
