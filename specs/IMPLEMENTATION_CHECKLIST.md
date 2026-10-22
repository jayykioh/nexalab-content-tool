# Implementation Checklist — Content Tool Pilot

Checklist này bám theo canonical SPEC và Master Plan v5.5. “Done” chỉ áp dụng cho đúng phạm vi và evidence ghi ở đây.

## Trạng thái tổng thể — 2026-10-22

| Mốc | Trạng thái hiện tại | Bằng chứng / phần còn thiếu |
|---|---|---|
| M0a — OCR feasibility | **Hoàn tất kỹ thuật cho KHTN 8** | Đã so sánh flash/basic/standard trên 20 trang, chọn standard, và chạy PDF 200 trang / OCR mẫu 20 trang end-to-end qua UI. Chưa đo thời gian review người dùng hoặc CER/WER (không có gold text). Đây chứng minh OCR feasibility, không chứng minh book-to-Lesson. Chi tiết: `specs/M0A_SPIKE_REPORT.md`. |
| M1 — Local book-to-Lesson workflow | **Chưa đạt product DoD** | UI local đã import/OCR/review, resume, tạo Lesson draft và proposal trích xuất từ OCR accepted, giữ source block IDs, BASIC_EXERCISE, export blockers và BE plan dry-run. Synthetic browser flow và unit tests đã chạy. Chưa có 2–3 Lesson từ nguồn thật đủ quyền, outcome/subject đã xác minh, formal reviews và BE plan không blocker; proposal vẫn cần người biên soạn kiểm tra. |
| M2a — Pack/pathway | **Code hoàn tất; tích hợp M1 pending** | `basicExercises`, materialization và pathway code đã có unit/API/FE coverage. Chưa chứng minh Lesson tạo từ M1 UI giữ IDs và chạy qua Open Curriculum end-to-end. |
| M2b — Release | **Code có; target/apply runtime chưa xác minh** | Synthetic dry-run từng không blocker và không ghi, nhưng BE đang trỏ Supabase từ xa chưa xác định môi trường. Chưa apply hoặc kiểm receipt/idempotency trên DB staging đã định danh. |
| M3 — Staging E2E | **Chưa chạy** | Chỉ bắt đầu sau M1/M2a integration, quyền/review baseline hợp lệ và NexaLab preflight trên target staging. |

**Vì sao workflow chưa xong:** các phần trước đây được chia theo thành phần kỹ thuật (CLI package/export, OCR spike, BE pathway) và có DoD riêng, không yêu cầu một operator đi xuyên suốt import → OCR correction → Lesson authoring → BE plan. Do đó “M0a done” và “M2a done” chỉ là các lát kỹ thuật; M1 vertical flow vẫn là việc chính còn thiếu. Thứ tự hoàn tất từ nay: M1 → tích hợp M2a → M2b → M3. OCR Workbench không yêu cầu tên reviewer; formal BE release approval vẫn giữ nguyên.

## Trước khi implement

- [x] Chốt BE/FE commit làm căn cứ; recheck Zod manifest, importer CLI, pathway, Open Curriculum response và component FE.
  - Evidence: BE `99fca447081e95efcc369ca1ddaf1af52d395b53`; FE `0d7738e19959e094b7f5bb7b57adaf9d89fb8612`; Tool `d658883dfc26ad25d1bb446657283addd3916d99`.
- [ ] Xác nhận quyền xử lý và xuất bản nguồn; chưa rõ quyền thì không ingest nguồn đó.
- [x] Theo chỉ đạo người dùng, không đặt `H_review_max` cố định; tối ưu review effort và thu thập thời gian thực tế trong Workbench.
- [x] Chọn 20 trang phân tầng cho KHTN 8; PDF scan image-only nên không có text layer để làm CER/WER baseline.
- [x] Thử MinerU local trên cùng sample ở flash/basic/standard; ghi phiên bản, hash, cấu hình và runtime. Cần hoàn tất rà soát license chính xác của model weights/dependencies trước khi phân phối.
- [ ] Thu thập thời gian review/rework từ operator thực tế trên Workbench; không thay thời gian người dùng bằng synthetic/agent timing. Không có cap giờ cố định; dữ liệu này tối ưu thao tác và không phải release approval.
- [ ] Lập gold transcription hoặc chọn nguồn có native text để tính CER/WER nếu cần đo lỗi định lượng.
- [ ] Chốt người review thật cho bài baseline. Đủ 4 loại review; subject và rights là hai người khác nhau. Không dùng email/timestamp giả. Nếu chưa đủ reviewer, dừng baseline apply.
- [ ] Chỉ dùng `fixture` cho nội dung synthetic để thử plumbing ở staging; không dùng fixture để phát hành bài pilot.

## M1 — Local book-to-Lesson workflow

- [x] Import PDF qua UI, chọn sample/full, chạy MinerU local, đối chiếu trang và OCR, lưu review actions/elapsed time mà không thu reviewer identity.
- [x] Hiển thị tiến độ theo stage của từng chương và lỗi/blocker; giữ checkpoint để tiếp tục workspace sau khi đóng/restart. Browser acceptance đã restart Studio thật và xác nhận lại 11/11 trang accepted, 3/3 Lesson draft cùng dashboard OCR/review/Lesson cho cả Bài 4–6.
- [ ] Xử lý mixed native text / scan; giữ source, version, page/region locator, method và hashes cho mọi block dùng trong Lesson.
- [ ] Sửa/chấp nhận/đánh dấu OCR block trong UI; giữ version history/original. Gemini LaTeX proposal (khi rights/provider gate đã mở) giữ original, hiện diff, và chỉ áp dụng theo thao tác operator.
- [ ] Tạo/sửa Lesson trong UI với stable pack/lesson/step/question/option IDs, source evidence, outcome/curriculum mapping, media và basic exercises.
- [ ] Không yêu cầu tự viết/chỉnh manifest JSON để tạo Lesson; UI báo lỗi thiếu trường/evidence và cho sửa ở đúng bước.
- [ ] Export deterministic manifest và hiển thị BE `plan` blockers; chỉ gọi plan không ghi dữ liệu.
- [x] Không commit PDF/crop hạn chế, credentials hoặc source data trái quyền.

Evidence available: M0a UI run on 200-page KHTN 8 PDF with 20-page MinerU sample; CLI file-workspace/export slice and synthetic BE dry-run. The current local UI also produces extractive section, summary, and per-section knowledge-unit proposals from accepted OCR with stable source block references. A real browser acceptance run now covers import, MinerU extraction, manual correction, accepted-page resume, three reviewed Lesson drafts, BASIC_EXERCISE authoring, and aggregate release-blocker reporting. These checks establish the local technical Book-to-Lesson pilot, not M1 product DoD: publication rights, official curriculum mapping, formal reviews, and a clean BE plan remain unverified. BE config used in the prior dry-run points to remote Supabase with an unverified project/environment; no apply was performed.

Real-source pilot (2026-10-22): with the operator's explicit permission for **local processing only**, imported `SGK Khoa học tự nhiên 8-mau.pdf` (200 image-only PDF pages, SHA-256 `29e4ccd95130cb38cfe9a696fe2edd5e0e66496ab9761c8a60ac5cb5803c3ffb`) through the studio at port 8766 into ignored `workspaces/khtn8-m1-real`. Defined Bài 4 (PDF 22–25 / print 20–23), Bài 5 (PDF 26–29 / print 24–27), and Bài 6 (PDF 30–32 / print 28–30) through the same UI. MinerU 4.0.12 extracted all 11 mapped pages; every page was visually compared with the rendered source, corrected through the OCR Review UI, and saved as `accepted`. The Lesson UI then produced and saved three drafts with 13/11/8 source-linked sections and 13/11/8 knowledge units respectively, stable source block IDs, and one BASIC_EXERCISE per Lesson. Aggregate export validation reported the expected eight release blockers for each draft (24 total): unverified outcome, subject, publication license/source URL, and editorial/subject/rights/accessibility reviews. Local-processing permission is **not** publication permission. Official subject/outcome mapping, publication rights, four real formal reviews, and a verified BE target remain absent; therefore M1 product DoD and release eligibility are still open even though the local technical pilot is complete.

Ink-coverage experiment (2026-10-22): the planned cheap comparison of dark rendered pixels against expanded OCR bounding boxes was sampled on all 11 pilot pages. It was not retained as a blocker because decorative title artwork and non-text graphics produced severe false positives on pages 22, 26 and 30 (roughly 56–61% apparently uncovered), while mostly textual pages appeared near 100% covered. Visual source/OCR review remains the reliable gate until the heuristic can distinguish text from artwork.

## M2a — BE pack/pathway và FE

- [x] Thêm `basicExercises` optional vào strict schema; legacy manifest không có field này vẫn parse.
- [x] Không đặt default `[]` trước canonical digest; golden fixture chứng minh digest manifest legacy giữ nguyên.
- [x] Map exercise trực tiếp vào `LessonStep.config` theo BASIC_EXERCISE; không đi qua `lesson.questions`/QUIZ.
- [x] Giữ `required: true` cho course evidence nhưng sửa pathway để exercise chưa hoàn thành không khóa bước sau.
- [x] BASIC_EXERCISE render/attempt được trong Open Curriculum; question/option IDs đi tới attempt ổn định.
- [x] QUIZ và assignment gating hiện có không đổi.
- [x] Chỉ đánh dấu hoàn tất sau unit/API/FE test; M2a focused tests verify the BASIC_EXERCISE pathway and preserve existing QUIZ/assignment gates.

## M2b — Release

- [ ] Kiểm tra đúng database/environment target trước plan/apply; không suy ra target từ tên file.
  - Evidence: cấu hình BE hiện tại đặt DB URLs tới Supabase từ xa trong khi `APP_ENV=development`; project/environment cụ thể chưa xác minh. `scripts/plan-local.ps1` nay chặn host không phải loopback. Lệnh dry-run trước đó là read-only, không apply.
- [x] `plan` không blocker và hiển thị digest/actions; dry-run không ghi dữ liệu.
  - Evidence: dry-run output reported target/environment `development`; digest `d577aa353617155850b71efd69a4758310c6a8d5fb715b892bad127170fa171a`; pack `fixture-khtn8-local-reading` action `new-version`, version `1`, no blockers; CLI reported `nothing written`. Follow-up config inspection found the BE DB URLs point to remote Supabase, so this was not verified as a local DB run and the actual database identity remains unknown.
- [ ] Apply bằng `npm run content:release` trong môi trường BE được kiểm soát; không thêm route HTTP cho MVP.
- [ ] Giữ guard: initiator active; baseline approver ADMIN active và khác initiator.
- [ ] Baseline reviews gắn người thật; email CLI không được tính là xác thực reviewer.
- [ ] Kiểm tra transaction, receipt và audit; cùng target/digest trả receipt cũ.
- [ ] Không dùng `retire` như rollback tự động; thao tác thủ công chỉ sau khi kiểm tra mọi pack bị ảnh hưởng.

## M3 — Staging E2E

- [ ] Preflight riêng của NexaLab hoàn tất trước staging apply/expose.
- [ ] Import 2–3 Lesson baseline đã đủ rights/review; kiểm tra Open Curriculum list/detail.
- [ ] Thử BASIC_EXERCISE, bỏ qua exercise và mở bước kế tiếp; kiểm tra attempt lưu đúng ID.
- [ ] Sửa một pack để tạo digest chưa từng apply rồi apply version mới.
- [ ] Xác nhận version/Lesson cũ được archive nhưng giữ lại; attempts cũ còn nguyên và gắn đúng step, không bị chuyển/xóa.
- [ ] Xác nhận Lesson/version mới hiển thị đúng; cùng digest retry không nhân đôi.
- [ ] Không tuyên bố course progress đã cập nhật; course binding ở scope riêng.
- [ ] Ghi lại lỗi, receipt, API response và test run; không đánh dấu production-ready từ staging.

## NexaLab preflight — ngoài scope Content Tool

- [ ] Read-only: xác minh target, đếm tổng `TextbookSourceChunk` và số `studentFacing=true`; đối chiếu con số 47.
- [ ] Nếu có dòng bật, xác minh target rồi chỉ cập nhật dòng đó về `false`; ghi số trước/sau và xác nhận lại.
- [ ] Xác minh Supabase Data API, grants và RLS trên đúng môi trường.
- [ ] Đếm duplicate `StepProgress` với `assignmentId IS NULL` trước khi đề xuất migration.
- [ ] Audit `printedPageLabel` (trang in) tách biệt `physicalPageIndex` (trang PDF vật lý, 1-based).
- [ ] Không đưa thay đổi DB/migration này vào repository Content Tool.
