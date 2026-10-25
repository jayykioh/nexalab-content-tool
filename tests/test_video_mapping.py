from __future__ import annotations

from nexalab_content_tool.m1_workflow import validate_video_mapping


def test_video_mapping_accepts_lesson_and_section_metadata_without_ocr_fields():
    lesson = validate_video_mapping([{"id": "video-01", "title": "Động năng", "url": "https://www.youtube.com/watch?v=abc123", "transcript": "Năng lượng của vật do chuyển động."}])
    section = validate_video_mapping([{"id": "video-02", "title": "Thế năng", "url": "https://cdn.example.org/lesson.mp4", "captionUrl": "https://cdn.example.org/lesson.vtt"}])
    assert lesson[0]["id"] == "video-01"
    assert section[0]["captionUrl"].endswith(".vtt")


def test_video_mapping_rejects_invalid_url_or_missing_stable_id():
    import pytest
    with pytest.raises(Exception):
        validate_video_mapping([{"id": "video-01", "title": "x", "url": "http://example.org/x.mp4"}])
    with pytest.raises(Exception):
        validate_video_mapping([{"title": "x", "url": "https://www.youtube.com/watch?v=abc123"}])


def test_video_mapping_is_optional_for_legacy_lessons():
    assert validate_video_mapping([]) == []


def test_video_mapping_metadata_is_small_and_deterministic():
    item = {"id": "video-01", "title": "Video", "url": "https://www.youtube.com/watch?v=abc123", "transcript": "Tóm tắt."}
    assert validate_video_mapping([item]) == validate_video_mapping([dict(item)])
