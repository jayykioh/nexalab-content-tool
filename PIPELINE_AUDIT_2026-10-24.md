# Content Tool → BE: kết quả kiểm tra ngày 24/10/2026

## Kết luận

KHTN 9 có đủ 51 Structured JSON và OCR của 218 trang. Chưa có manifest thật đủ điều kiện đưa vào BE để phát hành. `accepted` trong Studio là trạng thái cục bộ; không chứng minh kiểm chứng khoa học, outcome hoặc duyệt phát hành.

## Lỗi kỹ thuật đã sửa

1. Candidate gán cứng `grade=8`: dùng metadata lớp rõ ràng; import/UI hỗ trợ lớp 8/9, không suy đoán lớp khi thiếu. Workspace KHTN 9 đã đặt lớp 9 theo tên sách.
2. Tạo Structured JSON bỏ phần mở đầu/mục tiêu và cắt mỗi mục còn 2–3 claim: giữ toàn bộ section OCR trong lần tạo mới; summary vẫn riêng. Xuất `sourceReading` đầy đủ từ OCR hiện tại cho cả các bản cũ. Giữ nguyên `learningContent` đã chỉnh để tránh ghi đè công sức biên soạn. Các bản cũ vẫn cần đối chiếu và hợp nhất với `sourceReading`, không tự coi là đã sửa nội dung khoa học.
3. Kiểm tra trước đây có thể trả `valid` khi thiếu file JSON: nay thiếu file là lỗi.
4. Acceptance/export chỉ so hash trong snapshot, có thể bỏ sót OCR vừa sửa: nay đối chiếu với OCR đang lưu; chặn acceptance/export cũ. Validator cũng kiểm tra nguồn hiện tại.
5. BE không nhận `lesson.basicExercises`: thêm schema và materialization thành bước BASIC_EXERCISE bắt buộc ở vị trí 30, giữ question/option ID; runtime step ID được namespace theo version Lesson và ID bài tập. Không sinh QUIZ cho bài tập này.
6. Thêm `BE-NexaLab/scripts/validate-content-handoff.ts`: kiểm tra schema thật và materialize bước học offline, không mở kết nối DB. Kết quả này không thay thế BE plan.

## Kết quả dữ liệu thật

- Candidate: `workspaces/khtn9-m1-real/exports/sgk-khtn9-kntt-be-candidate.json`.
- Nội dung: `workspaces/khtn9-m1-real/exports/structured/` (51 bài, có sourceReading, learningContent, nguồn và cảnh báo).
- Báo cáo BE: `workspaces/khtn9-m1-real/exports/be-contract-validation.json`.
- 51/51 bài thiếu domain, subjectId, outcomeCodes và source.accessedAt; 440 knowledge unit chưa có outcomeCodes.
- Bài 01: claim tại knowledgeUnits[23].claims[0] ngắn hơn 5 ký tự. Bài 47: knowledgeUnits[14].claims[1] dài hơn 1.000 ký tự. Cần biên tập theo nguồn; không cắt bỏ nội dung chỉ để qua schema.
- Sau khi qua schema, vẫn cần BE kiểm tra outcome thật tồn tại, quyền nguồn, reviewer, asset và target DB. Mã nội bộ trong release-prep không được mặc nhiên coi là outcome hợp lệ của BE.
- 3 pack cũ trong `packs/` là bản soạn riêng, không tự đồng bộ với 51 Structured JSON. Không dùng chúng như bản xuất mới nhất của cả sách.
- Nhánh Lab hiện có proposal theo model/outcome đã xác minh; chưa có bằng chứng chạy golden cases cho sách này, chưa phải Lab Blueprint đã duyệt để phát hành.

## Kiểm tra đã chạy

- Python: 25 test đạt, bao gồm regression lớp 9, giữ section đầy đủ, thiếu JSON và stale OCR.
- BE: 35 test content/pathway đạt; TypeScript lint và build đạt.
- Manifest synthetic thực sự xuất từ Content Tool qua schema BE: đạt, materialize READING, VIDEO, BASIC_EXERCISE. Đây là fixture, không phải bằng chứng phát hành sách thật.
- Đã backup books.json và exports trước khi refresh tại `workspaces/khtn9-m1-real/backups-pipeline-20261024-160442/`.
- Chưa chạy DB plan/apply, migration hoặc E2E student; chưa ghi database.

## Chạy lại

Tại Content Tool:

```powershell
.venv/Scripts/python.exe -m nexalab_content_tool export-structured workspaces/khtn9-m1-real --book sgk-khtn9-kntt
.venv/Scripts/python.exe -m nexalab_content_tool validate-structured workspaces/khtn9-m1-real --book sgk-khtn9-kntt
```

Tại BE:

```powershell
npx tsx scripts/validate-content-handoff.ts '../NexaLAB_Content tool/workspaces/khtn9-m1-real/exports/sgk-khtn9-kntt-be-candidate.json' '../NexaLAB_Content tool/workspaces/khtn9-m1-real/exports/be-contract-validation.json'
```

Chỉ chuyển sang release authoring sau khi hoàn thiện nội dung và mapping. `export` dùng packs/release.json cùng evidence, registry và review log; `export-structured` tạo candidate phục vụ biên soạn. BE plan là gate tiếp theo sau khi có manifest hợp lệ và target đã xác định.
