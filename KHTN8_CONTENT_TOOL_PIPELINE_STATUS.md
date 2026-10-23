# NexaLab Content Tool — pipeline status (KHTN 8)

Updated: 2026-10-23  
Repository branch: `codex/m2b-full-validation`  
Workspace: `workspaces/m1-khtn8-acceptance`  
Source: `.local/books/sgk-khtn8/source.pdf`, 200 PDF pages, SHA-256 `6dcda104a5b09d1395417afef9ac48630843e57dc53938412eada13a6fdfdbf1`.

## Executive status

The local pipeline and review/export UI are implemented and focused workflow tests pass. The KHTN 8 book run is **not complete**: OCR is paused for local, chapter-by-chapter continuation. The saved page records cover 173/189 mapped Lesson pages, while 16 mapped pages are still missing. The report/checkpoint files have not been regenerated since the last per-page retry, so their old per-Lesson error summaries are stale. Only four Chapter VI Structured Lesson JSONs exist; they remain `needs_review`. No Lesson has local human content acceptance, and no BE release approval is represented.

| Pipeline stage | Current status | Evidence / limit |
|---|---|---|
| Source import and local processing setup | Done for this workspace | 200-page PDF is stored locally and hash-bound. This records local processing setup; it does not establish publication rights. |
| TOC → Chapter → Lesson map | Present, partly confirmed | 47 Lessons across the opening unassigned Lesson and Chapters I–VIII. Ch VI’s 4 ranges are confirmed; the other 43 remain proposed. 189 mapped Lesson pages; 11 unmapped pages (PDF1–7, 197–200). No Lesson-range overlaps; two excluded standalone sample ranges overlap mapped pages and must not be counted again. |
| MinerU OCR | Partial, resumable | 180 page JSON records exist; 173 of the 189 mapped pages have records with at least 50 text characters. Missing: PDF161–171 and 192–196. A retry through PDF160 completed before the user stopped processing. Do not rerun the whole book. |
| OCR correction / provenance | Persisted locally | 100 saved edit entries remain across page records. The count is edit entries, not a claim that 100 distinct pages or all source text were human-approved. Page records retain OCR method, block IDs and source/page provenance. |
| Normalization | Implemented; sample-tested | Safe text normalization and MinerU table/content extraction have focused tests. No independent quality review has been performed on every page of the book. |
| Enrichment / Lesson authoring | Implemented; four Lessons authored | Extractive proposals and editable summary, sections, knowledge units, formulas and tables are available. Only the four Chapter VI JSONs currently exist; there are no Structured JSONs for the other 43 Lessons. Do not infer scientific correctness from generated or normalized content. |
| Structured export and provenance validation | Implemented; Chapter VI artifacts exist | Four JSONs preserve stable Lesson IDs, authored content and page/block references. Existing Chapter VI quality review and BE validation artifacts are present, but are not current whole-book validation after the later OCR retries. |
| Human content review | UI implemented; content not accepted | Local save/accept controls and invalidation on edits exist. The four existing JSONs are `needs_review`; no human acceptance is recorded. Unreviewed Lessons must stay unreviewed. |
| BE candidate and blockers | Chapter VI candidate exists; blocked | Candidate is not release-ready. Curriculum mapping, rights, and formal human reviews are not asserted. Refresh it after finalizing the relevant Structured JSONs. |
| BE/database release apply | Not done | No database writes, migration, Supabase operation or Lab change was performed. A local candidate/dry-run is not a release. |

## What is implemented in the repository

- Local PDF/book import, printed-page mapping, TOC detection, proposed Chapter/Lesson tree, explicit confirmation, stable source Lesson IDs, and page-by-page checkpointed OCR.
- MinerU 4.0.12 integration with normalization and source-page/block provenance; saved page corrections are preferred over later OCR output.
- Local extractive enrichment and persistent Lesson drafts; Structured Lesson JSON export preserves authored learning content and stable IDs while updating OCR-derived source blocks.
- Book → Chapter → Lesson review navigation; PDF and Structured Lesson side by side; editable learning content; source references/warnings; local acceptance and approved-local export controls.
- BE candidate/blocker and Structured JSON validation paths. Local acceptance is separate from BE’s formal release review.
- `run-studio.ps1` starts the Local UI. UI smoke-check and workflow test evidence exists from this run; the script does not make the book content reviewed or approved.

Focused tests most relevant to these claims: whole-book batching/resume/unmapped-page accounting; persistence across restart; human-only acceptance and acceptance invalidation; source provenance; safe normalization; UTF-8 OCR review; and BE dry-run/apply gating. On 2026-10-23, `tests.test_m1_workflow` plus `tests.test_workflow` passed: 25 tests. This is code/workflow evidence, not proof of complete OCR or curriculum review.

## Current workspace artifacts

- Book/source index and page checkpoints: `workspaces/m1-khtn8-acceptance/.local/books/sgk-khtn8/`
- Four Structured JSONs: `workspaces/m1-khtn8-acceptance/exports/structured/`
- Existing Chapter VI candidate, validation and content-quality review: `workspaces/m1-khtn8-acceptance/exports/chapter-vi-be-candidate.json`, `chapter-vi-be-validation.json`, and `chapter-vi-structured-quality-review.md`
- Whole-book report: `workspaces/m1-khtn8-acceptance/reports/sgk-khtn8-whole-book-processing.json` — **stale relative to the per-page retry through PDF160**.
- OCR checkpoint: `workspaces/m1-khtn8-acceptance/.local/books/sgk-khtn8/processing.json` — **stale relative to the per-page retry**. It still shows 7 failed, 2 partial and 38 completed Lessons from the earlier run; those statuses must be recomputed after processing resumes.

The workspace is ignored by Git because it contains source material. Do not commit the PDF, OCR page records or generated local lesson artifacts.

## Blockers and caveats

1. Finish only the missing mapped ranges: Chapter VII PDF161–171, then Chapter VIII PDF192–196. Resume with ` .\run-studio.ps1 ` from the repository root and use the existing Local UI/checkpoints. Avoid whole-book rerun and avoid OCR on already recorded/corrected pages.
2. Refresh the checkpoint and whole-book processing report after those ranges. Check page text thresholds and failures, then verify 47 Lesson coverage and mapping overlap/unmapped counts.
3. Refresh all eligible Structured Lesson JSONs and validate schema, stable IDs, complete page/block provenance and review flags. Preserve the four existing Chapter VI learning-content fields; regenerate reports/candidates from finalized JSONs only.
4. The other 43 Lesson ranges are still TOC proposals. A human must confirm the ranges before treating them as curriculum structure.
5. Local processing permission is not publishing permission. Curriculum outcomes/domain, source publication rights, and formal editorial/subject/accessibility release reviews remain unverified.
6. All unreviewed content must remain `needs_review`; no synthetic reviewer identity or approval may be added.

## Suggested plan from this state

1. Resume and finish Chapter VII’s missing PDF161–171 range; check checkpoint and page-level failures before moving on.
2. Resume and finish Chapter VIII PDF192–196; regenerate the whole-book report so its page/lesson statuses reflect current records.
3. Human-confirm the remaining TOC Lesson ranges before producing final outputs for them; then export and validate the successfully processed Lessons in chapter batches.
4. Review each Structured Lesson against its PDF in the UI, prioritizing formulas, tables, units and scientific statements. Save edits and explicitly accept only reviewed Lessons.
5. Refresh BE candidate and blocker reports from the finalized JSONs. Keep the candidate blocked until actual curriculum, rights and formal release reviews are evidenced.

Start the local tool with:

```powershell
.\run-studio.ps1
```
