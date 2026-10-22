# NexaLab Content Tool

Local-first CLI for preparing a small, reviewed NexaLab content release. NexaLab BE remains the authoritative validator and the only writer. This repository does not hold database credentials; release writes are delegated to the existing NexaLab BE CLI.

## Current M1 slice

- Create a versioned file workspace.
- Reserve stable operator-authored IDs.
- Extract native PDF text with source/page/hash provenance after rights and review-cap gates are set.
- Render a static HTML evidence report.
- Export deterministic JSON for the current NexaLab release schema, including an optional authored `basicExercises` step.
- Invoke the existing backend release command in dry-run mode and gate apply on the exact planned digest.

MinerU, real textbook ingestion, asset upload, course binding, Labs, and a web editor are later milestones.

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

Before extraction, edit `workspace.json` to set a positive `reviewPolicy.hReviewMaxHours` and set `localSourceRightsConfirmed` only after rights are confirmed. Add the exact source/version to `source-inventory.json` with this shape:

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

The tool deliberately performs only local completeness checks. The backend Zod schema, curriculum records, reviewer accounts, assets, and release gates remain authoritative:

```powershell
uv run nexalab-content plan workspaces/pilot --backend ..\nexalab-be --target development
```

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

The example keeps `lesson.questions` empty because that field creates a required public `QUIZ`. Its optional `lesson.basicExercises` object maps to a required `BASIC_EXERCISE` evidence step whose authored step/question/option IDs are preserved through export.
