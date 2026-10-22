# Content Tool ↔ NexaLab integration contract

> **Snapshot:** 2026-10-22, NexaLab BE commit `48463ea39e147aecdf729a3eae7b1335d6649824` (`main`).
> **Status:** reference snapshot for starting a separate Content Tool repository. This is not an API promise or a replacement for the live code. Recheck the named source files and commit before implementing against it.

## 1. Purpose and boundary

The Content Tool is a separate, local-first operator tool for extracting, organizing, reviewing, and packaging source content. NexaLab remains authoritative for validation, authorization, persistence, publication, progress, and student delivery.

The tool may produce a normalized, human-reviewed release manifest. It must not write directly to NexaLab's database, bypass the API/import path, or treat copied schema notes as implementation authority. The backend does not OCR, parse source books, generate/summarize/repair lesson content, or infer missing facts; it validates and deterministically materializes a trusted manifest.

For the first import, reuse existing models. Do not introduce new ingestion, package, course, or release tables by default. Preserve existing legacy data/readers while the pilot is being validated. Any later migration/removal requires a separate consumer inventory, migration plan, and rollback evidence.

## 2. Evidence labels

- **Implemented at snapshot:** verified in the NexaLab BE/FE source at the commit above.
- **Product constraint:** required by `docs/product/prd.md`; implementation still needs code-path verification when changed.
- **Tool proposal:** work to build in the separate tool or future BE work; not represented as an existing capability.

Do not convert a product requirement or tool proposal into a claim of shipped behavior.

## 3. Current release interface

**Implemented at snapshot:** `AdminContentController` is `ADMIN`-only (`src/modules/content/interface/admin-content.controller.ts`). The HTTP release routes are:

| Method | Path | Current behavior |
|---|---|---|
| `GET` | `/admin/releases` | List recent releases with items. |
| `POST` | `/admin/releases/plan` | Dry-run a manifest; validates and returns blockers/actions, with an audit record. |
| `POST` | `/admin/releases/:id/retire` | Retire an applied release using a reason and explicit `confirm: true`. |

The release manifest is parsed by `releaseManifestSchema` in `src/modules/content/application/content-release.ts`: strict top-level object with `name`, `namespace` (`fixture` or `baseline`), `sources[]`, and `packs[]`. The canonical schema and gates in `src/modules/content/application/content-pack.ts`, `src/modules/content/application/ingestion.ts`, and the release service are authoritative; do not duplicate them as a second source of truth.

**Implemented in application/CLI path, not exposed as HTTP apply:** `applyRelease(...)` plans again, checks an active ADMIN approver, requires a distinct approver for `baseline`, writes release/content changes transactionally, and returns an idempotent receipt for an already-applied digest. Confirm the exact CLI entrypoint and deployment wiring before operating it; this contract does not assert that a production CLI or environment is configured.

`rollback` is not a current HTTP route. The implemented operation is `retire`; do not describe it as general rollback without verifying its exact semantics against the target release and current state.

## 4. Existing models to reuse

| Concern | Existing model/code | Integration implication |
|---|---|---|
| Reviewed lesson package | `ContentPack`, `ContentPackVersion` (`prisma/schema.prisma`; `content-pack.ts`) | Manifest is immutable/versioned by package key and digest; released pack versions point to materialized lessons. |
| Applied deployment | `ContentRelease`, `ContentReleaseItem` (`prisma/schema.prisma`) | Receipt records environment, digest, importer version, initiator/approver and item actions. Items use polymorphic `kind/refId`; this is not course membership. |
| Student lesson | `Lesson`, `LessonStep` and `materializeLegacySteps` (`pathway.ts`) | Release application creates/publishes a shared lesson; pathway generation must be checked because legacy materialization synthesizes required steps. |
| Official course and progress | `FoundationalCourseVersion`, `FoundationalCourseLesson` (`prisma/schema.prisma`); `FoundationalProgressService` | Course membership, order and denominator come from an active course version, not from `ContentRelease`. Binding a released lesson into a course is a separate, explicit operation/contract. |
| Media | `Asset`, immutable `AssetVersion` (`prisma/schema.prisma`) | Existing pack schema requires a concrete `assetv:<AssetVersionId>` reference. A tool-side logical asset key needs an explicit, reviewed resolution to a READY version before producing a BE manifest. |
| Curriculum | Subject/chapter/topic/outcome models; pack gate validates outcome codes | Use current official IDs/codes from the target backend; never invent or silently map curriculum codes. |
| Lab | Existing `Lab`, practical activity/simulation version models | Lab attachment is optional/post-Lesson for the pilot. Pin and validate a concrete version if added; never assume a logical Lab key resolves safely. |

The schema is intentionally not normalized or migrated by this contract. It describes the current shape only.

## 5. Content and student-flow constraints

**Product constraint (`docs/product/prd.md`, Open Curriculum decisions):**

- Open Curriculum lessons may include reading, video/equivalent text, lesson-level basic exercises, and foundational Labs.
- A shared scored quiz, Quizlet/card activity, or quiz-pass gate must not gate public lesson or foundational Lab access.
- `Class Space` resources and explicitly assigned scored tests remain separate from public shared curriculum.
- Foundational progress is computed from the active `FoundationalCourseVersion`; only required `READING`, `VIDEO`, and `BASIC_EXERCISE` steps are included as step evidence by the current service, with course-linked required Labs handled separately.

**Implemented at snapshot:** `materializeLegacySteps` currently creates a required `QUIZ` step when a package has `lesson.questions`; `BASIC_EXERCISE` has a distinct pathway schema/type. Therefore, do not send Content Tool practice exercises through `lesson.questions` unless their exact schema/materialization semantics are deliberately changed and checked against the product constraint. Define the package-to-`BASIC_EXERCISE` mapping before pilot apply.

**Implemented at snapshot:** existing pack questions/materialization may not preserve tool-authored stable question/option IDs end-to-end. Verify `lessonFromPack`, materialization, API response, attempt records, and FE keys before claiming stable identity across wording edits.

## 6. Content Tool responsibilities (proposal)

The separate repository may own:

1. Local source inventory and extraction adapters (including local native-text/OCR/layout paths).
2. A static HTML review report and structured review decisions; edits live in the canonical source files. A React Review Workbench is outside the Lean v5.4 pilot.
3. Stable logical IDs for authored packages/questions/options and a backed-up ID registry.
4. Deterministic export of a manifest accepted by the current BE schema, plus schema/version and source commit metadata.
5. CLI `plan` / `apply` orchestration only after the real supported backend invocation is verified. The backend remains the final validator and writer. The current `content:release` CLI checks active account emails; these arguments do not authenticate a separate human reviewer.

Keep any AI/OCR provider optional and outside BE request handling. If transfer/retention/training/region rights are unresolved, extraction and review must still work locally without sending source material to an external provider. Set the review workload cap before the extraction spike and estimate total review time from measured flagged-item counts and review time by item type.

## 7. Apply, identity, and asset gates

Before staging apply, the implementation contract must settle:

- What constitutes the initial/legacy release and how the first package is applied safely.
- Whether omitted content means “unchanged” or removal; removal must never be inferred silently from omission.
- Idempotency behavior for same key/same digest and same key/different digest, including environment and importer/schema version in the digest contract.
- Stable ID preservation through package → Lesson/step → FE → attempts/evidence.
- Explicit mapping `(release or target environment, logical asset key) -> READY AssetVersionId`, including immutability, review, and digest binding. No unresolved logical key may reach `assetv:`.
- Explicit course-version membership/order/activation and historical-progress behavior; release membership alone does not update a foundational course.
- Audited reviewer identity and payload-bound review approval. A claimed email/hash in a file is not proof of who reviewed that exact payload.
- Credentials must stay out of the repo and manifests; use environment/user secrets. The existing CLI is a trusted server-side operation with active-account checks, not an authenticated HTTP apply route. Do not describe email arguments as proof of human approval.

For a trusted one-operator staging pilot, retain dry-run, authenticated operator, atomic apply, and idempotency. Defer locks, concurrency handling, stale-base enforcement, generalized rollback, and multi-operator controls until recovery needs or multiple operators justify them. Keep an explicit recovery procedure and a way to quarantine/revoke a bad release/assets.

## 8. Legacy and database change policy

Do not perform broad schema normalization as a prerequisite for creating the Content Tool repo. Start with a versioned adapter/export manifest and use the existing release/pack/Lesson/asset/Lab models.

Add a BE migration only when a demonstrated contract cannot be represented safely with current models, and make it additive/backward-compatible for the pilot. Before removing any legacy field/table/path, inventory readers and writers across BE, FE, jobs, scripts, seed, and operational tooling; prevent dual writes; prove old records remain readable; then remove in a separate change after the new path is verified.

## 9. Verification before the first apply

1. Rebase this contract against the current BE commit; inspect current Zod schemas and route manifest.
2. Produce a small package containing 2–3 lessons and validate it with the backend dry-run.
3. Check every blocker, materialized Lesson/step type, asset version, curriculum code, reviewer and rights evidence.
4. Confirm no public required `QUIZ` was created for a basic exercise; verify the resulting student path and active-course progress behavior. A required BASIC_EXERCISE must not lock the next step after the pathway implementation is updated.
5. Apply only to a verified staging target with a known database identity; never infer production readiness from static code or a successful local plan.
6. Verify API/FE reads, release receipt, idempotent rerun, and that a new pack digest archives the old Lesson while preserving its historical exercise attempts. Do not use retire as automated rollback; inspect its state effects before any manual use.

No migrations, database writes, or runtime tests were performed to create this document.

## 10. Source map

- Product constraints: `docs/product/prd.md` (Open Curriculum, Class Space, progress, and product-owner decisions).
- Route contract: `src/modules/content/interface/admin-content.controller.ts`.
- Manifest, plan, apply, retire, receipt: `src/modules/content/application/content-release.ts`.
- Pack schema, validation, materialization: `src/modules/content/application/content-pack.ts`.
- Legacy step generation and exercise/quiz types: `src/modules/lessons/application/pathway.ts`.
- Active course progress: `src/modules/progress/application/foundational-progress.service.ts`.
- Data models: `prisma/schema.prisma`.
- FE step types/rendering: `../nexalab-fe/src/lib/api.ts` and `../nexalab-fe/src/features/lessons/LessonDetail.tsx`.
- Repository layering and ownership: `docs/architecture/project-structure.md`, `AGENTS.md`, and `../nexalab-fe/AGENTS.md`.
