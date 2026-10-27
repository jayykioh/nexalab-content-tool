# NexaLab Content Tool — pipeline status (KHTN 8)

Updated: 2026-10-26
Repository branch: `p2-vid`
Available workspace: `workspaces/khtn8-m1-real`
Canonical workspace source: `.local/books/sgk-khtn8-kntt/source.pdf`, 200 PDF pages, SHA-256 `29e4ccd95130cb38cfe9a696fe2edd5e0e66496ab9761c8a60ac5cb5803c3ffb`.

The user-supplied file `SGK Khoa học tự nhiên 8-mau (1).pdf` has SHA-256 `84379558517b1eb53dc1ea0c76e40aecc20bb0384be965a3659dc86147317375`. It is a separately repackaged PDF: sampled rendered pages match the canonical workspace source, but its byte digest is different. It must not be mixed into hash-bound page records or used to relabel existing provenance.

## Executive status

The local pipeline and review/export UI are implemented, but the historical workspace described by the earlier status (`workspaces/m1-khtn8-acceptance`) is not present in the current checkout or anywhere under the WDP301 workspace. Its claimed 173/189 page checkpoint and four Chapter VI Structured JSONs therefore cannot be inspected or resumed. The available `workspaces/khtn8-m1-real` contains only 11 page JSONs for PDF22–32, three mapped entries (Bài 4–6), no `processing.json`, and no Structured Lesson exports. No Lesson has local human content acceptance, and no BE release approval is represented.

| Pipeline stage | Current status | Evidence / limit |
|---|---|---|
| Source import and local processing setup | Done for this workspace | 200-page PDF is stored locally and hash-bound. This records local processing setup; it does not establish publication rights. |
| TOC → Chapter → Lesson map | Historical artifact unavailable | The 47-Lesson map described previously is not present. The available workspace maps only Bài 4–6 (PDF22–32). |
| MinerU OCR | Not resumable from claimed checkpoint | Only 11 page JSON records are present. The historical 173/189 checkpoint is unavailable, and `mineru-kit` is not installed/discoverable in the current environment. |
| OCR correction / provenance | Persisted for available pages only | The 11 available page records contain 96 saved edit entries and all 11 are locally marked accepted. This does not establish coverage or approval for the rest of the book. Page records retain OCR method, block IDs and source/page provenance. |
| Normalization | Implemented; sample-tested | Safe text normalization and MinerU table/content extraction have focused tests. No independent quality review has been performed on every page of the book. |
| Enrichment / Lesson authoring | Workflow implemented; book artifacts unavailable | No KHTN 8 Structured JSON is present in the available workspace. Do not infer scientific correctness from generated or normalized content. |
| Structured export and provenance validation | Workflow implemented; no current book artifact | The previously reported Chapter VI artifacts are not present and cannot be treated as current evidence. |
| Human content review | UI implemented; no current Lesson artifact | Local save/accept controls and invalidation on edits exist, but there are no available Structured Lesson JSONs to review or accept. |
| BE candidate and blockers | No current KHTN 8 candidate | No inspectable candidate exists in the available workspace. Curriculum mapping, rights, and formal human reviews are not asserted. |
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

- Available source index and 11 page records: `workspaces/khtn8-m1-real/.local/books/sgk-khtn8-kntt/`.
- No `processing.json`, whole-book report, or KHTN 8 Structured JSON is currently available.
- The historical `workspaces/m1-khtn8-acceptance` paths are unavailable and must be restored from their original machine/backup before a 16-page-only resume is attempted.

The workspace is ignored by Git because it contains source material. Do not commit the PDF, OCR page records or generated local lesson artifacts.

## Blockers and caveats

1. Restore the original hash-bound `workspaces/m1-khtn8-acceptance` directory (including page JSONs, book tree, `processing.json`, Structured exports, and its exact source PDF) from backup. Without it, a 16-page-only resume is impossible.
2. Verify the restored checkpoint's exact source digest before running the reported missing ranges. Never rebind its records to the user-supplied repackaged PDF.
3. After restoring and completing the missing ranges, refresh the checkpoint and whole-book report, then validate 47-Lesson coverage and mapping overlap/unmapped counts.
4. Refresh eligible Structured Lesson JSONs and validate schema, stable IDs, complete page/block provenance and review flags. Preserve authored fields from restored artifacts; do not invent them from this status document.
5. Local processing permission is not publishing permission. Curriculum outcomes/domain, source publication rights, and formal editorial/subject/accessibility release reviews remain unverified.
6. All unreviewed content must remain `needs_review`; no synthetic reviewer identity or approval may be added.

## Suggested plan from this state

1. Restore and verify the historical checkpoint before any OCR. Confirm its source digest and the reported 173/189 coverage.
2. Only after restoration, resume the reported missing ranges PDF161–171 and PDF192–196, then regenerate the whole-book report.
3. Human-confirm the remaining TOC Lesson ranges before producing final outputs for them; then export and validate the successfully processed Lessons in chapter batches.
4. Review each Structured Lesson against its PDF in the UI, prioritizing formulas, tables, units and scientific statements. Save edits and explicitly accept only reviewed Lessons.
5. Refresh BE candidate and blocker reports from finalized JSONs. Keep the candidate blocked until actual curriculum, rights and formal release reviews are evidenced.

Start the local tool with:

```powershell
.\run-studio.ps1
```
