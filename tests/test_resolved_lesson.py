import copy
import json
from pathlib import Path

import pytest

from nexalab_content_tool.resolved_lesson import (
    LessonContractError,
    canonical_to_pack,
    load_resolved,
    resolve_lesson,
    build_canonical,
    apply_to_structured,
)
from nexalab_content_tool.structured_merge import build_lesson

P = "bk-v1-"
LESSON = "lesson-x"


def _block(n: int, page: int, text: str, type_: str = "text") -> dict:
    return {"id": f"{P}p{page:04d}-b{n:04d}", "type": type_, "normalizedText": text, "physicalPageIndex": page, "printedPageLabel": str(page), "extractionMethod": "test", "bbox": [0, 0, 1, 1]}


def _lesson() -> dict:
    b1, b2 = _block(1, 1, "Một câu nguồn đúng."), _block(1, 2, "Câu hai của nguồn.")
    return {
        "book": {"key": "bk", "version": "v1", "sha256": "a" * 64, "title": "Book", "author": "Author"},
        "chapter": {"id": "c", "title": "Chapter"},
        "sourceLesson": {"id": LESSON, "title": "Lesson"},
        "pdfPageRange": {"start": 1, "end": 2}, "printedPageRange": {"start": 1, "end": 2},
        "sourceBlocks": [b1, b2],
        "sourceReading": {"sections": [
            {"id": "s1", "heading": "Một", "content": b1["normalizedText"], "sourceBlockIds": [b1["id"]]},
            {"id": "s2", "heading": "Hai", "content": b2["normalizedText"], "sourceBlockIds": [b2["id"]]},
        ]},
        "learningContent": {
            "sections": [
                {"id": "s1", "heading": "Một", "content": "Một câu nguồn đứng.", "sourceBlockIds": [b1["id"]]},
                {"id": "s2", "heading": "Hai", "content": b2["normalizedText"], "sourceBlockIds": [b2["id"]]},
            ],
            "summary": "old", "summarySourceBlockIds": [], "tables": [], "formulas": [], "sourceImages": [], "basicExercises": [],
            "knowledgeUnits": [
                {"id": "u1", "title": "Một", "claims": [{"id": "c1", "text": "Một câu nguồn đứng.", "sourceBlockIds": [b1["id"]]}]},
                {"id": "u2", "heading": "Hai", "title": "Hai", "claims": [{"id": "c2", "text": b2["normalizedText"], "sourceBlockIds": [b2["id"]]}]},
            ],
        },
        "contentReview": {"status": "accepted", "history": []},
    }


AUTHORING = {
    "packKey": "pack-x", "title": "Lesson", "grade": 9, "domain": "ENERGY", "subjectId": "physics", "topic": "T",
    "outcomeCodes": ["O/1", "O/2"], "curriculumVerification": "unverified", "learningObjective": "Objective text",
    "source": {"accessedAt": "2026-10-23", "license": "UNKNOWN", "attribution": "Book - Author"},
    "summary": {"text": "Tóm tắt.", "sourceBlockIds": [f"{P}p0001-b0001"]},
    "unitOutcomes": {"Một": ["O/1"], "Hai": ["O/2"]},
    "claims": {"p0001-b0001": {"important": False, "basis": "x"}, "p0002-b0001": {"important": True, "basis": "y"}},
    "formulas": [], "tables": [], "images": {}, "basicExercises": None,
}
COMPONENTS = {name: {"state": "not_applicable", "reason": "none in this fixture", "sourceBlockIds": []} for name in ("headings", "summary", "knowledgeUnits", "formulas", "tables", "images", "basicExercises")}


def _decisions(lesson: dict, action: str = "source") -> dict:
    built = build_lesson(lesson)
    items = [h for s in built["sections"] for h in s["held"]]
    return {"schemaVersion": 1, "lessonId": LESSON, "inputFingerprint": built["fingerprint"], "components": COMPONENTS, "decisions": [
        {"itemId": h["id"], "fingerprint": h["fingerprint"], "action": action, "replacement": None, "sourceBlockIds": [], "reason": "PDF shows the source wording", "actor": "test", "reviewKind": "agent-source-check"} for h in items]}


def _workspace(tmp_path: Path, decisions: dict | None) -> tuple[Path, Path]:
    root = tmp_path / "ws"
    (root / "exports" / "structured").mkdir(parents=True)
    (root / "exports" / "approved-structured").mkdir(parents=True)
    (root / "exports" / "structured" / f"{LESSON}.json").write_text(json.dumps(_lesson(), ensure_ascii=False), encoding="utf-8")
    (root / "exports" / "approved-structured" / f"{LESSON}.json").write_text("{}", encoding="utf-8")
    folder = root / "release-prep" / "x"
    folder.mkdir(parents=True)
    (folder / "authoring.json").write_text(json.dumps(AUTHORING, ensure_ascii=False), encoding="utf-8")
    if decisions is not None:
        (folder / "decisions.json").write_text(json.dumps(decisions, ensure_ascii=False), encoding="utf-8")
    return root, folder


def test_no_decisions_is_blocked_and_writes_no_canonical(tmp_path):
    root, folder = _workspace(tmp_path, None)
    result = resolve_lesson(root, LESSON, folder)
    assert not result["resolved"]
    assert {p["code"] for p in result["report"]["problems"]} == {"UNRESOLVED_ITEM"}
    assert not (folder / "canonical.json").exists()


def test_stale_fingerprint_voids_every_decision(tmp_path):
    decisions = _decisions(_lesson())
    decisions["inputFingerprint"] = "0" * 64
    root, folder = _workspace(tmp_path, decisions)
    result = resolve_lesson(root, LESSON, folder)
    assert not result["resolved"]
    assert any(p["code"] == "STALE_DECISION" for p in result["report"]["problems"])


def test_item_fingerprint_mismatch_and_invalid_actions_are_reported(tmp_path):
    decisions = _decisions(_lesson())
    decisions["decisions"][0]["fingerprint"] = "bad"
    root, folder = _workspace(tmp_path, decisions)
    codes = {p["code"] for p in resolve_lesson(root, LESSON, folder)["report"]["problems"]}
    assert "STALE_DECISION" in codes
    decisions = _decisions(_lesson(), action="replace")
    root, folder = _workspace(tmp_path / "b", decisions)
    assert {p["code"] for p in resolve_lesson(root, LESSON, folder)["report"]["problems"]} == {"INVALID_DECISION"}


def test_resolved_lesson_applies_content_cancels_acceptance_and_keeps_the_original(tmp_path):
    root, folder = _workspace(tmp_path, _decisions(_lesson()))
    result = resolve_lesson(root, LESSON, folder)
    assert result["resolved"] and result["canonical"]["contentStatus"] == "resolved"
    saved = json.loads((root / "exports" / "structured" / f"{LESSON}.json").read_text(encoding="utf-8"))
    assert saved["contentReview"]["status"] == "needs_review"
    assert saved["contentReview"]["history"][-1]["action"] == "canonical_applied"
    assert not (root / "exports" / "approved-structured" / f"{LESSON}.json").exists()
    assert saved["learningContentOriginal"]["sections"][0]["content"] == "Một câu nguồn đứng."
    assert saved["learningContent"]["sections"][0]["content"] == "Một câu nguồn đúng."
    canonical, loaded = load_resolved(root, LESSON)  # still current after applying
    assert canonical["contentStatus"] == "resolved"


def test_editing_learning_content_after_apply_makes_the_canonical_stale(tmp_path):
    root, folder = _workspace(tmp_path, _decisions(_lesson()))
    resolve_lesson(root, LESSON, folder)
    path = root / "exports" / "structured" / f"{LESSON}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["learningContent"]["sections"][0]["content"] = "Đã sửa tay."
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LessonContractError) as error:
        load_resolved(root, LESSON)
    assert error.value.code == "STALE_DECISION"


def test_changed_source_block_makes_the_canonical_stale(tmp_path):
    root, folder = _workspace(tmp_path, _decisions(_lesson()))
    resolve_lesson(root, LESSON, folder)
    path = root / "exports" / "structured" / f"{LESSON}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["sourceBlocks"][0]["physicalPageIndex"] = 99
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LessonContractError) as error:
        load_resolved(root, LESSON)
    assert error.value.code == "STALE_DECISION"


def _canonical(tmp_path):
    root, folder = _workspace(tmp_path, _decisions(_lesson()))
    result = resolve_lesson(root, LESSON, folder, apply=False)
    assert result["resolved"], result["report"]["problems"]
    return result["canonical"], _lesson()["sourceBlocks"]


def test_converter_emits_evidence_per_claim_page_only(tmp_path):
    canonical, blocks = _canonical(tmp_path)
    out = canonical_to_pack(canonical, blocks)
    pages = {}
    for item in out["evidence"]:
        if "claimId" in item:
            pages.setdefault(item["claimId"], set()).add(item["physicalPageIndex"])
    assert pages == {"c1": {1}, "c2": {2}}
    assert [c["important"] for u in out["pack"]["knowledgeUnits"] for c in u["claims"]] == [False, True]
    assert out["pack"]["knowledgeUnits"][0]["outcomeCodes"] == ["O/1"] and out["pack"]["knowledgeUnits"][1]["outcomeCodes"] == ["O/2"]
    assert out["pack"]["lesson"]["sgkReference"] == {
        "sourceId": "bk", "sourceVersion": "v1", "sourceSha256": "a" * 64,
        "sourceLessonId": LESSON, "sourceLessonTitle": "Lesson",
        "chapterId": "c", "chapterTitle": "Chapter",
        "pdfPageRange": {"start": 1, "end": 2}, "printedPageRange": {"start": 1, "end": 2},
    }


def test_converter_is_deterministic_and_candidate_equals_pack(tmp_path):
    canonical, blocks = _canonical(tmp_path)
    assert canonical_to_pack(canonical, blocks)["packDigest"] == canonical_to_pack(copy.deepcopy(canonical), blocks)["packDigest"]


@pytest.mark.parametrize("mutate, code", [
    (lambda c: c["sources"][0].update(accessedAt=None), "MISSING_SOURCE_ACCESSED_AT"),
    (lambda c: c["knowledgeUnits"][0].update(outcomeCodes=["O/9"]), "MISSING_UNIT_OUTCOME"),
    (lambda c: c["knowledgeUnits"][0]["claims"][0].update(sourceBlockIds=[]), "CLAIM_EVIDENCE_MISSING"),
    (lambda c: c.update(contentStatus="unresolved"), "UNRESOLVED_CONTENT"),
])
def test_converter_blocks_instead_of_inventing_data(tmp_path, mutate, code):
    canonical, blocks = _canonical(tmp_path)
    mutate(canonical)
    with pytest.raises(LessonContractError) as error:
        canonical_to_pack(canonical, blocks)
    assert error.value.code == code


def test_claim_importance_must_be_authored(tmp_path):
    root, folder = _workspace(tmp_path, _decisions(_lesson()))
    authoring = copy.deepcopy(AUTHORING)
    del authoring["claims"]["p0002-b0001"]["important"]
    with pytest.raises(LessonContractError) as error:
        build_canonical(_lesson(), _decisions(_lesson()), authoring, LESSON)
    assert error.value.code == "CLAIM_IMPORTANCE_MISSING"


def test_duplicate_or_missing_section_ids_are_rejected_before_merge():
    lesson = _lesson()
    lesson["sourceReading"]["sections"].append(dict(lesson["sourceReading"]["sections"][0]))
    with pytest.raises(ValueError):
        build_lesson(lesson)
    lesson = _lesson()
    lesson["learningContent"]["sections"][0].pop("id")
    with pytest.raises(ValueError):
        build_lesson(lesson)
    lesson = _lesson()
    lesson["sourceReading"]["sections"][0] = "not an object"
    with pytest.raises(ValueError):
        build_lesson(lesson)
