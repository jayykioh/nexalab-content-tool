"""Build an auditable, non-releasable KHTN 9 OLM video mapping inventory.

Title matches are candidates, never human review or a transcript. This script
does not modify canonical lessons, packs, or the database.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


# Playlist indices inspected against the 51 Kết nối tri thức lesson titles.
# Split videos retain playlist order unless a part number supplies a better order.
LESSON_BY_INDEX = {
    1: 2, 3: 3, 4: 4, 7: 6, 8: 5, 9: 5, 11: 39, 12: 7,
    13: 19, 14: 20, 15: 40, 16: 1, 17: 36, 20: 7, 21: 42,
    22: 42, 23: 37, 25: 21, 26: 1, 27: 41, 28: 38,
    29: 44, 30: 40, 31: 23, 32: 22, 33: 24, 34: 11,
    35: 12, 36: 12, 37: 13, 38: 43, 39: 8, 40: 9,
    41: 10, 42: 43, 43: 14, 44: 45, 45: 34, 46: 33,
    47: 15, 48: 8, 49: 35, 50: 18, 51: 17, 52: 16,
    53: 46, 54: 25, 55: 47, 56: 47, 57: 35, 58: 27,
    61: 28, 62: 26, 63: 27, 64: 29, 65: 30, 66: 32,
    67: 32, 68: 31, 69: 48, 70: 26, 71: 50, 72: 49,
    73: 50, 74: 18,
}

EXCLUSION_REASON = {
    2: "Gene là trung tâm của di truyền học: không có bài SGK KNTT cùng phạm vi để gắn tự động",
    5: "Gene là trung tâm của di truyền học: không có bài SGK KNTT cùng phạm vi để gắn tự động",
    6: "Video ẩn/không có tiêu đề, chưa thể xác minh nội dung",
    10: "Video ẩn/không có tiêu đề, chưa thể xác minh nội dung",
    18: "Bài mở đầu thuộc cấu trúc SGK khác; KNTT Bài 1 có phạm vi riêng",
    19: "Bài 1 tên gần giống nhưng khác 'Nhận biết'; cần đối chiếu nội dung trước khi gắn",
    24: "Thực hành quan sát tiêu bản nhiễm sắc thể không phải một bài độc lập trong 51 bài KNTT",
    59: "Playlist ghi 'Xóa'; không có metadata nội dung đáng tin cậy",
    60: "Playlist ghi 'Xóa'; không có metadata nội dung đáng tin cậy",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def part_number(title: str) -> int:
    match = re.search(r"\((?:phần|part)\s*(\d+)\)|\(p(\d+)\)", title, re.I)
    return int(next(group for group in match.groups() if group)) if match else 0


def build(playlist: dict, workspace: Path, baseline: dict | None = None) -> dict:
    canonical_paths = sorted((workspace / "release-prep").glob("bai*/canonical.json"))
    if len(canonical_paths) != 51:
        raise ValueError(f"Expected 51 canonical KHTN9 lessons, found {len(canonical_paths)}")
    lessons = {}
    for path in canonical_paths:
        item = load(path)
        number = int(item["lessonId"].rsplit("-", 1)[1])
        lessons[number] = {
            "lessonId": item["lessonId"],
            "packKey": item["packKey"],
            "title": item["metadata"]["title"],
            "sgkReference": {
                "sourceLessonId": item["metadata"].get("sourceLessonId"),
                "sourceLessonTitle": item["metadata"].get("sourceLessonTitle"),
                "pdfPageRange": item["metadata"].get("pdfPageRange"),
                "printedPageRange": item["metadata"].get("printedPageRange"),
            },
            "videos": [],
        }
    # The DB snapshot is lesson-shaped.  Flatten both lesson and section video
    # lists so an existing DB video retains its immutable ID, reviewed text and
    # recorded review status when its provider ID recurs in the OLM playlist.
    prior_by_provider_id = {}
    if baseline:
        for lesson in baseline.get("lessons", []):
            candidates = list(lesson.get("videos") or [])
            for section in lesson.get("sections") or []:
                candidates.extend(section.get("videos") or [])
            for item in candidates:
                # Legacy baseline objects predate providerVideoId.  Their
                # canonical YouTube URL is sufficient to preserve the stable
                # authored ID, but not evidence that the old transcript text
                # was a genuine transcript.
                provider_id = item.get("providerVideoId") or item.get("videoId")
                if not provider_id:
                    match = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{6,})", item.get("url", ""))
                    provider_id = match.group(1) if match else None
                if provider_id:
                    prior_by_provider_id[provider_id] = item
    excluded = []
    for entry in playlist["entries"]:
        index = entry["playlistIndex"]
        if index in EXCLUSION_REASON:
            excluded.append({"playlistIndex": index, "videoId": entry["videoId"], "title": entry["title"], "reason": EXCLUSION_REASON[index]})
            continue
        if index not in LESSON_BY_INDEX:
            raise ValueError(f"Unclassified playlist index: {index}")
        provider_id = entry["videoId"]
        prior = prior_by_provider_id.get(provider_id, {})
        video = {
            "id": prior.get("id") or f"olm-{provider_id.lower()}",
            "title": entry["title"],
            "url": f"https://www.youtube.com/watch?v={provider_id}",
            "provider": "YOUTUBE",
            "providerVideoId": provider_id,
            "durationSec": entry.get("durationSec"),
            # Never recirculate an old title-derived placeholder as a real
            # transcript.  The raw baseline remains in the separate read-only
            # snapshot for audit and may be restored only after human review.
            "transcript": entry.get("transcript"),
            "captionStatus": entry.get("captionStatus", "NOT_CHECKED"),
            "completionThresholdPercent": 90,
            "reviewStatus": prior.get("reviewStatus") if prior.get("reviewStatus") in {"REVIEWED", "NEEDS_REVIEW", "REJECTED"} else "NEEDS_REVIEW",
            "provenance": {
                "sourceUrl": playlist["sourceUrl"],
                "sourceLabel": "OLM KHTN 9 playlist",
                "checkedAt": playlist["checkedAt"],
                "availability": entry.get("availability", "UNKNOWN"),
                "rightsStatus": "NEEDS_REVIEW",
                "accessibilityStatus": "NEEDS_REVIEW",
            },
            "mappingStatus": "TITLE_MATCH_PENDING_CONTENT_REVIEW",
            "playlistIndex": index,
            "baselineDbVideoId": prior.get("id"),
            "baselineTranscriptStatus": "UNVERIFIED_LEGACY_TEXT_NOT_REUSED" if prior.get("transcript") else None,
        }
        lessons[LESSON_BY_INDEX[index]]["videos"].append(video)
    for lesson in lessons.values():
        lesson["videos"].sort(key=lambda item: (part_number(item["title"]) or 999, item["playlistIndex"]))
    mapping = list(lessons.values())
    return {
        "schemaVersion": 1,
        "kind": "full-p2-video-mapping-inventory",
        "subject": "khtn9",
        "status": "PENDING_HUMAN_VIDEO_AND_RIGHTS_REVIEW_NOT_RELEASABLE",
        "playlistId": playlist["playlistId"],
        "sourceUrl": playlist["sourceUrl"],
        "checkedAt": playlist["checkedAt"],
        "counts": {
            "playlistEntries": len(playlist["entries"]),
            "mappedVideos": sum(len(item["videos"]) for item in mapping),
            "lessonsWithVideos": sum(bool(item["videos"]) for item in mapping),
            "lessonsTotal": len(mapping),
            "excludedVideos": len(excluded),
            "lessonsWithoutVideos": sum(not item["videos"] for item in mapping),
            "baselineVideosPreserved": sum(bool(video["baselineDbVideoId"]) for lesson in mapping for video in lesson["videos"]),
        },
        "lessons": mapping,
        "excluded": excluded,
        "lessonsWithoutVideos": [{"lessonId": item["lessonId"], "title": item["title"]} for item in mapping if not item["videos"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(load(args.playlist), args.workspace, load(args.baseline) if args.baseline and args.baseline.exists() else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
