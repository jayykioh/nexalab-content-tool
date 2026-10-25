from __future__ import annotations

import argparse, json, re, unicodedata
from pathlib import Path
from nexalab_content_tool.resolved_lesson import canonical_to_pack, load_structured

PLAYLIST = "PLDHr_ecbSve4L1v52dd02aQzOwaTj-d74"
SUFFIX = re.compile(r"\s*-\s*(?:khoa học tự nhiên|khtn|natural science)\s*9\s*-\s*olm\.vn\s*$", re.I)
PART = re.compile(r"\s*\((?:phần|part|tiết)\s*[12]\)\s*$", re.I)

def norm(value: str) -> str:
    value = value.lower().strip()
    value = SUFFIX.sub("", value).strip()
    value = PART.sub("", value).strip()
    value = unicodedata.normalize("NFD", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = PART.sub("", value).strip()
    value = SUFFIX.sub("", value).strip()
    value = re.sub(r"^bai\s*(?:mo dau|\d+)\.?\s*[-.:]?\s*", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("workspace", type=Path)
    p.add_argument("playlist_json", type=Path)
    p.add_argument("--manifest", type=Path, required=True)
    args = p.parse_args()
    playlist = json.loads(args.playlist_json.read_text(encoding="utf-8-sig"))
    videos = [{"id": e["id"], "title": e.get("title") or "", "url": f"https://www.youtube.com/watch?v={e['id']}", "transcript": f"Video OLM minh họa nội dung: {e.get('title') or 'bài học Khoa học tự nhiên 9'}."} for e in playlist.get("entries", []) if e.get("id") and e.get("title") and e.get("title") not in {"Xóa"}]
    lessons = []
    for folder in sorted((args.workspace / "release-prep").glob("bai[0-9][0-9]")):
        canonical_path = folder / "canonical.json"
        if not canonical_path.exists(): continue
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        lessons.append((folder, canonical, norm(canonical["metadata"]["title"])))
    matched: dict[str, list[dict]] = {}
    for video in videos:
        key = norm(video["title"])
        candidates = [(folder, canonical, title_key) for folder, canonical, title_key in lessons if key == title_key]
        if len(candidates) == 1:
            folder, canonical, _ = candidates[0]
            video_id = video["id"].lower()
            existing = [v for v in canonical.get("videos", []) if v.get("id") != f"olm-{video_id}" and video["id"] not in str(v.get("url", ""))]
            canonical["videos"] = existing + [{**video, "id": f"olm-{video_id}"}]
            canonical["videos"].sort(key=lambda item: next((i for i, x in enumerate(videos) if x["id"] == item["url"].split("v=", 1)[-1]), 9999))
            canonical_path = folder / "canonical.json"
            canonical_path.write_text(json.dumps(canonical, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            matched.setdefault(canonical["packKey"], []).append(video)
    packs = []
    for folder, canonical, _ in lessons:
        if canonical["packKey"] not in matched: continue
        structured_path, structured = load_structured(args.workspace, canonical["lessonId"])
        packs.append(canonical_to_pack(canonical, structured["sourceBlocks"])["pack"])
    args.manifest.write_text(json.dumps({"name": "khtn9-olm-video-mapping", "namespace": "baseline", "sources": [], "packs": packs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"playlistEntries": len(videos), "matchedLessons": len(matched), "matchedVideos": sum(map(len, matched.values())), "mapping": matched}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
