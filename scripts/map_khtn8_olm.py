"""Build a reviewable KHTN 8 OLM video manifest from verified crawl metadata.

The index mapping below was checked against the 47 KHTN 8 curriculum topics.
It is deliberately conservative: unavailable, unrelated, duplicate, and
supplemental videos stay in the review queue. No human approval is inferred.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRAWL = ROOT / "data" / "full-p2-crawl" / "khtn8-playlist.json"
REGISTRY = ROOT / "catalog-registry.json"
OUTPUT = ROOT / "data" / "full-p2-mapping" / "khtn8-canonical-video-manifest.json"

LESSON_VIDEO_INDEXES = {
    2: [7, 82], 3: [12, 13], 4: [14, 15], 5: [16, 17], 6: [44],
    7: [20], 8: [21], 9: [81, 22], 10: [23, 24], 11: [26, 32],
    12: [33], 13: [2], 14: [3], 15: [4], 16: [5, 8], 17: [10, 83],
    18: [25, 27], 19: [28, 29], 20: [30, 31], 21: [46], 22: [47],
    23: [80], 24: [53], 26: [55, 56], 28: [65, 66, 67], 29: [75, 73],
    30: [9], 31: [11], 32: [18, 35, 36], 33: [37, 38, 39],
    34: [42, 43], 35: [40, 41], 36: [45], 37: [48, 49, 50],
    38: [51, 52], 39: [57, 59], 40: [58, 60, 62], 41: [63, 64],
    42: [68, 69], 43: [70], 44: [71, 72], 45: [74], 46: [78],
    47: [76, 77],
}

# Exact title alone cannot settle these distinctions or add a new SGK lesson.
REVIEW_QUEUE = {
    1: ("UNAVAILABLE", None, "YouTube hides the title and metadata."),
    6: ("RELATED_SUBTOPIC", 2, "Physical versus chemical change is related to Lesson 2; verify the relevant SGK section."),
    19: ("UNAVAILABLE", None, "YouTube hides the title and metadata."),
    34: ("SUPPLEMENTAL_PRACTICAL", 31, "First aid for fracture is related to the musculoskeletal lesson; verify section placement."),
    54: ("DUPLICATE_PART_CANDIDATE", 3, "Another Part 1 for moles and gas density is already mapped; compare contents before attaching both."),
    61: ("OUT_OF_SCOPE", None, "Vietnamese language grade 4 video is unrelated to KHTN 8."),
    79: ("SUPPLEMENTAL_PRACTICAL", 33, "Blood and circulation practical needs verified section placement."),
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _part(title: str) -> int:
    match = re.search(r"(?:phần|part)\s*(\d+)", title, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _video(entry: dict, source: dict) -> dict:
    video_id = entry["videoId"]
    video = {
        "id": f"olm-{video_id.lower()}",
        "title": entry["title"],
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "provider": "YOUTUBE",
        "providerVideoId": video_id,
        "durationSec": entry.get("durationSec"),
        "completionThresholdPercent": 90,
        "reviewStatus": "NEEDS_REVIEW",
        "provenance": {
            "sourceUrl": source["sourceUrl"],
            "sourceLabel": "OLM KHTN 8 YouTube playlist",
            "playlistIndex": entry["playlistIndex"],
            "checkedAt": source["checkedAt"],
            "availability": "AVAILABLE",
            "rightsStatus": "NEEDS_REVIEW",
            "accessibilityStatus": "NEEDS_REVIEW",
            "operatorDecision": "TITLE_MATCH_PENDING_HUMAN_REVIEW",
        },
    }
    # Captions fetched from YouTube are evidence, not a reviewed transcript.
    # Keep the VTT reference explicit; do not turn automatic captions or a
    # title-derived summary into the `transcript` field required for release.
    if entry.get("captionPath"):
        video["captionEvidence"] = {
            "kind": entry.get("captionStatus"),
            "path": entry["captionPath"],
            "characters": entry.get("captionCharacters"),
        }
    return video


def build() -> dict:
    crawl, registry = _json(CRAWL), _json(REGISTRY)
    entries = {item["playlistIndex"]: item for item in crawl["entries"]}
    topics = {int(item["code"].split("L")[-1]): item for item in registry["topics"] if item["code"].startswith("KHTN8-L")}
    if len(topics) != 47 or set(topics) != set(range(1, 48)):
        raise ValueError("KHTN 8 registry must contain 47 consecutive lessons")
    if len(entries) != len(crawl["entries"]):
        raise ValueError("Duplicate playlist index")
    mapped = [index for indexes in LESSON_VIDEO_INDEXES.values() for index in indexes]
    if len(mapped) != len(set(mapped)):
        raise ValueError("A playlist entry cannot be mapped to multiple lessons")
    if set(mapped) & set(REVIEW_QUEUE) or set(mapped) | set(REVIEW_QUEUE) != set(entries):
        raise ValueError("Every playlist entry must be mapped or placed in the review queue exactly once")
    lessons = []
    for number in range(1, 48):
        topic = topics[number]
        indexes = sorted(LESSON_VIDEO_INDEXES.get(number, []), key=lambda i: (_part(entries[i]["title"]), i))
        lessons.append({
            "lessonCode": topic["code"],
            "lessonTitle": topic["title"],
            "chapterCode": topic["chapterCode"],
            "sgkReference": None,
            "structuredJsonStatus": "NOT_PRESENT_IN_AVAILABLE_WORKSPACE",
            "videos": [_video(entries[index], crawl) for index in indexes],
            "mappingReviewStatus": "NEEDS_REVIEW" if indexes else "NO_VIDEO_MATCH",
        })
    queue = [{"playlistIndex": index, "videoId": entries[index]["videoId"], "title": entries[index]["title"],
              "reasonCode": reason, "candidateLessonCode": f"KHTN8-L{lesson:02d}" if lesson else None,
              "reason": detail} for index, (reason, lesson, detail) in sorted(REVIEW_QUEUE.items())]
    return {
        "schemaVersion": 1,
        "kind": "khtn8-full-p2-canonical-video-mapping-candidate",
        "releaseReady": False,
        "playlistId": crawl["playlistId"],
        "sourceUrl": crawl["sourceUrl"],
        "checkedAt": crawl["checkedAt"],
        "sourceLessonRegistry": "catalog-registry.json",
        "counts": {"playlistEntries": len(entries), "mappedVideos": len(mapped),
                   "lessonsWithVideos": sum(bool(item["videos"]) for item in lessons),
                   "lessonsWithoutVideos": sum(not item["videos"] for item in lessons),
                   "reviewQueue": len(queue)},
        "lessons": lessons,
        "reviewQueue": queue,
        "releaseBlockers": ["KHTN 8 Structured JSON and verified SGK page references are incomplete in the available workspace.",
                            "Video title mapping, rights, accessibility and transcript availability require human review."],
    }


def main() -> None:
    result = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
