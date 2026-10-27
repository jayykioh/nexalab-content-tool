import json
from pathlib import Path

from nexalab_content_tool.structured_merge import (
    build_block_index,
    build_lesson,
    build_preview,
    merge_section,
    norm,
    split_units,
)

FIXTURE = Path(__file__).parent / "fixtures" / "merge_bai01_intro.json"
SOURCE_SENTENCE = "Điều tra và nghiên cứu về các bệnh này sẽ cung cấp thông tin quan trọng để nâng cao ý thức về vệ sinh an toàn thực phẩm và phòng ngừa bệnh tật đường tiêu hoá."
FRAGMENT = "Mục tiêu của nghiên cứu này là:"


def _sec(learning: str | None, source: str | None, blocks: list[dict] | None = None) -> dict:
    """The section owns the given blocks, as in a real Structured JSON section."""
    blocks = blocks or []
    index = build_block_index({"sourceBlocks": blocks})
    owned = [b["id"] for b in blocks]
    return merge_section(
        {"id": "x", "heading": "h", "content": learning, "sourceBlockIds": owned} if learning is not None else None,
        {"id": "x", "heading": "h", "content": source, "sourceBlockIds": owned} if source is not None else None,
        index,
    )


def _held_kinds(section: dict) -> list[str]:
    return [item["kind"] for item in section["held"]]


def _accounted(section: dict) -> None:
    assert section["lostSource"] == []
    assert section["lostLearning"] == []


# --- equality keeps symbols, operators, digits and Greek letters -----------------

def test_plus_and_minus_are_not_equal():
    section = _sec("U = I + R.", "U = I - R.")
    assert "U = I + R." not in section["merged"]
    assert _held_kinds(section) == ["near_pair"]
    assert section["held"][0]["diff"] == [{"op": "replace", "learning": "+", "source": "-"}] or section["held"][0]["diff"]
    _accounted(section)


def test_alpha_equal_and_not_equal_are_not_equal():
    section = _sec("α = β.", "α ≠ β.")
    assert _held_kinds(section) == ["near_pair"]
    assert section["merged"] == ""
    _accounted(section)


def test_accent_difference_that_changes_the_word_is_a_held_pair_not_exact():
    section = _sec("Viên bi rơi.", "Viên bị rơi.")
    assert _held_kinds(section) == ["near_pair"]
    assert section["held"][0]["learning"]["text"] == "Viên bi rơi."
    assert section["held"][0]["source"]["text"] == "Viên bị rơi."
    _accounted(section)


def test_numeric_source_sentence_is_not_dropped_as_a_page_number_without_block_evidence():
    section = _sec(None, "Nguồn chỉ có 100.")
    assert section["merged"] == "Nguồn chỉ có 100."
    assert section["sourceUnits"][0]["disposition"] == "emitted"


# --- page numbers are excluded by block provenance only -------------------------

def test_page_number_is_excluded_when_its_block_says_page_number():
    blocks = [{"id": "b1", "type": "page_number", "normalizedText": "14", "physicalPageIndex": 14}]
    section = _sec(None, "14", blocks)
    assert section["merged"] == ""
    unit = section["sourceUnits"][0]
    assert unit["disposition"] == "excluded"
    assert unit["blockIds"] == ["b1"] and unit["pages"] == [14]
    _accounted(section)


# --- every unit has a disposition; tables and formulas are counted, not skipped --

def test_learning_only_table_is_held_for_review_not_lost():
    section = _sec("| Góc | Giá trị |\n| --- | --- |\n| 30 | 1 |", "Một câu nguồn đủ dài để so khớp.")
    assert "table_review" in _held_kinds(section)
    assert section["merged"] == "Một câu nguồn đủ dài để so khớp."
    _accounted(section)


def test_learning_only_formula_is_held_with_its_text():
    section = _sec("$W_{d} = \\frac{1}{2}mv^{2}$", "Một câu nguồn đủ dài để so khớp.")
    held = [item for item in section["held"] if item["kind"] == "learning_only"]
    assert held and held[0]["learning"]["text"] == "$W_{d} = \\frac{1}{2}mv^{2}$"
    _accounted(section)


def test_learning_text_contained_in_another_section_is_matched_elsewhere():
    sentence = "Đặc điểm của đoạn mạch nổi tiếp nằm ở đây."
    index = build_block_index({})
    section = merge_section(
        {"id": "a", "heading": "A", "content": sentence},
        {"id": "a", "heading": "A", "content": "Một câu khác của phần này."},
        index,
        lesson_source_flat=" " + norm(sentence) + " ",
    )
    assert section["learningUnits"][0]["disposition"] == "matched_elsewhere"
    _accounted(section)


# --- containment: superseded only when nothing is left over ----------------------

def test_learning_sentence_holding_a_source_sentence_with_extra_words_is_held_on_both_sides():
    section = _sec("Năng lượng gió sạch và có sẵn trong thiên nhiên", "Năng lượng gió sạch")
    assert section["merged"] == ""
    item = [i for i in section["held"] if i["kind"] == "covering_extra"][0]
    assert item["remainder"] == "và có sẵn trong thiên nhiên"
    assert [u["disposition"] for u in section["sourceUnits"]] == ["held"]
    assert [u["disposition"] for u in section["learningUnits"]] == ["held"]
    _accounted(section)


def test_operator_left_over_is_a_decision_not_punctuation():
    section = _sec("U = I + R.", "I + R.")
    assert _held_kinds(section) == ["covering_extra"]
    assert section["merged"] == ""
    assert section["held"][0]["remainder"] == "U ="
    _accounted(section)


def test_leading_minus_sign_is_not_silently_superseded():
    section = _sec("- I + R.", "I + R.")
    assert "superseded" not in [u["disposition"] for u in section["learningUnits"]]
    assert _held_kinds(section) == ["covering_extra"]
    _accounted(section)


def test_number_inside_a_section_block_is_content_even_if_a_page_number_block_has_the_same_digits():
    blocks = [
        {"id": "b1", "type": "text", "normalizedText": "Giá trị 100 đơn vị.", "physicalPageIndex": 5},
        {"id": "b9", "type": "page_number", "normalizedText": "100", "physicalPageIndex": 99},
    ]
    content = "Giá trị 100 đơn vị.\n\n100"
    section = merge_section(None, {"id": "x", "heading": "h", "content": content, "sourceBlockIds": ["b1"]}, build_block_index({"sourceBlocks": blocks}))
    unit = [u for u in section["sourceUnits"] if u["text"] == "100"][0]
    assert unit["disposition"] == "emitted"
    assert unit["provenance"] == "section" and unit["blockIds"] == ["b1"]


def test_number_matching_only_a_page_number_block_outside_the_section_is_held_not_excluded():
    blocks = [
        {"id": "b1", "type": "text", "normalizedText": "Nội dung khác.", "physicalPageIndex": 5},
        {"id": "b9", "type": "page_number", "normalizedText": "100", "physicalPageIndex": 99},
    ]
    section = merge_section(None, {"id": "x", "heading": "h", "content": "100", "sourceBlockIds": ["b1"]}, build_block_index({"sourceBlocks": blocks}))
    assert _held_kinds(section) == ["provenance_review"]
    assert section["sourceUnits"][0]["disposition"] == "held"


def test_held_ids_are_content_derived_and_repeatable():
    first = _sec("U = I + R.", "I + R.")
    second = _sec("U = I + R.", "I + R.")
    assert first["held"][0]["id"] == second["held"][0]["id"]
    assert first["held"][0]["id"].startswith("covering_extra-")


def test_learning_text_with_no_similar_block_says_so_explicitly():
    blocks = [{"id": "b1", "type": "text", "normalizedText": "Hoàn toàn khác về chủ đề quang học.", "physicalPageIndex": 3}]
    section = _sec("Ghi chú của biên tập về điện trở.", "Một câu nguồn khác đủ dài.", blocks)
    learning_item = [i for i in section["held"] if i["learning"] and i["learning"]["text"].startswith("Ghi chú")][0]
    assert learning_item["evidence"]["learning"]["status"] == "none"


def test_learning_sentence_holding_a_source_sentence_with_only_punctuation_extra_is_superseded():
    section = _sec("Năng lượng gió sạch .", "Năng lượng gió sạch")
    assert section["learningUnits"][0]["disposition"] == "superseded"
    assert section["merged"] == "Năng lượng gió sạch"
    assert section["held"] == []
    _accounted(section)


def test_punctuation_only_difference_of_one_word_is_a_held_pair_not_a_silent_match():
    section = _sec("Năng lượng gió sạch.", "Năng lượng gió sạch")
    assert _held_kinds(section) == ["near_pair"]
    assert section["merged"] == ""
    _accounted(section)


def test_learning_fragment_inside_a_longer_source_sentence_is_matched_and_source_is_used():
    section = _sec("Bản bán trụ trong suốt, dùng để đo", "Bản bán trụ trong suốt, dùng để đo góc tới và góc khúc xạ.")
    assert section["merged"] == "Bản bán trụ trong suốt, dùng để đo góc tới và góc khúc xạ."
    assert section["learningUnits"][0]["disposition"] == "matched"
    _accounted(section)


def test_fragment_whose_end_punctuation_differs_is_held_not_matched():
    section = _sec("Bản bán trụ trong suốt.", "Bản bán trụ trong suốt, dùng để đo góc tới và góc khúc xạ.")
    assert _held_kinds(section) == ["learning_only"]
    assert section["merged"] == "Bản bán trụ trong suốt, dùng để đo góc tới và góc khúc xạ."
    _accounted(section)


# --- placeholders and line wraps -------------------------------------------------

def test_placeholder_is_excluded_and_semicolon_does_not_split_it():
    units = split_units("[Hình từ PDF trang 14; cần mô tả thủ công]\n\nCâu nội dung thật của bài học.")
    assert units[0]["placeholderPages"] == [14] and units[0]["text"] == ""
    section = _sec(None, "[Hình từ PDF trang 14; cần mô tả thủ công]\n\nCâu nội dung thật của bài học.")
    assert section["merged"] == "Câu nội dung thật của bài học."
    assert any(u["disposition"] == "excluded" for u in section["sourceUnits"])


def test_single_newline_is_an_ocr_wrap_not_a_sentence_boundary():
    units = split_units("Một viên bị chuyển động đến đập vào\nviên bị khác.")
    assert len(units) == 1


# --- regression: Bài 01 section I (real OCR fixture) ------------------------------

def test_bai01_intro_keeps_the_source_sentence_and_does_not_pair_the_fragment_with_it():
    lesson = json.loads(FIXTURE.read_text(encoding="utf-8"))
    section = build_lesson(lesson)["sections"][0]
    assert SOURCE_SENTENCE in section["merged"]
    fragment = [u for u in section["learningUnits"] if u["text"] == FRAGMENT]
    assert fragment and fragment[0]["disposition"] == "matched"
    assert section["lostSource"] == [] and section["lostLearning"] == []


def test_bai01_intro_traces_the_source_sentence_to_its_block_and_page():
    lesson = json.loads(FIXTURE.read_text(encoding="utf-8"))
    section = build_lesson(lesson)["sections"][0]
    unit = next(u for u in section["sourceUnits"] if u["text"] == SOURCE_SENTENCE)
    assert unit["blockIds"] == ["sgk-khtn9-kntt-tai-ban-2-2026-p0012-b0005"]
    assert unit["pages"] == [12]


# --- preview folder: evidence for every held item and an honest accounting ---------

def test_preview_writes_held_items_with_both_texts_and_block_evidence(tmp_path):
    structured = tmp_path / "structured"
    structured.mkdir()
    lesson = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # One changed word in a sentence that exists in a real source block (b0006, page 12).
    lesson["learningContent"]["sections"][0]["content"] = lesson["learningContent"]["sections"][0]["content"].replace("là:", "la:")
    (structured / "src-lesson-test.json").write_text(json.dumps(lesson, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "preview"
    summary = build_preview(structured, out)
    held = json.loads((out / "held-items.json").read_text(encoding="utf-8"))
    assert summary["lostSource"] == 0 and summary["lostLearning"] == 0
    assert json.loads((out / "losses.json").read_text(encoding="utf-8")) == []
    pair = [h for h in held if h["kind"] == "near_pair"]
    assert pair, "a changed word must be held, not merged"
    assert pair[0]["source"]["text"] == "Mục tiêu của nghiên cứu này là:"
    assert pair[0]["source"]["blockIds"] == ["sgk-khtn9-kntt-tai-ban-2-2026-p0012-b0006"]
    assert pair[0]["source"]["pages"] == [12]
    assert pair[0]["learning"]["text"] == "Mục tiêu của nghiên cứu này la:"
    assert pair[0]["decisionNeeded"]


def test_header_block_is_held_for_review_not_silently_excluded():
    blocks = [{"id": "h1", "type": "header", "normalizedText": "Bài 17", "physicalPageIndex": 17}]
    section = _sec(None, "Bài 17", blocks)
    assert section["merged"] == ""
    assert _held_kinds(section) == ["block_type_review"]
    _accounted(section)


def test_changed_learning_text_carries_candidate_block_evidence():
    index = build_block_index({"sourceBlocks": [{"id": "b1", "type": "text", "normalizedText": "Mục tiêu của nghiên cứu này là:", "physicalPageIndex": 12}]})
    section = merge_section(
        {"id": "x", "heading": "h", "content": "Mục tiêu của nghiên cứu này la:"},
        {"id": "x", "heading": "h", "content": "Mục tiêu của nghiên cứu này là:"},
        index,
    )
    held = section["held"][0]
    assert held["kind"] == "near_pair"
    assert held["source"]["blockIds"] == ["b1"]
    assert held["evidence"]["learning"]["status"] == "candidate"
    assert held["evidence"]["learning"]["candidateBlocks"][0]["blockId"] == "b1"


def _lesson(blocks, content="Một câu nguồn đủ dài."):
    return {"book": {"sha256": "abc"}, "sourceLesson": {"id": "L"}, "sourceBlocks": blocks,
            "learningContent": {"sections": [{"id": "s", "heading": "H", "content": "U = I + R.", "sourceBlockIds": ["b1"]}]},
            "sourceReading": {"sections": [{"id": "s", "heading": "H", "content": "I + R.", "sourceBlockIds": ["b1"]}]}}


def test_duplicate_section_ids_are_rejected_before_merge():
    import pytest
    lesson = _lesson([])
    lesson["sourceReading"]["sections"].append(dict(lesson["sourceReading"]["sections"][0], content="Khác."))
    with pytest.raises(ValueError):
        build_lesson(lesson)


def test_fingerprint_changes_when_block_page_changes_but_held_id_stays():
    a = build_lesson(_lesson([{"id": "b1", "type": "text", "normalizedText": "I + R.", "physicalPageIndex": 1}]))["sections"][0]
    b = build_lesson(_lesson([{"id": "b1", "type": "text", "normalizedText": "I + R.", "physicalPageIndex": 99}]))["sections"][0]
    assert a["held"][0]["id"] == b["held"][0]["id"]
    assert a["held"][0]["fingerprint"] != b["held"][0]["fingerprint"]
