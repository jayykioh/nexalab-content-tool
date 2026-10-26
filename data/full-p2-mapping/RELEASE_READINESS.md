# Full P2 OLM mapping — release-readiness snapshot

This directory is an auditable **candidate inventory**, not a released pack.
It is generated from the official OLM playlists and read-only DB snapshots.

| Scope | Playlist entries | Candidate mappings | Lessons with video | Not mapped to a lesson | Release state |
| --- | ---: | ---: | ---: | ---: | --- |
| KHTN 9 | 74 | 65 | 50/51 | 9 | Blocked pending review and real transcript/equivalent text |
| KHTN 8 | 83 visible playlist entries | 76 | 44/47 | 7 in review queue | Blocked pending complete Structured JSON/SGK references and review |

The canonical per-video provenance, canonical watch URLs, duration, review
status and mapping decision are in `khtn9-manifest.json` and
`khtn8-canonical-video-manifest.json`.  `khtn9-manifest.json` also records the
9 excluded OLM videos and the one KHTN 9 lesson without a candidate.  The KHTN
8 manifest records all 7 queue items and its three lessons without a candidate.

## Evidence and DB safety

- The KHTN 9 database snapshot contains 51 lessons and 18 existing videos. All
  18 stable authored IDs are preserved in the KHTN 9 candidate inventory.
  Legacy title-derived text is retained only in the read-only snapshot and is
  explicitly not reused as a transcript.
- The KHTN 8 snapshot contains 98 lessons. No deletion or update is performed.
- 26 mapped KHTN 8 videos have a fetched automatic-Vietnamese VTT evidence
  sidecar. Those sidecars are not claimed to be reviewed transcripts.
- The active PostgreSQL schema is missing `Lesson.sgkReference`; migration
  `20261026150000_full_p2_video_evidence` is present in source but unapplied.
  No DB release is safe until it is applied and the candidate videos pass
  content, rights and accessibility review.

## Reproduce

1. Run `scripts/crawl_olm_playlists.py` with the project virtual environment.
2. Run `scripts/audit_full_p2_db.cjs` for a fresh read-only baseline.
3. Run `scripts/build_khtn9_olm_mapping.py` with the baseline and canonical
   KHTN 9 workspace, then run `scripts/map_khtn8_olm.py`.

No commit or push has been made for these artifacts.
