"""Upgrade the local KHTN 9 preview artifacts to the Full P2 video contract.

This is intentionally a local-data migration. It does not approve content, publish a
pack, or write to the backend. Existing title-only "transcripts" are removed because
they are not reviewed transcripts or equivalent learning text.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nexalab_content_tool.m1_workflow import validate_video_mapping
from nexalab_content_tool.resolved_lesson import _digest, canonical_to_pack


PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLDHr_ecbSve4L1v52dd02aQzOwaTj-d74"
CHECKED_AT = "2026-10-25T00:00:00Z"
PLACEHOLDER_PREFIX = "video olm minh họa nội dung:"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def youtube_id(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower().removeprefix("www.") == "youtu.be":
        return parsed.path.strip("/").split("/")[0]
    return (parse_qs(parsed.query).get("v") or [""])[0]


def upgrade_video(video: dict) -> dict:
    upgraded = dict(video)
    upgraded.update({
        "provider": "YOUTUBE",
        "providerVideoId": youtube_id(str(video.get("url", ""))),
        "completionThresholdPercent": 90,
        "reviewStatus": "PENDING_REVIEW",
        "provenance": {
            "sourceUrl": PLAYLIST_URL,
            "sourceLabel": "OLM KHTN 9 playlist",
            "checkedAt": CHECKED_AT,
            "availability": "AVAILABLE",
            "rightsStatus": "UNKNOWN_BLOCK_PUBLIC_RELEASE",
            "accessibilityStatus": "TRANSCRIPT_OR_CAPTION_NOT_REVIEWED",
            "operatorDecision": "TITLE_MATCH_PENDING_HUMAN_REVIEW",
        },
    })
    transcript = str(upgraded.get("transcript", "")).strip().lower()
    if transcript.startswith(PLACEHOLDER_PREFIX):
        upgraded.pop("transcript", None)
    return validate_video_mapping([upgraded])[0]


def compact_reference(canonical: dict, structured: dict) -> None:
    source_lesson = structured.get("sourceLesson") or {}
    chapter = structured.get("chapter") or {}
    metadata = canonical.setdefault("metadata", {})
    metadata.update({
        "sourceLessonId": source_lesson.get("id"),
        "sourceLessonTitle": source_lesson.get("title"),
        "sourceChapterId": chapter.get("id"),
        "pdfPageRange": structured.get("pdfPageRange"),
        "printedPageRange": structured.get("printedPageRange"),
    })


def migrate(root: Path) -> dict:
    structured_dir = root / "exports" / "structured"
    packs, upgraded_videos, upgraded_lessons, missing = [], 0, 0, []
    canonical_paths = sorted((root / "release-prep").glob("bai*/canonical.json"))
    for canonical_path in canonical_paths:
        canonical = read_json(canonical_path)
        lesson_id = str(canonical.get("lessonId", ""))
        structured_path = structured_dir / f"{lesson_id}.json"
        if not structured_path.exists():
            missing.append(lesson_id or canonical_path.parent.name)
            continue
        compact_reference(canonical, read_json(structured_path))
        videos = [upgrade_video(video) for video in canonical.get("videos", [])]
        if videos:
            canonical["videos"] = videos
            upgraded_videos += len(videos)
            upgraded_lessons += 1
        canonical["contentHash"] = _digest({key: value for key, value in canonical.items() if key != "contentHash"})
        write_json(canonical_path, canonical)
        source_blocks = read_json(structured_path).get("sourceBlocks", [])
        packs.append(canonical_to_pack(canonical, source_blocks, allow_unresolved=True)["pack"])

    output = {
        "name": "khtn9-full-p2-preview-not-releasable",
        "namespace": "baseline",
        "sources": [],
        "packs": packs,
        "_status": "PREVIEW_ONLY_PENDING_VIDEO_AND_RELEASE_REVIEW",
        "_counts": {
            "lessons": len(packs),
            "videoLessons": upgraded_lessons,
            "videos": upgraded_videos,
            "missingStructuredLessons": len(missing),
        },
        "_missingStructuredLessonIds": missing,
    }
    write_json(root / "exports" / "full-p2" / "khtn9-full-p2-preview.json", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    result = migrate(args.workspace.resolve())
    print(json.dumps(result["_counts"], ensure_ascii=False))
    return 0 if not result["_missingStructuredLessonIds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
