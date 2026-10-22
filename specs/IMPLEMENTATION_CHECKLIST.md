# Implementation Checklist — Content Tool Pilot

Checklist này bám theo Master Plan v5.4. Đánh dấu xong chỉ khi có artifact hoặc test evidence tương ứng.

## Trước khi implement

- [ ] Chốt BE/FE commit làm căn cứ; recheck Zod manifest, importer CLI, pathway, Open Curriculum response và component FE.
- [ ] Xác nhận quyền xử lý và xuất bản nguồn; chưa rõ quyền thì không ingest nguồn đó.
- [ ] Đặt `H_review_max` và ngưỡng OCR trước khi xem kết quả spike.
- [ ] Chọn 10–20 trang đại diện; ghi loại trang, trang có text layer, scan, bảng/hình/công thức.
- [ ] Thử native text trước, rồi MinerU local; ghi phiên bản, source URL/hash, cấu hình và giấy phép của code, từng model weight, dependency.
- [ ] Chốt người review thật cho bài baseline. Đủ 4 loại review; subject và rights là hai người khác nhau. Không dùng email/timestamp giả. Nếu chưa đủ reviewer, dừng baseline apply.
- [ ] Chỉ dùng `fixture` cho nội dung synthetic để thử plumbing ở staging; không dùng fixture để phát hành bài pilot.

## M1 — Tool local

- [ ] CLI tạo workspace/source inventory và lưu output trung gian local; không cần DB/R2 credentials.
- [ ] Mỗi block giữ source version, page locator, extraction method và file hash.
- [ ] ID pack/lesson/step/question/option ổn định qua export; không sinh lại theo wording, page offset hay lần chạy.
- [ ] Báo cáo HTML đối chiếu nguồn và kết quả; review log phân biệt người biên tập với người thực sự duyệt.
- [ ] Đo lỗi extraction, thời gian sửa theo loại mục, rework và vùng có mực không được OCR/layout box phủ.
- [ ] Thử heuristic render + mask OCR/layout boxes để gắn cờ vùng chưa phủ; giữ nếu tín hiệu hữu ích, bỏ nếu nhiễu.
- [ ] Không commit PDF/crop có hạn chế, credentials hoặc dữ liệu nguồn ngoài quyền.
- [ ] Export đúng manifest BE hiện hành; `plan` là validator cuối, không duy trì schema validator độc lập không cần thiết.

## M2a — BE pack/pathway và FE

- [x] Thêm `basicExercises` optional vào strict schema; legacy manifest không có field này vẫn parse.
- [x] Không đặt default `[]` trước canonical digest; golden fixture chứng minh digest manifest legacy giữ nguyên.
- [x] Map exercise trực tiếp vào `LessonStep.config` theo BASIC_EXERCISE; không đi qua `lesson.questions`/QUIZ.
- [x] Giữ `required: true` cho course evidence nhưng sửa pathway để exercise chưa hoàn thành không khóa bước sau.
- [x] BASIC_EXERCISE render/attempt được trong Open Curriculum; question/option IDs đi tới attempt ổn định.
- [x] QUIZ và assignment gating hiện có không đổi.
- [x] Chỉ đánh dấu hoàn tất sau unit/API/FE test; source code hiện tại có generic required-step gate nên chưa đạt sẵn.

## M2b — Release

- [ ] Kiểm tra đúng database/environment target trước plan/apply; không suy ra target từ tên file.
- [ ] `plan` không blocker và hiển thị digest/actions; dry-run không ghi dữ liệu.
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
