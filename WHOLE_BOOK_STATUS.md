# KHTN 8 whole-book processing status

Updated: 2026-10-23
Workspace: `workspaces/m1-khtn8-acceptance`
Source: `.local/books/sgk-khtn8/source.pdf` (200 PDF pages)

## Current state

- TOC-first map contains 47 Lesson ranges across the unassigned opening lesson and Chapters I–VIII. Only Chapter VI ranges are human-confirmed; other TOC-derived Lesson ranges remain proposals.
- OCR is intentionally paused for local, chapter-by-chapter continuation. The saved checkpoint is resumable; do not start a fresh full-book rerun.
- Current local page records: 180 total, including 173 of 189 mapped Lesson pages. All 180 recorded pages currently have at least 50 text characters.
- 16 mapped pages remain without page records: PDF 161–171 and 192–196. The corresponding Lessons remain incomplete/unreviewed until these ranges are processed.
- 100 saved manual OCR edit entries remain in the page records. Existing Chapter VI JSON edits and authored lesson content must be preserved.
- The book has 11 unmapped pages (PDF 1–7 and 197–200); these are outside Lesson ranges and are not OCR blockers for Lesson coverage.
- The earlier batch run recorded transient failures from MinerU batch/model/temp-file errors. Do not treat those stale per-Lesson errors as final page status: refresh checkpoint status after processing the missing ranges.

## Suggested local continuation

Run the existing script from this repository and select the affected chapter/range in the Local UI:

```powershell
.\run-studio.ps1
```

Resume Chapter VII at PDF 161–171, then Chapter VIII at PDF 192–196. Review OCR/source pages in the UI before content acceptance. After the missing pages are recorded, refresh Structured Lesson outputs and validate provenance. Do not mark local content accepted without a human review, or treat local acceptance as BE release approval.

## Outputs and gates

The current pipeline writes page checkpoints under `.local/books/sgk-khtn8/pages/`, Structured Lesson candidates under `exports/structured/`, the whole-book report under `reports/`, and BE candidate/blocker artifacts under `exports/`. Refresh those outputs after the two remaining ranges are processed. Curriculum mapping, rights, and formal human release reviews remain unresolved unless separately evidenced.
