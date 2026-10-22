# NexaLab Content Tool

Local-first CLI for preparing a small, reviewed NexaLab content release. NexaLab BE remains the authoritative validator and the only writer. This repository does not hold database credentials or apply releases.

## Current M1 slice

- Create a versioned file workspace.
- Reserve stable operator-authored IDs.
- Extract native PDF text with source/page/hash provenance after rights and review-cap gates are set.
- Render a static HTML evidence report.
- Export deterministic JSON for the current NexaLab release schema.
- Invoke the existing backend release command in dry-run mode only.

MinerU, real textbook ingestion, `basicExercises`, backend/FE changes, release apply, asset upload, course binding, Labs, and a web editor are later milestones.

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

The `plan` command has no apply flag and invokes `npm run content:release` without `--apply`.

## Synthetic example

`examples/synthetic-pilot` demonstrates registry, evidence, fixture review markers, report, and export. Its reviewers and sources are synthetic. It is not approved baseline content and must not be presented as evidence that a human completed review.

```powershell
uv run nexalab-content report examples/synthetic-pilot
uv run nexalab-content export examples/synthetic-pilot
```

The example keeps `lesson.questions` empty. Under the current backend materializer, those questions become a required public `QUIZ`; dedicated `basicExercises` support belongs to M2a.
