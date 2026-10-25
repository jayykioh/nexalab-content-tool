# NexaLab Content Tool

Local-first NexaLab book-to-Lesson tool. Import and author in the local UI; NexaLab BE remains the authoritative release validator and only database writer.

## Current status

- **Available:** Books & Chapters import, PDF/printed-page mapping, chapter OCR with per-page checkpoints, side-by-side OCR correction, local extractive Lesson/knowledge-unit proposals from accepted pages, persisted Lesson drafts with BASIC_EXERCISE, release blockers, manifest export when eligible, and configured BE dry-run plan. The CLI remains available.
- **Optional:** Gemini proposals require explicit provider-policy and source-transmission confirmation plus a configured API key. They remain proposals for operator review; no external source transfer occurs in the local-only flow.
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

For another workspace in this checkout layout, use `uv run nexalab-content plan <workspace> --backend ..\BE-NexaLab --target development`.

For a release, first review the full plan output and resolve every blocker. Apply requires the exact BE digest from that plan and runs a fresh plan immediately before delegating to BE:

```powershell
uv run nexalab-content apply workspaces/pilot --backend ..\BE-NexaLab --target development `
  --initiated-by operator@nexalab.local --approved-by admin@nexalab.local `
  --confirm-digest <64-character-be-digest>
```

The backend rechecks the active initiator, active ADMIN approver, baseline approver separation, plan gates, transaction, and idempotency. Its CLI email arguments look up accounts; they do not authenticate the operator or prove that a human completed the baseline reviews. Only run baseline apply after real editorial, subject, rights, and accessibility reviews are complete, and run it from the controlled backend environment whose database identity has been verified. No HTTP apply route is used.

## Curriculum bootstrap for another textbook

Start with `outcomes-propose` to build a deterministic local proposal from existing Structured Lesson JSON in `exports/structured`. It reads explicit objective fields and text blocks following an existing `Mục tiêu`/`Objectives` section heading; it does not rerun OCR or invent objective wording. Knowledge Unit headings stay separately labeled as source concepts, never promoted to outcomes solely because they are headings. Candidates include measurable-action and source-grounding checks, stable ordered-text identities, near-duplicate flags, Lesson and multi-outcome Knowledge Unit mapping suggestions, provenance, confidence basis, and proposal-only Lab opportunity classes. A candidate is never approved automatically, and no official curriculum code is generated. The review queue groups evidence by book, chapter, Lesson and source topic, with ambiguous items first.

```powershell
uv run python -m nexalab_content_tool.cli outcomes-propose workspaces/pilot --name textbook-a
```

The report is written to `.local/outcomes/textbook-a.json`. Optional `--curriculum-source-metadata path/to/catalog.json` pins the local catalog digest separately from an official source document digest; a missing official document checksum stays `null`. The extraction is generic and does not assume one outcome per Knowledge Unit. The local `outcomes-review` workflow records named human decisions for internal outcomes and mappings after source text verification; it does not make an outcome official. Explicitly approved internal outcomes can sync through the separate guarded BE Registry workflow. Official curriculum crosswalk remains an optional, separate verification stage.

```powershell
uv run python -m nexalab_content_tool.cli outcomes-review workspaces/pilot --name textbook-a --input outcome-review.json
```

The existing Content Tool Studio includes a grouped visual review screen at **4. Duyệt outcomes**. Start it from this repository root and open the printed loopback URL:

```powershell
uv run python -m nexalab_content_tool.cli studio workspaces/m1-khtn8-acceptance --port 8765
```

Open `http://127.0.0.1:8765`, choose **4. Duyệt outcomes**, and load `khtn8-quality-review`. The screen groups candidates and mappings by Chapter and Lesson and displays source phrase, PDF page, source blocks, source digest, ambiguity, confidence and mapping suggestion. The operator must select each row, choose a decision, enter a real reviewer identity/reason, and confirm source verification. It supports approve, revise, reject, merge, reuse, ambiguous and unmapped actions. Loading or displaying proposals does not record a decision.

Each review input explicitly selects candidate IDs. Outcome decisions are `approve`, `revise`, `reject`, `merge`, or `reuse`; mapping decisions are `approve`, `revise`, `reject`, `ambiguous`, or `unmapped`. Every selected decision includes the exact `verifiedSourceBlockIds`; the ID list must cover all evidence blocks for that candidate or mapping. Approval also requires a named reviewer, email, reason, source verification and, when relevant, explicit duplicate/quality resolution. A revised statement remains pending until a later explicit approval. `merge` points to an approved internal outcome; `reuse` selects another candidate or an existing BE code. An `unmapped` decision requires a documented reason. Decisions append to `.local/outcomes/review-events.jsonl`; immutable proposal snapshots are stored under `.local/outcomes/versions/` and referenced by SHA-256 proposal version.

```json
{
  "sourceTextVerified": true,
  "reviewerName": "Actual reviewer name",
  "reviewerEmail": "reviewer@example.org",
  "reason": "Checked the cited source blocks and page locators",
  "outcomeDecisions": {
    "<candidate-id>": {
      "decision": "approve",
      "verifiedSourceBlockIds": ["<source-block-id>"],
      "registryAttributes": {"grade": 8, "domain": "MATTER", "chapter": "Reviewed chapter title"}
    }
  },
  "mappingDecisions": {
    "<mapping-id>": {"decision": "approve", "verifiedSourceBlockIds": ["<source-block-id>"]}
  }
}
```

Run `outcomes-export` to produce the approved-only bundle, rejected/merged records, reviewed Lesson/Knowledge Unit mappings, remaining queue and preflight report. `outcomes-sync` writes approved internal outcomes only, after checking the BE development target and provenance column; it never writes Lessons or publishes content. New outcomes receive stable `NXO-…` NexaLab codes; `officialCode` remains null. The separate `curriculum-propose/review/sync` flow remains for an optional verified official curriculum crosswalk.

```powershell
uv run python -m nexalab_content_tool.cli outcomes-export workspaces/pilot --name textbook-a
$env:NEXALAB_ADMIN_ACCESS_TOKEN = '<current admin token>'
uv run python -m nexalab_content_tool.cli outcomes-sync workspaces/pilot --name textbook-a --api-base http://127.0.0.1:4000/api
```

The additive BE migration `20261025100000_curriculum_outcome_source_evidence` adds append-only JSONB provenance to new and reused `CurriculumOutcome` records. Existing rows remain null until explicitly backfilled. Sync checks the current BE target response for `outcomeSourceEvidencePersisted=true` and stops before taxonomy reads/writes when the migration is absent. Deploy migrations with the repository's `npm run db:migrate` workflow; do not modify Prisma migration history manually.

For optional model assistance, pass `--llm-proposals reviewed-model-output.json`. Each candidate ID must map to exactly `normalizedStatement`, `evidenceSourceBlockIds`, `confidence`, `ambiguity`, `mergeWithOutcomeId`, and `suggestedOutcomeIds`; cited blocks and mapping targets must be allowed for that candidate, and a merge target must be one of its flagged possible duplicates. Model output remains a suggestion requiring human review.

The existing BE Registry sync remains constrained by the current BE Registry contract (Grades 8–9 and its configured domains). Internal textbook-derived outcomes require their own explicit human outcome/mapping decisions, provenance and BE target/environment preflight; they do not require or receive invented official codes. If an official curriculum crosswalk is later needed, verify its source document and locators through the separate `curriculum-propose/review/sync` workflow.

Curriculum and textbook structure have separate identities. Keep stable `framework.key`, Subject IDs, chapter/topic codes and semantic outcome keys in the proposal; never derive those keys from PDF page numbers or OCR headings. `curriculum-propose` creates NexaLab-owned outcome codes (`NX-…`) and stores official statements/source locators separately. It suggests exact active, non-synthetic BE matches and exposes other active outcomes for the same grade/domain as human-review candidates. Only the explicit reviewer choice reuses a non-exact candidate. A source's official outcome code is never invented.

Create an input JSON with this shape. The source PDF digest and each outcome locator are required evidence fields; enter verified source text and references from the authoritative curriculum source:

```json
{
  "framework": {
    "key": "VN2018",
    "version": "2018.1",
    "title": "Verified curriculum framework title",
    "source": {
      "authority": "Issuing authority",
      "url": "https://authority.example/curriculum.pdf",
      "publishedAt": "2018-12-26",
      "accessedAt": "2026-10-24",
      "sha256": "<64-character source file SHA-256>"
    }
  },
  "textbookIdentity": {"bookKey": "book-key", "version": "edition-key"},
  "subjects": [{
    "id": "KHTN",
    "name": "Khoa học tự nhiên",
    "chapters": [{
      "code": "KHTN-G8-MATTER-01",
      "title": "Stable curriculum chapter title",
      "grade": 8,
      "domain": "MATTER",
      "topics": [{
        "code": "KHTN-G8-MATTER-ATOMS",
        "title": "Stable curriculum topic",
        "outcomes": [{"key": "atomic-model", "statement": "Verified official statement", "sourceLocator": "page 14, section 2"}]
      }]
    }]
  }],
  "mappings": [{
    "lessonId": "book-key-lesson-id",
    "knowledgeUnitId": "knowledge-unit-id",
    "outcomeKeys": ["atomic-model"],
    "sourcePages": [8],
    "rationale": "Human-reviewable mapping rationale"
  }]
}
```

Run the proposal and inspect the generated registry. The first command can query BE read-only to add exact-match reuse suggestions. Then record explicit source, outcome and mapping approvals. `NEXALAB_ADMIN_ACCESS_TOKEN` is read from the process environment and is not saved in workspace files. Curriculum sync writes only through BE admin APIs and is hard-restricted to a loopback API URL. Before any writes it calls the read-only `/admin/curriculum-target` check and requires `APP_ENV=development` plus loopback `DATABASE_URL` and `DIRECT_URL`; a local BE connected to a remote database is rejected. It creates a versioned BE Framework plus Subject/grade links, then uses existing Chapter/Topic/Outcome endpoints. It refuses unapproved registries and conflicting existing records. The sync command never publishes content. It asks the existing release exporter to regenerate a manifest only when all normal content/release gates are already satisfied.

```powershell
$env:NEXALAB_ADMIN_ACCESS_TOKEN = '<current admin token>'
uv run nexalab-content curriculum-propose workspaces/pilot --input curriculum-proposal.json --api-base http://127.0.0.1:4000/api
```

Open `.local/curriculum/<framework>@<version>.json`, review the generated internal codes and reuse candidates, then create a separate review JSON containing the selected `outcomeCodes` mapping from each semantic key to either an exact existing BE code or the proposed `NX-…` code; `mappingIds` contains the proposal's mapping IDs. The reviewer fields and reason are required:

```json
{
  "sourceVerified": true,
  "outcomeCodes": {"atomic-model": "NX-VN2018-8-MA-ATOMIC-MOD-1234ABCD"},
  "mappingIds": ["<mapping id from the registry>"],
  "reviewerName": "Actual reviewer name",
  "reviewerEmail": "reviewer@example.org",
  "reason": "Source locator and outcome-to-Lesson mapping reviewed"
}
```

```powershell
uv run nexalab-content curriculum-review workspaces/pilot --framework VN2018 --version 2018.1 --input curriculum-review.json
uv run nexalab-content curriculum-sync workspaces/pilot --framework VN2018 --version 2018.1 --api-base http://127.0.0.1:4000/api
Remove-Item Env:NEXALAB_ADMIN_ACCESS_TOKEN
```

Review approval is a local operator record; BE admin authentication and its audit log record any authoritative taxonomy creation. The local BE URL guard prevents accidental remote/production writes. A BE curriculum record remains separate from a textbook Lesson; no Lesson JSON is rewritten by bootstrap. The full release manifest remains blocked until the existing source-rights, pack-content, and formal-review requirements pass. Use `plan` only after inspecting the regenerated manifest and verifying its actual target database identity.

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

In **Books & Chapters**, import the PDF, enter book metadata, OCR the selected TOC pages locally, detect the proposed Book → Chapter → Lesson tree, correct printed-page/PDF-page ranges, and confirm it. The confirmed source Lesson IDs and TOC provenance are stored in the existing local book index. Select a Lesson to run OCR only across its mapped PDF range. **OCR Review** shows the source page beside extracted blocks; save corrections and accept pages before authoring. Restarting the studio resumes from files under the workspace's ignored `.local/` directory. In **Lesson Export**, load accepted pages for the selected Lesson, use **Tạo cấu trúc từ OCR đã review** for extractive sections, summary, and one knowledge unit per section, then check the suggestions and edit the Lesson and optional BASIC_EXERCISE before saving. The saved draft retains its source Lesson identity, chapter, page ranges and TOC provenance. The tool preserves authored fields, original OCR, source block IDs, and math symbols; it does not infer curriculum taxonomy/outcomes or verify scientific correctness. Export reports the exact unresolved outcome, source rights and formal-review blockers. Enter a BE checkout and target only after export is eligible; BE plan is dry-run and never applies a release. Local processing rights do not approve publication rights. For an existing MinerU ZIP, the direct review command remains available:

For a mapped book, **Xử lý / tiếp tục toàn bộ Lessons đã map** resumes contiguous OCR batches from saved page checkpoints; proposed TOC ranges remain visibly unconfirmed until a person confirms them. **Refresh JSON + BE candidate** writes per-Lesson Structured JSON, page/block provenance, the whole-book coverage report, BE candidate and blocker report. The Structured Lesson review panel edits summary, sections, knowledge units, formulas and tables beside the PDF; saving returns the Lesson to `needs_review`, while explicit local acceptance is separate from BE release approval. Exporting an accepted JSON requires its current content and source-block snapshot to match the human review.

```powershell
uv run nexalab-content review workspaces/pilot `
  --pdf D:\permitted\source.pdf `
  --mineru-zip workspaces\pilot\mineru\sample.zip
```

The example keeps `lesson.questions` empty because that field creates a required public `QUIZ`. Its optional `lesson.basicExercises` object maps to a required `BASIC_EXERCISE` evidence step whose authored step/question/option IDs are preserved through export.
