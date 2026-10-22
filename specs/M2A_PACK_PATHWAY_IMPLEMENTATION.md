---
title: 'M2a pack and pathway'
type: 'feature'
created: '2026-10-22'
status: 'done'
tool_baseline: '4dc61aa112fd6621676c217b197cbbd3e5177789'
backend_baseline: '48463ea39e147aecdf729a3eae7b1335d6649824'
frontend_baseline: 'c7fe8914a4e6fecb0737e562c8d6ba6319f9b3bc'
---

## Intent

Complete the M2a milestone from Lean v5.5 with the smallest compatible change: allow one optional authored basic-exercise step in a content pack, materialize it as the existing `BASIC_EXERCISE` runtime config, keep it required for evidence without gating the next pathway step, and prove the existing Open Curriculum UI can submit the authored question and option IDs. M2a code is complete; end-to-end integration against Lessons authored in the M1 UI remains pending.

## Boundaries

- Preserve the parsed digest of the legacy fixture that omits `basicExercises`.
- Keep `lesson.questions` and its required `QUIZ` behavior unchanged.
- Reuse the existing basic-exercise validator, attempt endpoint, FE component, release transaction, and database schema.
- Do not add migrations, release apply changes, course binding, assignment exercise submission, or staging claims.

## Tasks

- [x] Content Tool accepts and exports `lesson.basicExercises`, registers authored step/question/option IDs, and demonstrates the field in its synthetic fixture/report.
- [x] Backend strict pack schema accepts the optional field without a default, materializes a required `BASIC_EXERCISE`, and keeps the legacy digest golden value.
- [x] Pathway exposes sanitized exercise resources while an incomplete `BASIC_EXERCISE` does not lock a later step; QUIZ/LAB gates remain unchanged.
- [x] FE regression proves Open Curriculum renders the exercise and submits authored IDs through the existing attempt route.
- [x] Focused Tool, BE, and FE checks pass; authoritative BE dry-run accepts the new Tool fixture without `--apply`.

## Result

- Legacy parsed pack digest remains `7bb327dd47bf38b06784610c3964904c00a9995782e192a11c4b95d4dc005df9`.
- New Tool fixture export SHA-256 is `22f71eec9d9099ed79a0a1b901b49be2c10d5f4a646bb5703ae80196341ff271`.
- Backend dry-run returned `blockers: []` and `PLAN ok (dry run; nothing written)`.
- BE: 197 unit tests passed; lint and build passed. FE: lint/build passed and the focused four-test Playwright file passed. Tool: eight tests, compile, report, and export passed.

## Verification

- `uv run python -m unittest discover -s tests -v`
- `uv run nexalab-content export examples/synthetic-pilot`
- `uv run nexalab-content plan examples/synthetic-pilot --backend ../nexalab-be --target development`
- `npm test -- --run src/modules/content/application/content-foundation.test.ts src/modules/lessons/application/pathway.test.ts`
- `npm run lint` and `npm run build` in both changed TypeScript repositories as applicable.
- Focused Playwright: `npx playwright test tests/student-lessons-hub.spec.ts` with the configured local web server/browser.
