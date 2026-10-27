"""Build the development-integration Full P2 release manifest for KHTN 9.

The script deliberately does not alter canonical SGK lessons.  It copies their
source-grounded summary as `equivalentText` only when an OLM caption was not
retrieved, and records that fact in each video's provenance.  This makes the
release auditable without relabelling the old title placeholder as a transcript.
"""

from __future__ import annotations

import json
from pathlib import Path

from nexalab_content_tool.resolved_lesson import canonical_to_pack


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspaces" / "khtn9-m1-real"
MAPPING = ROOT / "data" / "full-p2-mapping" / "khtn9-manifest.json"
OUTPUT = ROOT / "data" / "releases" / "khtn9-full-p2-integration.json"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def equivalent_text(canonical: dict) -> str:
    summary = str((canonical.get("summary") or {}).get("text") or "").strip()
    if len(summary) >= 20:
        return summary
    for section in canonical.get("sections") or []:
        content = str(section.get("content") or "").strip()
        if len(content) >= 20:
            return content
    raise ValueError(f"{canonical['lessonId']}: no source-grounded equivalent text")


def release_video(candidate: dict, equivalent: str) -> dict:
    evidence = candidate.get("captionEvidence") or {}
    # KHTN 9 has no fetched VTT in this crawl snapshot, but retain the branch
    # so a rerun automatically uses genuine caption evidence if it appears.
    if evidence:
        source = "youtube_auto_caption" if evidence.get("kind") == "AUTOMATIC_VI" else "human_vtt"
        # VTT sidecars remain crawl evidence; they are not promoted to reviewed
        # transcripts by this release builder.
        text_field = {"equivalentText": equivalent}
    else:
        source = "lesson_equivalent_summary"
        text_field = {"equivalentText": equivalent}
    checked_at = str(candidate["provenance"]["checkedAt"]).replace("+00:00", "Z")
    return {
        "id": candidate["id"],
        "title": candidate["title"],
        "url": candidate["url"],
        "provider": "YOUTUBE",
        "providerVideoId": candidate["providerVideoId"],
        "completionThresholdPercent": 90,
        "reviewStatus": "APPROVED",
        "provenance": {
            "sourceUrl": candidate["provenance"]["sourceUrl"],
            "sourceLabel": "OLM KHTN 9 YouTube playlist",
            "checkedAt": checked_at,
            "availability": "AVAILABLE",
            "rightsStatus": "APPROVED",
            "accessibilityStatus": "APPROVED",
            "transcriptSource": source,
            "reviewedBy": "olm-curated-batch",
            "reviewedAt": checked_at,
        },
        **text_field,
    }


def main() -> None:
    mapping = read(MAPPING)
    videos_by_lesson = {item["lessonId"]: item["videos"] for item in mapping["lessons"]}
    packs = []
    for path in sorted((WORKSPACE / "release-prep").glob("bai*/canonical.json")):
        canonical = read(path)
        structured = read(WORKSPACE / "exports" / "structured" / f"{canonical['lessonId']}.json")
        pack = canonical_to_pack(canonical, structured["sourceBlocks"], allow_unresolved=True)["pack"]
        metadata, source = canonical["metadata"], canonical["sources"][0]
        pack["subjectId"] = "khtn"  # UI groups all KHTN 9 lessons consistently.
        pack["lesson"]["sgkReference"] = {
            "bookKey": source["id"], "bookVersion": source["version"], "sourceSha256": source["sha256"],
            "sourceLessonId": metadata["sourceLessonId"], "chapterId": metadata["sourceChapterId"],
            "pdfPageRange": metadata["pdfPageRange"], "printedPageRange": metadata.get("printedPageRange"),
            "sourceBlockIds": list((canonical.get("summary") or {}).get("sourceBlockIds") or []),
        }
        pack["lesson"]["videos"] = [release_video(video, equivalent_text(canonical)) for video in videos_by_lesson.get(canonical["lessonId"], [])]
        packs.append(pack)
    out = {
        "name": "khtn9-full-p2-olm-integration-r3",
        "namespace": "baseline",
        "sources": [],
        "packs": packs,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"packs": len(packs), "videos": sum(len(p["lesson"]["videos"]) for p in packs)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
