"""Capture OLM playlist metadata without inventing unavailable captions.

Run with the project's virtual environment. Outputs are review inputs, not release packs.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp


PLAYLISTS = {
    "khtn8": "PLDHr_ecbSve6YcMWpMnRDPcTxtkR6YPMB",
    "khtn9": "PLDHr_ecbSve4L1v52dd02aQzOwaTj-d74",
}


def crawl(name: str, playlist_id: str, output: Path) -> dict:
    with yt_dlp.YoutubeDL({"extract_flat": "in_playlist", "skip_download": True, "quiet": True, "no_warnings": False}) as ydl:
        playlist = ydl.extract_info(f"https://www.youtube.com/playlist?list={playlist_id}", download=False)
    entries = []
    for index, item in enumerate(playlist.get("entries") or [], 1):
        if not item:
            entries.append({"playlistIndex": index, "videoId": None, "title": None, "url": None,
                            "durationSec": None, "transcript": None, "captionStatus": "UNAVAILABLE"})
            continue
        video_id = item.get("id")
        entries.append({
            "playlistIndex": item.get("playlist_index") or index,
            "videoId": video_id,
            "title": item.get("title"),
            "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
            "durationSec": item.get("duration"),
            "transcript": None,
            "captionStatus": "NOT_CHECKED",
            "availability": item.get("availability") or ("UNAVAILABLE" if not item.get("title") else "UNKNOWN"),
        })
    result = {
        "schemaVersion": 1,
        "kind": "olm-playlist-crawl",
        "subject": name,
        "playlistId": playlist_id,
        "sourceUrl": f"https://www.youtube.com/playlist?list={playlist_id}",
        "playlistTitle": playlist.get("title"),
        "channel": playlist.get("channel") or playlist.get("uploader"),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "reportedEntryCount": playlist.get("playlist_count") or len(entries),
        "entries": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def enrich_captions(path: Path) -> None:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    caption_dir = path.parent / "captions" / artifact["subject"]
    caption_dir.mkdir(parents=True, exist_ok=True)
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True,
                           "ignoreerrors": True, "no_warnings": True}) as ydl:
        for entry in artifact["entries"]:
            if entry.get("captionStatus") != "NOT_CHECKED" or not entry.get("videoId"):
                continue
            try:
                info = ydl.extract_info(entry["url"], download=False)
                if not info:
                    entry["captionStatus"] = "VIDEO_UNAVAILABLE"
                    continue
                entry["title"] = info.get("title") or entry["title"]
                entry["durationSec"] = info.get("duration") or entry["durationSec"]
                subtitles = info.get("subtitles") or {}
                automatic = info.get("automatic_captions") or {}
                tracks = subtitles.get("vi") or subtitles.get("vi-orig")
                kind = "MANUAL_VI" if tracks else None
                if not tracks:
                    tracks = automatic.get("vi-orig") or automatic.get("vi")
                    kind = "AUTOMATIC_VI" if tracks else None
                selected = next((item for item in tracks or [] if item.get("ext") == "vtt"), None)
                if not selected:
                    entry["captionStatus"] = "NO_VI_CAPTION"
                else:
                    response = urllib.request.urlopen(selected["url"], timeout=30)
                    vtt = response.read().decode("utf-8-sig", errors="replace")
                    if not vtt.startswith("WEBVTT") or len(vtt) < 100:
                        entry["captionStatus"] = "CAPTION_EMPTY"
                    else:
                        destination = caption_dir / f"{entry['videoId']}.vi.vtt"
                        destination.write_text(vtt, encoding="utf-8")
                        # VTT is the authoritative transcript artifact. Keep JSON compact.
                        entry["captionStatus"] = kind
                        entry["captionPath"] = str(destination.relative_to(path.parent)).replace("\\", "/")
                        entry["captionCharacters"] = len(vtt)
            except Exception as exc:
                entry["captionStatus"] = "FETCH_FAILED"
                entry["captionError"] = str(exc)[:200]
            path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(artifact["subject"], entry["playlistIndex"], entry["videoId"], entry["captionStatus"], flush=True)
            time.sleep(0.15)


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "data" / "full-p2-crawl"
    if len(sys.argv) > 1 and sys.argv[1] == "--enrich":
        subjects = sys.argv[2:] or list(PLAYLISTS)
        for subject in subjects:
            enrich_captions(destination / f"{subject}-playlist.json")
    else:
        for subject, identifier in PLAYLISTS.items():
            artifact = crawl(subject, identifier, destination / f"{subject}-playlist.json")
            print(subject, len(artifact["entries"]), "entries")
