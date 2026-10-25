# KHTN 8 OCR Correction Checkpoint

**Status:** OCR REMEDIATION DEFERRED — not completed

**Checkpoint date:** 2026-10-25
**Next milestone:** P1 — SGK Source Viewer

## Current product and pipeline state

- **Published curriculum:** 47/47 KHTN 8 Lessons are published and visible in FE Open Curriculum. This is the BE release and FE runtime state verified on 2026-10-25.
- **Renderer:** The FE Lesson renderer fixes are complete and verified. Markdown/GFM headings, lists and tables render; inline and display KaTeX render in the Lesson body and objectives; duplicate projection of objective text was removed; valid source references resolve without displaying `PDF trang 0`; mobile layout was checked. FE production build, BE build and local-browser verification of the two affected published Lessons passed.
- **Commits:** FE `7fa3b33ab0c70f576da1574117d5689ab5da7221` (`fix(lessons): polish structured lesson rendering`) and BE `023ea4842e49959d468d6e3e5b3a784aa04fe8f6` (`fix(learning): correct structured lesson projection`). **Neither was pushed** as of this checkpoint: each local branch has no upstream/tracking branch, and no matching `origin` branch ref is present in the local checkout. Remote state was not freshly fetched for this checkpoint.
- **Content Tool local processing is a separate status:** the repository's `KHTN8_CONTENT_TOOL_PIPELINE_STATUS.md` reports partial local OCR coverage, stale processing reports and only four local Structured Lesson JSONs in `needs_review`. Those local processing artifacts do not represent the 47 published Lessons. Do not treat publication as proof that the whole-book OCR corpus has been reviewed or corrected.

## Verified OCR issues

The issue evidence below comes from saved page/block artifacts for source PDF SHA-256 `6dcda104a5b09d1395417afef9ac48630843e57dc53938412eada13a6fdfdbf1`, corroborated against the original PDF in the prior review. Page values use the stored `physicalPageIndex` / `pNNNN` source-page identifier. Printed-page labels are absent for most cited blocks, so no printed page is inferred. For compactness, each cited block ID omits the common prefix `sgk-khtn8-nxbgd-2026-`.

### Meaning and scientific terminology — review first

| Lesson | Source block / PDF page | Extracted text | Verified correction | Severity | Status |
|---|---|---|---|---|---|
| Bài 4 — Dung dịch và nồng độ | `p0022-b0002`, `p0022-b0005`, `p0022-b0006`, `p0022-b0009`; `p0023-b0014`–`p0023-b0019`; `p0024-b0004`–`p0024-b0008`, `p0024-b0011`, `p0024-b0015`, `p0024-b0017`, `p0024-b0023`–`p0024-b0024`, `p0024-b0026`; `p0025-b0008`, `p0025-b0010`, `p0025-b0015`, `p0025-b0017`–`p0025-b0019`, `p0025-b0021` (PDF physical indexes 22–25) | `nông độ` (repeated in the Lesson title, explanations and formula descriptions) | `nồng độ` | Medium — corrupts a core scientific term throughout this Lesson; the saved formula expressions themselves are not confirmed wrong | Open; source correction not applied |
| Bài 4 — Dung dịch và nồng độ | `p0022-b0011`, `p0023-b0002`, `p0023-b0003`, `p0023-b0011` (PDF physical indexes 22–23) | `bảo hoà` | `bão hoà` (book spelling) | Medium — repeated terminology in the definition and exercises | Open; source correction not applied |
| Da và điều hoà thân nhiệt ở người | `p0165-b0009`, `p0166-b0003` (PDF physical indexes 165–166) | `giữ ẩm` in advice for cold weather | `giữ ấm` | High — changes the meaning of health guidance | Open; source correction not applied |
| Da và điều hoà thân nhiệt ở người | `p0165-b0007` (PDF physical index 165) | `cho có thể` | `cho cơ thể` | Medium — changes the meaning of the sentence | Open; source correction not applied |
| Da và điều hoà thân nhiệt ở người | `p0166-b0003` (PDF physical index 166) | `đột ngọt` | `đột ngột` | Medium — changes the meaning of advice about sudden weather changes | Open; source correction not applied |
| Da và điều hoà thân nhiệt ở người | `p0163-b0014` (PDF physical index 163) | `da bản` | `da bẩn` | Medium — changes the meaning of a hygiene statement | Open; source correction not applied |

### Other verified spelling / OCR defects

| Lesson | Source block / PDF page | Extracted text | Verified correction | Severity | Status |
|---|---|---|---|---|---|
| Bài 4 — Dung dịch và nồng độ | `p0022-b0013` (PDF physical index 22) | `đữa khuấy` | `đũa khuấy` | Low — spelling of a listed lab item | Open; source correction not applied |
| Da và điều hoà thân nhiệt ở người | `p0164-b0015` (PDF physical index 164) | `Buốc 1` | `Bước 1` | Low — procedure-step spelling | Open; source correction not applied |
| Da và điều hoà thân nhiệt ở người | `p0165-b0008` (PDF physical index 165) | `mát mê` | `mát mẻ` | Low — spelling | Open; source correction not applied |
| Da và điều hoà thân nhiệt ở người | `p0166-b0011` (PDF physical index 166) | `giũ vệ sinh`; same block also has `giũ gìn` | `giữ vệ sinh`; `giữ gìn` | Low — OCR spelling; surrounding intent is clear | Open; source correction not applied |

### Formula and table defects

- **Scientific formulas:** No incorrect scientific formula has been independently verified in the available evidence. The renderer work addressed formula display, which is separate from validating formula content. In Bài 4, the stored percent-concentration and molarity expressions still require source-grounded review before any content patch; this checkpoint does not declare them corrected or fully approved.
- **Tables:** No malformed or scientifically incorrect source table has been independently verified in the available evidence. Table rendering passed FE verification; that does not validate OCR table contents.
- Do not promote unverified formula/table concerns into corrections. Compare the affected source block and page image before changing them.

## Data and release boundary

Published Lesson data was **NOT corrected**. No OCR page records, Structured JSONs, database records, FE or BE files were changed as part of this checkpoint. The issue rows document candidate corrections only; no source content patch or new Content Release exists.

## Deferred remediation plan

When OCR-tool work resumes for a future book import:

1. Evaluate Gemini-assisted OCR quality improvement as an assistive proposal path, retaining the original extraction and provenance.
2. Validate proposed text against the source PDF at page/block level, prioritizing scientific formulas, units, tables, procedures, health guidance and meaning-changing OCR; require human review for accepted changes.
3. Apply approved corrections as a versioned content patch through the existing content workflow. Preserve the raw OCR and review history; do not mutate published records directly.
4. Validate the patched Structured content and provenance, then issue a reviewed/versioned content release through the existing release workflow.

This remediation is **DEFERRED**, not done. The next milestone is **P1 — SGK Source Viewer**; OCR-tool improvements are revisited when preparing the next book import.
