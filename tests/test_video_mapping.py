from __future__ import annotations

from nexalab_content_tool.m1_workflow import validate_video_mapping

PROVENANCE = {"sourceUrl": "https://www.youtube.com/playlist?list=source", "sourceLabel": "OLM playlist", "checkedAt": "2026-10-26T00:00:00Z", "availability": "AVAILABLE"}


def video(**changes):
    value = {"id": "video-01", "title": "Động năng", "url": "https://www.youtube.com/watch?v=abc123", "provider": "YOUTUBE", "providerVideoId": "abc123", "transcript": "Năng lượng của vật do chuyển động.", "reviewStatus": "APPROVED", "provenance": PROVENANCE}
    value.update(changes)
    return value


def test_video_mapping_accepts_lesson_and_section_metadata_without_ocr_fields():
    lesson = validate_video_mapping([video()])
    section = validate_video_mapping([video(id="video-02", title="Thế năng", url="https://cdn.example.org/lesson.mp4", provider="DIRECT", providerVideoId="lesson-mp4", transcript=None, captionUrl="https://cdn.example.org/lesson.vtt")])
    assert lesson[0]["id"] == "video-01"
    assert lesson[0]["completionThresholdPercent"] == 90
    assert lesson[0]["providerVideoId"] == "abc123"
    assert section[0]["captionUrl"].endswith(".vtt")


def test_video_mapping_rejects_invalid_url_or_missing_stable_id():
    import pytest
    with pytest.raises(Exception):
        validate_video_mapping([video(url="http://example.org/x.mp4")])
    with pytest.raises(Exception):
        validate_video_mapping([video(id=None)])


def test_video_mapping_is_optional_for_legacy_lessons():
    assert validate_video_mapping([]) == []


def test_video_mapping_metadata_is_small_and_deterministic():
    item = video(title="Video", transcript="Tóm tắt.")
    assert validate_video_mapping([item]) == validate_video_mapping([dict(item)])


def test_video_mapping_rejects_provider_mismatch_duplicate_and_placeholder_transcript():
    import pytest
    with pytest.raises(Exception, match="same video"):
        validate_video_mapping([video(providerVideoId="different")])
    with pytest.raises(Exception, match="Duplicate video ID"):
        validate_video_mapping([video(), video()])
    with pytest.raises(Exception, match="placeholder"):
        validate_video_mapping([video(transcript="Video minh họa nội dung.")])


def test_video_mapping_preserves_review_and_provenance_metadata():
    value = validate_video_mapping([video(completionThresholdPercent=95)])[0]
    assert value["reviewStatus"] == "APPROVED"
    assert value["completionThresholdPercent"] == 95
    assert value["provenance"] == PROVENANCE
