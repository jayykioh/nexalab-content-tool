# NexaLab Content Tool

Local-first NexaLab book-to-Lesson tool. Import and author in the local UI; NexaLab BE remains the authoritative release validator and only database writer.

## Current status

- **Available:** Books & Chapters import, PDF/printed-page mapping, chapter OCR with per-page checkpoints, side-by-side OCR correction, persisted Lesson drafts with BASIC_EXERCISE, release blockers, manifest export when eligible, and configured BE dry-run plan. The CLI remains available.
- **Optional:** Gemini LaTeX suggestions are disabled and not implemented; the spec requires separate rights/provider approval before using them.
- **Not verified:** release apply on an identified staging target and full student-facing staging E2E. Do not treat the synthetic `plan` as evidence of a local database or production readiness.

The KHTN 8 local run exercised import, chapter OCR, correction, restart, draft editing and release blockers. It did not produce a release-ready manifest because the real source's publication rights, curriculum outcome and formal reviews have not been verified. See [Master Plan v5.5](specs/NexaLab_Content_Tool_Master_Plan_Lean_v5.5.md).

The synthetic workflow is suitable for local development validation. It does not establish production readiness; the pilot plan requires staging E2E, real source rights and human baseline reviews before any baseline release. The test plan explicitly excludes production testing.

M0a was run locally on a stratified 20-page sample of the supplied KHTN 8 scan. MinerU 4.0.12 `standard` is the current OCR candidate; `basic` and `flash` were faster but had unacceptable Vietnamese/formula loss in the reviewed sample. The sample is scan-only, so no native-text CER/WER baseline was possible. The local Review Workbench records corrections, OCR decisions, history, and elapsed time; it does not collect reviewer identity. This OCR check does not count as subject, rights, or other baseline approval. See [M0a spike report](specs/M0A_SPIKE_REPORT.md). User direction: evaluate KHTN 8 first, defer the second book, and optimize review effort without a fixed hour cap. This remains local evaluation only; it does not resolve publication rights.

## Install

Python 3.12 and `uv` are expected.

```powershell
uv sync
uv run nexalab-content --help
```

## Operator sequence

Create a workspace. Keep real workspaces under `workspaces/`; that directory is ignored because it may contain restricted source material.

```powershell
uv run nexalab-content init workspaces/pilot --name pilot-khtn
```

For native text extraction, set the workspace review policy and confirm local processing rights before adding the exact source/version to `source-inventory.json` with this shape:

```json
{
  "key": "source-key",
  "version": "edition-1",
  "sha256": null,
  "rights": { "localProcessingConfirmed": true },
  "printedPageLabels": { "1": "12" }
}
```

The first successful extraction binds an empty inventory hash to the source file. A later hash mismatch stops extraction.

```powershell
uv run nexalab-content extract workspaces/pilot --source source-key --version edition-1 --file D:\permitted\source.pdf
```

Author pack files under `packs/`. Runtime IDs are never generated from wording or page offsets. Reserve each one explicitly; the owner string follows the paths used by the exporter:

```powershell
uv run nexalab-content id workspaces/pilot --kind pack --id my-pack --owner "packs/my-pack.json#pack"
uv run nexalab-content id workspaces/pilot --kind claim --id claim-1 --owner "packs/my-pack.json#claim:claim-1"
uv run nexalab-content id workspaces/pilot --kind step --id practice-1 --owner "packs/my-pack.json#step:practice-1"
```

If `release.json.sources` contains a backend source policy, reserve its key as `--kind source` with owner `release.json#source:<key>`. Pack evidence must map every claim/source pair and `lesson.content` to a source version, PDF page, locator, extraction method, and source hash.

Render the review report and export only after evidence, review log, and registry checks pass:

```powershell
uv run nexalab-content report workspaces/pilot
uv run nexalab-content export workspaces/pilot
```

The tool deliberately performs only local completeness checks. The backend Zod schema, curriculum records, reviewer accounts, assets, and release gates remain authoritative. To run the included synthetic workspace through a backend dry-run, `plan-local.ps1` requires both backend database URLs to point to loopback. `APP_ENV=development` alone does not prove the database is local; the backend CLI can otherwise connect to remote Supabase. Use:

```powershell
.\scripts\plan-local.ps1
```

For another workspace, use `uv run nexalab-content plan <workspace> --backend ..\nexalab-be --target development`.

For a release, first review the full plan output and resolve every blocker. Apply requires the exact BE digest from that plan and runs a fresh plan immediately before delegating to BE:

```powershell
uv run nexalab-content apply workspaces/pilot --backend ..\nexalab-be --target development `
  --initiated-by operator@nexalab.local --approved-by admin@nexalab.local `
  --confirm-digest <64-character-be-digest>
```

The backend rechecks the active initiator, active ADMIN approver, baseline approver separation, plan gates, transaction, and idempotency. Its CLI email arguments look up accounts; they do not authenticate the operator or prove that a human completed the baseline reviews. Only run baseline apply after real editorial, subject, rights, and accessibility reviews are complete, and run it from the controlled backend environment whose database identity has been verified. No HTTP apply route is used.

## Synthetic example

`examples/synthetic-pilot` demonstrates registry, evidence, fixture review markers, report, and export. Its reviewers and sources are synthetic. It is not approved baseline content and must not be presented as evidence that a human completed review.

```powershell
uv run nexalab-content report examples/synthetic-pilot
uv run nexalab-content export examples/synthetic-pilot
```

For the guided local flow, install MinerU 4.x in a local Python 3.12 environment, then point the UI at its `mineru-kit` executable. Start the loopback-only studio:

```powershell
$env:NEXALAB_MINERU_KIT = 'C:\path\to\mineru-env\Scripts\mineru-kit.exe'
uv run nexalab-content studio workspaces/pilot --port 8765
```

In **Books & Chapters**, import the PDF, enter book metadata, add chapter ranges and printed-page mapping, then run chapter OCR. **OCR Review** shows the source page beside extracted blocks; save corrections and accept pages before authoring. Restarting the studio resumes from files under the workspace's ignored `.local/` directory. In **Lesson Export**, load accepted pages, edit a Lesson and optional BASIC_EXERCISE, and save the draft. Export reports the exact unresolved outcome, source rights and formal-review blockers. Enter a BE checkout and target only after export is eligible; BE plan is dry-run and never applies a release. Local processing rights do not approve publication rights. For an existing MinerU ZIP, the direct review command remains available:

```powershell
uv run nexalab-content review workspaces/pilot `
  --pdf D:\permitted\source.pdf `
  --mineru-zip workspaces\pilot\mineru\sample.zip
```

The example keeps `lesson.questions` empty because that field creates a required public `QUIZ`. Its optional `lesson.basicExercises` object maps to a required `BASIC_EXERCISE` evidence step whose authored step/question/option IDs are preserved through export.
