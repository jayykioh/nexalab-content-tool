# M0a Extraction Spike — KHTN 8

**Run date:** 2026-10-22  
**Scope:** one locally provided KHTN 8 PDF, as directed by the user. The second book and two-book extrapolation are deferred until the user imports it.  
**Processing:** local only. No MinerU remote service and no Gemini. This local evaluation does not change the source's unresolved publishing rights.

## Source and sample

- File: `D:\coding\nexalab-be\tools\nexalab-ingest\out\nxbgd-khtn8-20261015\assets\sgk-khtn.pdf`
- Size: 25,151,587 bytes; SHA-256: `6dcda104a5b09d1395417afef9ac48630843e57dc53938412eada13a6fdfdbf1`
- 200 PDF pages; 0 pages have native text blocks. This is a scanned-image PDF, so a native-text-versus-OCR CER/WER comparison is not possible on this source.
- Stratified OCR sample: PDF pages 7–8, 27–28, 47–48, 67–68, 87–88, 107–108, 127–128, 147–148, 167–168, and 187–188. This covers the book at regular intervals.
- A first 20-page exploratory run was also performed but is excluded from the tier comparison because it was not stratified.

## Runtime and results

MinerU `4.0.12`, Python `3.12.13`, local `mineru-kit parse`, `--ocr-mode ocr`; output is an ignored local ZIP. Small-model inference used ONNX Runtime CPU; the standard tier selected the local llama.cpp VLM engine. First-run model download time is excluded from the comparison. The three stratified runs used the same 20 pages.

| Tier | Inference time | End-to-end run | Inference speed | Observed result |
|---|---:|---:|---:|---|
| flash | 64.5 s | 74.3 s | 0.310 pages/s | Fastest; drops layout/formula content and Vietnamese diacritics in reviewed text. |
| basic | 121.9 s | 131.5 s | 0.164 pages/s | Faster than standard; substantial diacritic loss, damaged formulas and five dropped-block warnings across four sampled pages. |
| standard | 213.3 s | 232.3 s | 0.094 pages/s | Slowest; best of the three for reviewed Vietnamese paragraphs and equations, but still has material OCR errors and requires human review. |

At the observed standard-tier inference rate, 200 pages would take approximately 35.5 minutes of model inference; using the measured end-to-end rate gives approximately 38.7 minutes after model weights are cached. This is a rough single-book estimate from 20 sampled pages, not a full-book benchmark. It excludes human review and page-to-page variation.

## Quality review

The source page and OCR result were visually compared in the new local Review Workbench. On the sampled chemistry page (PDF page 8), standard misread `TRONG` as `TRÔNG`, and made errors such as `nhãn` → `nhân`, `nồng độ` → `nông độ`, and `đựng` → `dụng/đụng`. Some errors affect safety instructions, so OCR output must not flow directly into lessons. On the sampled chemistry equations page (PDF page 27), standard preserved several equation structures better than basic and flash.

No gold transcription was present in this image-only PDF, so CER/WER and a statistically meaningful error rate were not reported. No human reviewer time has yet been collected; `H_review_est` remains unknown pending review decisions in the Workbench. Per user direction, there is no fixed `H_review_max`; optimize review effort and report observed time and throughput instead.

## Decision

- Use MinerU standard as the current local OCR candidate for content that may feed lessons; it is the best quality observed in this sample.
- Keep all OCR blocks in human review. Use flash/basic only for quick previews or indexing; do not treat their result as accepted content.
- Do not send source pages to Gemini until its separate rights, retention, training, and region gate is resolved.
- Do not publish this source: the NexaLab ingest manifest still says `releaseEligible: false` and the source rights status is unresolved.
- M0a's engine/throughput comparison for this one source is complete. Human review-time calibration, a gold-text accuracy measurement, and a second-book study remain explicit follow-up evidence, not claimed as completed.

## Local import UI verification

The loopback Workbench now handles the complete local operator path: select a PDF, choose tier and sample/full scope, confirm local-processing rights, run the installed `mineru-kit` subprocess, then compare OCR blocks with rendered source pages and save review decisions. The 200-page KHTN 8 PDF was uploaded through `/api/import`; MinerU `standard` completed a stratified 20-page sample. `/api/state` returned `ready=true`, 20 OCR pages, and 200 source pages; `/api/page/7` returned OCR blocks and `/source/7` returned the rendered source PNG. Review decisions and elapsed time are recorded; reviewer identity is not collected. This OCR review is not a subject, rights, or baseline release approval.

Imported source, OCR ZIP, rendered pages, and review JSON are stored only under the ignored workspace `.local/` directory. The loopback UI is bound to `127.0.0.1`; no Gemini, database, or remote OCR service was used.

## Reproduction

```powershell
cd D:\coding\nexalab-content-tool
$mineru = 'C:\Users\FPT\AppData\Local\Temp\nexalab-mineru-m0a\Scripts\mineru-kit.exe'
$pdf = 'D:\coding\nexalab-be\tools\nexalab-ingest\out\nxbgd-khtn8-20261015\assets\sgk-khtn.pdf'
& $mineru parse $pdf --pages '7-8,27-28,47-48,67-68,87-88,107-108,127-128,147-148,167-168,187-188' --output 'workspaces\m0a-nxbgd-khtn8\mineru-stratified-20' --format zip --tier standard --ocr-mode ocr
```

Run the local review UI for that output:

```powershell
uv run nexalab-content review 'workspaces\m0a-nxbgd-khtn8\workspace' `
  --pdf 'D:\coding\nexalab-be\tools\nexalab-ingest\out\nxbgd-khtn8-20261015\assets\sgk-khtn.pdf' `
  --mineru-zip 'workspaces\m0a-nxbgd-khtn8\mineru-stratified-20\sgk-khtn.zip'
```

Or start the guided import UI (install MinerU 4.x locally first):

```powershell
$env:NEXALAB_MINERU_KIT = 'C:\Users\FPT\AppData\Local\Temp\nexalab-mineru-m0a\Scripts\mineru-kit.exe'
uv run nexalab-content studio 'workspaces\m0a-nxbgd-khtn8\workspace' --port 8765
```

MinerU references: [Quick Start](https://github.com/opendatalab/MinerU/blob/master/docs/en/quick_start/index.md), [Tiers and Runtimes](https://github.com/opendatalab/MinerU/blob/master/docs/en/usage/tiers.md), [License](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md). Review exact model-weight and transitive dependency licenses before distributing the configured tool or deploying it beyond local evaluation.
