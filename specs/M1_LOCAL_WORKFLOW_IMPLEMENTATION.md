---
title: 'M1 local content preparation workflow'
type: 'feature'
created: '2026-10-22'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: '58e31e25216f79f2a8291316227a31f43bde21e6'
context:
  - 'specs/NexaLab_Content_Tool_Master_Plan_Lean_v5.4.md'
  - 'specs/content-tool-nexalab-contract.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The repository contains the pilot contract but no executable tool. An operator cannot create a traceable local workspace, preserve stable authored IDs, extract permitted PDF text, review source evidence, export a deterministic NexaLab release manifest, or submit that manifest to the authoritative backend dry run.

**Approach:** Build the first M1 vertical slice as a Python CLI with a file-based workspace. It will support synthetic plumbing end to end while keeping real source files, credentials, baseline approval, OCR expansion, and backend mutations outside this story.

## Boundaries & Constraints

**Always:** Keep source artifacts and intermediate output local and ignored by Git; record source version, page locator, extraction method, and SHA-256 for every extracted block; require operator-authored stable IDs and preserve them verbatim; generate deterministic JSON and a static HTML traceability report; invoke the existing NexaLab `content:release` command only in dry-run mode; treat the current backend Zod schema at commit `48463ea39e147aecdf729a3eae7b1335d6649824` as authoritative.

**Never:** Write directly to NexaLab databases or storage; hold NexaLab credentials; run `--apply`; process real textbook content without confirmed rights and a predeclared `H_review_max`; claim human review from fixture metadata; build a web UI, independent full copy of the backend validator, OCR provider integration, `basicExercises` compatibility shim, asset upload, course binding, Lab authoring, or backend/frontend changes.

</frozen-after-approval>

## Code Map

- `specs/NexaLab_Content_Tool_Master_Plan_Lean_v5.4.md` -- canonical pilot scope and milestone order; supersedes the broader untracked MVP spec in the backend repository.
- `specs/content-tool-nexalab-contract.md` -- integration boundary, release safety rules, and source map.
- `../nexalab-be/src/modules/content/application/content-release.ts` -- authoritative release envelope and plan behavior; do not duplicate its database-aware gates.
- `../nexalab-be/src/modules/content/application/content-pack.ts` -- current pack shape, stable-ID syntax, canonical digest behavior, and human review gates.
- `../nexalab-be/src/modules/content/application/ingestion.ts` -- current source-policy shape.
- `../nexalab-be/scripts/content-release.ts` -- supported dry-run entrypoint to call from the tool.
- `../nexalab-be/content/releases/fixture-khtn8-energy.json` -- synthetic contract fixture to adapt for local plumbing; it must not be presented as reviewed baseline content.

## Tasks & Acceptance

**Execution:**

- [x] `pyproject.toml`, `src/nexalab_content_tool/__main__.py`, `src/nexalab_content_tool/cli.py` -- create a Python 3.12 CLI with explicit `init`, `extract`, `id`, `report`, `export`, and `plan` commands and concise operator errors.
- [x] `src/nexalab_content_tool/workspace.py` -- define and validate the on-disk workspace, source inventory, review thresholds, protected local paths, and file hashes without introducing a database.
- [x] `src/nexalab_content_tool/extract.py` -- extract native PDF text page by page with PyMuPDF and store blocks with physical page index, printed label when supplied, bounding box, method, source version, and hashes; leave MinerU as a later adapter.
- [x] `src/nexalab_content_tool/identity.py` -- maintain an append-only registry of operator-authored pack/source/unit/claim/question/option IDs and reject conflicting reuse.
- [x] `src/nexalab_content_tool/manifest.py` -- combine reviewed workspace files into stable, sorted JSON matching the current release envelope; keep practice questions empty so this story cannot create a required public QUIZ before M2a.
- [x] `src/nexalab_content_tool/report.py` -- render a self-contained HTML report connecting final claims and lesson content to source/version/page/locator and explicit review state.
- [x] `src/nexalab_content_tool/backend.py` -- call the sibling backend `content:release` dry run with an explicit target and manifest path; reject apply-related arguments and surface the backend exit status unchanged.
- [x] `.gitignore`, `README.md`, `examples/synthetic-pilot/` -- protect local source/output directories, document the operator sequence and current limitations, and provide a small synthetic workspace that exercises export/report without representing real review.
- [x] `tests/test_workflow.py` -- preserve the M1 safety boundaries for initialization, extraction failures, stable IDs, evidence validation, deterministic export, report gating, and backend command construction.

**Acceptance Criteria:**

- Given a new directory, when the operator runs `init`, then the CLI creates a versioned workspace with an empty source inventory, an explicit unset review cap, and no credentials.
- Given a permitted PDF, when native extraction runs, then each stored block carries its source hash, source version, 1-based physical page index, optional printed page label, bounding box, and extraction method.
- Given an ID already registered for a different entity, when the operator attempts conflicting reuse, then the CLI fails without rewriting the registry.
- Given the synthetic example, when `report` and `export` run twice without input changes, then their semantic output is stable and the release manifest contains only the current backend fields with authored IDs unchanged.
- Given an unreviewed or incomplete pack, when export is requested, then the tool identifies local completeness problems and does not invent reviewer approval; backend-specific curriculum/account/asset gates remain for `plan`.
- Given an explicit backend path and target, when `plan` runs, then it invokes the existing dry-run command without `--apply`, writes no database data through tool code, and returns the backend result to the operator.

## Implementation Notes

- Implemented a Python 3.12+ package with PyMuPDF as the only runtime dependency and generated `uv.lock`.
- Workspace initialization leaves review thresholds unset and stores no credential fields; real extraction requires both global and source-level rights gates plus a positive review cap.
- Export performs only tool-owned safety/completeness checks, strips tool-only evidence/review-log fields, and delegates authoritative schema/database gates to the backend dry run.
- Synthetic verification produced the same local export SHA-256 twice (`379803720436f2b7063d973c12a8365e97451a61c81a033c773a347a228cb4ed`). Backend plan returned no blockers and did not write.
- Native extraction was exercised with a generated synthetic PDF; registry conflict handling was exercised and left the registry byte-identical.
- Review remediation made initialization and export atomic, rejects empty/corrupt native extraction, rechecks the source hash after parsing, reconciles non-fixture evidence against the source inventory and extraction artifact, and makes the report pass the same local completeness gate as export.
- Eight executable workflow tests pass under `uv`; the authoritative backend plan still reports no blockers and `PLAN ok (dry run; nothing written)`.

## Spec Change Log

## Review Triage Log

| ID | Finding | Verdict | Resolution |
|---|---|---|---|
| B1 | M1 does not calculate `H_review_est` | reject | This is the preceding M0a spike gate in the master plan; M1 requires the already-declared finite cap before real extraction. |
| B2 | Inventory hash is bound before artifact write | patch | Artifact is written first; inventory binding occurs only after extraction output succeeds. |
| B3 | Empty native extraction succeeds | patch | Empty native text now stops with an explicit OCR/layout-review error and leaves the hash unbound. |
| B4 | PyMuPDF failures leak tracebacks | patch | Parser/open errors are translated to `ContentToolError`. |
| B5 | Evidence is not reconciled with inventory/artifact | patch | Non-fixture evidence must match inventory version/hash and extraction metadata/page range. |
| B6 | Evidence locator is optional | patch | Every evidence row now requires a non-empty locator. |
| B7 | Evidence targets can be orphaned, ambiguous, or duplicated | patch | Exactly one known claim or `lesson.content` target is required and target/source duplicates are rejected. |
| B8 | Duplicate pack files, pack keys, or release source keys pass | patch | All three duplicate classes are rejected locally. |
| B9 | Report bypasses export completeness checks | patch | Report calls `build_manifest()` before rendering. |
| B10 | Report omits review-relevant pack/source detail | patch | Report now includes outcomes, knowledge terms/misconceptions, materials, source rights/attribution, and extracted page text. |
| B11 | Init overwrites managed files in a non-workspace directory | patch | Init requires an empty target and installs a staged workspace atomically. |
| B12 | No executable regression coverage | patch | Added eight standard-library workflow tests for the stated safety boundaries. |
| E1 | Init can overwrite existing metadata | patch | Same remediation as B11. |
| E2 | Partial init blocks retry | patch | The complete workspace is built in a temporary sibling then atomically renamed. |
| E3 | NaN/infinite review cap passes | patch | Review cap must be finite and positive. |
| E4 | PDF can change after initial hash | patch | Source is rehashed after parsing and before any output. |
| E5 | Zero-block PDF binds a source | patch | Same remediation as B3. |
| E6 | Concurrent ID writers can race | reject | The approved one-operator pilot explicitly defers locks/concurrency; registry writes remain atomic. |
| E7 | Boolean page index passes as integer | patch | Boolean values are explicitly rejected. |
| E8 | Locator and source provenance can be fabricated | patch | Same remediation as B5/B6. |
| E9 | Report can render an incomplete pack | patch | Same remediation as B9. |
| E10 | Backend dry run can hang forever | patch | Subprocess has a 300-second safety timeout with an operator-facing error. |
| E11 | Interrupted export can destroy prior manifest | patch | Export now uses the shared atomic JSON writer. |
| E12 | Malformed inventory/registry entries leak attribute errors | patch | Both readers reject non-object entries before access. |
| E13 | Tool does not recursively clone the backend Zod validator | reject | The frozen boundary keeps the backend authoritative and forbids an independent full validator; backend `plan` remains the schema gate. |
| E14 | Reviewer identity fields are not checked locally | patch | Reviewer name, email, timezone-bearing ISO timestamp, and duplicate review kinds are validated. |
| E15 | Report does not validate evidence links | patch | Same remediation as B9. |
| V1 | Extraction safety/provenance lacks executable tests | patch | Added empty/corrupt extraction and unbound-hash tests; the synthetic successful extraction remains in command verification. |
| V2 | Stable ID conflict is only manually demonstrated | patch | Added byte-preservation regression test for conflicting ownership. |
| V3 | Manifest gates/determinism lack negative tests | patch | Added deterministic export and ambiguous/fabricated evidence tests. |
| V4 | Backend dry-run boundary lacks a command test | patch | Added command construction, exit-code propagation, no-apply, and timeout assertions. |

## Design Notes

The local authoring file should wrap a near-backend `pack` object with tool-only `evidence` and review-log data. Export removes tool-only fields rather than maintaining another comprehensive implementation of the backend schema. The synthetic example must use empty `lesson.questions` until M2a adds the dedicated `basicExercises` contract; this prevents accidental public QUIZ creation under the current materializer.

## Verification

**Commands:**

- `uv run nexalab-content --help` -- expected: all six commands are listed.
- `uv run nexalab-content init .tmp/demo` -- expected: a valid local workspace is created with no secret or source payload committed.
- `uv run nexalab-content report examples/synthetic-pilot` -- expected: a self-contained traceability report is generated.
- `uv run nexalab-content export examples/synthetic-pilot` -- expected: a deterministic current-schema fixture manifest is generated.
- `uv run nexalab-content plan examples/synthetic-pilot --backend ../nexalab-be --target development` -- expected: the backend CLI performs a dry run and the tool never appends `--apply`.
- `uv run python -m unittest discover -s tests -v` -- expected: all M1 workflow boundary tests pass.
