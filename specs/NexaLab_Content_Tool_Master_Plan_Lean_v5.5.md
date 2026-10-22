# NexaLab Content Tool — Lean Master Plan v5.5

> **Ngày:** 22/10/2026  
> **Trạng thái:** Scope đã đồng bộ với canonical SPEC ngày 22/10/2026; book-to-Lesson workflow chưa hoàn tất. Đây không phải xác nhận production readiness.  
> **Cơ sở đối chiếu:** NexaLab BE commit `48463ea39e147aecdf729a3eae7b1335d6649824`; kiểm tra lại source ở commit bắt đầu implement.

## Mục tiêu

Tạo tool local có UI hướng dẫn operator đi hết luồng từ nhập sách tới package 2–3 Lesson, rồi dùng luồng release hiện có của NexaLab để hiển thị nội dung trong Open Curriculum. CLI chỉ dành cho tác vụ vận hành BE `plan`/`apply` và xử lý lặp lại; người dùng không phải tự cấu hình manifest JSON để biên soạn Lesson.

```text
Tài liệu được phép xử lý → tool local: extract/review/export → BE content:release plan/apply
                                                                  ↓
                                                    Lesson → Open Curriculum
```

BE tiếp tục là nguồn sự thật cho manifest, quyền, validation, digest, lưu trữ và phát hành. Tool không kết nối DB, không giữ credentials và không tự tạo hoặc sửa nội dung chuyên môn.

## Quyết định phạm vi

**Trong pilot**

- Một operator dùng UI local để import một hoặc nhiều PDF, chọn sample/full OCR, theo dõi trạng thái theo chặng, tiếp tục workspace sau khi dừng, review/correct OCR cạnh nguồn, và biên soạn Lesson bằng UI. Không yêu cầu nhập tên reviewer cho OCR QA.
- Native text trước; dùng MinerU local cho scan/layout. M0a đã benchmark MinerU 4.0.12 trên sample KHTN 8; runtime/model phải được pin, MinerU vẫn là cài đặt riêng chứ chưa được đóng gói cùng tool. Gemini chỉ là gợi ý sửa LaTeX/công thức, mặc định tắt cho tới khi quyền truyền nguồn và policy provider được xác nhận; luôn giữ bản gốc và cần operator áp dụng rõ ràng.
- Xuất manifest đúng schema BE đang nhận; UI hiển thị kết quả BE `plan`. `apply` tiếp tục qua đường `content:release` hiện có trong môi trường BE được kiểm soát.
- Thêm mapping riêng cho `basicExercises` vào `LessonStep.config` kiểu `BASIC_EXERCISE`, giữ ID ổn định và không khóa bước học kế tiếp.
- Đưa Lesson vào Open Curriculum. Course membership và mẫu số tiến độ course **không thuộc pilot**.

**Để sau pilot:** course-version activation, Lab authoring UI, asset upload/promotion đa môi trường, rollback tổng quát, multi-operator/concurrency, normalize/xóa legacy schema. Lesson editor hẹp và stage tracker cho một sách thuộc luồng pilot, không phải CMS/dashboard tổng quát.

Open Curriculum hiện lấy Lesson published/shared có pack version released, không đọc course membership. Vì vậy bài có thể xuất hiện trong catalog mà không cần `FoundationalCourseVersion`; nhưng tiến độ course sẽ không tính các bài này cho tới khi có bước binding riêng. Chỉ mở course binding nếu yêu cầu pilot bắt buộc bài nằm trong mẫu số tiến độ.

## Hợp đồng BE cần implement

Đã có ở snapshot: `POST /admin/releases/plan` và `POST /admin/releases/:id/retire`; `applyRelease()` chạy trong application/CLI path, nhưng chưa có HTTP apply route. `npm run content:release` gọi `scripts/content-release.ts`. Baseline yêu cầu initiator là tài khoản active; approver là ADMIN active và khác initiator. Email CLI được tra cứu trong DB, không chứng minh người đó đã đăng nhập/phê duyệt độc lập.

**Gate người duyệt là blocker của bài thật:** baseline bắt buộc có editorial, subject, rights, accessibility; reviewer phải là TEACHER/ADMIN active; subject và rights phải là hai người khác nhau. Code không đòi bốn người riêng, nhưng cả bốn review phải thật; tối thiểu cần người review chuyên môn và một người khác thực sự xác nhận quyền nguồn. Không điền tên/email/timestamp của người chưa review để qua gate. Một dev đứng một mình không thể tuyên bố đủ review subject và rights. Trước M2b, chốt người thật sẽ review; nếu chưa có thì dừng apply baseline. `fixture` chỉ dùng nội dung synthetic để thử plumbing trên staging: gate vẫn bắt đủ bốn review và subject khác rights, chỉ bỏ kiểm tra reviewer có tài khoản active; fixture không được đưa vào pilot/production.

1. **M2a — pack mapping:** thêm `basicExercises` tùy chọn, strict schema, map trực tiếp sang `BASIC_EXERCISE` config hiện có. Không đưa practice vào `lesson.questions` vì đường đó sinh `QUIZ`. Dùng ID authored ổn định cho step/question/option; giữ `required: true` để course progress có thể tính evidence sau này.
2. **M2a — tương thích:** schema cũ không có `basicExercises` phải tiếp tục parse và giữ nguyên digest cũ. Không gán default `[]` trước digest/canonicalization. Không cần migration dự kiến vì config là JSON.
3. **M2a — hành vi học:** hiện `buildPathwaySteps()` khóa các step sau bất kỳ required step nào chưa hoàn tất. Sửa điều kiện để BASIC_EXERCISE vẫn là evidence required cho course progress nhưng không khóa step tiếp theo; giữ nguyên gate QUIZ/assignment. Xác minh cả API Open Curriculum và luồng pathway/FE.
4. **M2b — phát hành:** dùng `content:release` CLI hiện có, dry-run trước, apply từ môi trường BE được kiểm soát. Không thêm HTTP apply route trong MVP. Giữ guard initiator/approver như code; chỉ apply bài thật khi đủ reviewer thật ở gate baseline.
5. **Retire/recovery:** không gọi retire như rollback tự động trong pilot. Source hiện tại không kiểm tra release còn là head trước khi retire và có thể phục hồi version đã supersede. Sai nội dung được sửa bằng release mới; retire chỉ dùng thủ công sau khi kiểm tra trạng thái toàn bộ pack bị ảnh hưởng. Nếu muốn dùng retire trong flow, phải thêm kiểm tra từng pack: version hiện released phải đúng version do release mục tiêu tạo; nếu không thì block.

**Idempotency đã biết:** cùng target + digest đã apply trả receipt cũ; không kích hoạt lại version lịch sử. Muốn khôi phục nội dung cũ không apply lại manifest cũ; theo pilot hãy tạo release sửa nội dung. Cần kiểm tra hành vi này trong staging trước khi viết hướng dẫn vận hành.

## Review và quyền nguồn

- Chỉ xử lý tài liệu có quyền lưu, trích xuất và xuất bản phù hợp. OCR/biên tập không tạo quyền sử dụng.
- Thử MinerU trước trên mẫu trang đã chọn. Kiểm tra giấy phép của đúng bản code, từng model weight và dependency đi kèm; pin phiên bản/nguồn tải. Chỉ thử engine khác nếu MinerU không đạt ngưỡng chất lượng/tốc độ đã đặt trước.
- Báo cáo nối nội dung cuối với source/version/page/locator; lưu các thao tác OCR, lịch sử, elapsed time và hash nhưng không hỏi/ghi reviewer identity. Đây không phải baseline approval. Formal release review/authentication vẫn theo contract BE; không dùng OCR action thay editorial/subject/rights/accessibility approval.
- Theo chỉ đạo người dùng 2026-10-22, spike ban đầu chỉ dùng KHTN 8 và không đặt `H_review_max` cố định. Tối ưu giờ review, ghi thời gian thực tế theo loại trang/block, đo rework; chỉ ngoại suy sách thứ hai sau khi người dùng import. Không thay reviewer thật bằng agent timing. M1 thử một kiểm tra rẻ: render trang, so vùng có mực với các OCR/layout boxes và gắn cờ vùng không được phủ. Đây chỉ là cảnh báo để người review kiểm tra, không tự sửa nội dung; giữ lại nếu thử mẫu cho kết quả hữu ích, bỏ nếu quá nhiễu.
- PDF, crop, dữ liệu hạn chế, API key và DB/R2 credentials không vào Git.

## Mốc thực hiện

| Mốc | Việc | Hoàn tất khi |
|---|---|---|
| **M0a — OCR feasibility** | MinerU local tier comparison, source/hash/runtime và Review Workbench cho KHTN 8 | **Hoàn tất kỹ thuật cho một sách:** standard được chọn; sample phân tầng 20/200 trang chạy qua UI. Human review-time calibration và gold-text CER/WER chưa có; đây không phải luồng book-to-Lesson hoàn chỉnh. |
| **M1 — Local book-to-Lesson workflow** | UI import, stage progress/resume, native text/MinerU, OCR correction, optional rights-gated Gemini LaTeX proposals, UI Lesson authoring, stable evidence/IDs, deterministic export và BE plan | Operator tạo 2–3 Lesson từ nguồn được phép hoàn toàn qua UI; không sửa manifest JSON bằng tay; BE `plan` không blocker; Gemini tắt vẫn chạy được. |
| **M2a — Pack và pathway integration** | `basicExercises` schema/mapping, ID ổn định, không khóa pathway; fixture manifest cũ và mới | Code hiện có; Lesson do UI M1 tạo giữ IDs; exercise không khóa bước sau; QUIZ/assignment không đổi. |
| **M2b — Release** | Dùng CLI hiện hữu; chốt reviewer thật, target/environment và audit receipt | Plan không blocker; apply atomic; rerun cùng digest trả receipt cũ; review và approver gates được đáp ứng trung thực |
| **M3 — Staging E2E** | Import 2–3 Lesson; sửa một pack để tạo digest chưa từng apply rồi apply; đọc qua Open Curriculum | Student đọc bài, làm practice và đi tiếp; version/Lesson cũ được archive nhưng giữ lại, attempts cũ còn gắn đúng step và không bị chuyển/xóa; Lesson mới đúng; course progress không bị tuyên bố đã cập nhật |

## Điều kiện NexaLab ngoài scope repo Tool

Đây là preflight riêng cho môi trường NexaLab trước khi staging apply/expose; không phải milestone hay story của Content Tool, và không chặn extraction/tool local. Bắt đầu bằng truy vấn chỉ đọc để đếm tổng số `TextbookSourceChunk` và số dòng `studentFacing=true` (đối chiếu con số 47). Nếu có dòng bật, xác minh database/environment rồi đặt riêng các dòng đó về `false`, ghi số dòng trước/sau; sau đó xác minh Data API/grants/RLS. Riêng NexaLab, kiểm tra duplicates `StepProgress` có `assignmentId IS NULL` trước khi cân nhắc migration; audit `printedPageLabel` (trang in) và `physicalPageIndex` (trang PDF vật lý, 1-based). Không thay đổi DB trong task Content Tool.

## Definition of Done

1. Tool xuất 2–3 manifest; BE `plan` chấp nhận không còn blocker.
2. Manifest legacy không có `basicExercises` vẫn hợp lệ và giữ digest; manifest mới giữ ID qua export.
3. Tests và staging E2E chứng minh practice xuất thành BASIC_EXERCISE, hiện đúng ở FE, không thành QUIZ, không khóa bước tiếp theo; assignment flow hiện tại không đổi.
4. Apply staging dùng CLI BE hiện có, giữ approver guard baseline, chạy atomic và trả receipt/audit; cùng digest trả receipt cũ.
5. Lesson xuất hiện trong Open Curriculum. Course progress không được tuyên bố đã cập nhật; nếu cần, course binding là scope riêng sau pilot.
6. Review effort được đo/tối ưu, có quyền nguồn và traceability; staging target được định danh rõ.

Không tuyên bố production-ready từ static review hoặc staging. Không có database/runtime claim cho tới khi môi trường tương ứng được kiểm tra trực tiếp.

## Trình tự trước khi giao story

1. Canonical contract là `_bmad-output/specs/spec-nexalab-content-tool-mvp/SPEC.md` cùng `master-plan.md`; tài liệu này là bản mirror cho repo Tool. PRD/code BE/FE giữ vai trò nguồn sự thật tương ứng.
2. Thứ tự tiếp theo là M1 → tích hợp end-to-end M2a → M2b → M3. M0a hoàn tất phần feasibility cho KHTN 8 nhưng không hoàn tất M1.
3. Hoàn tất NexaLab preflight ngoài scope trước staging apply/expose; preflight không chặn M1 local.

Tham chiếu: [NexaLab integration contract](content-tool-nexalab-contract.md). Đây là snapshot; khi có khác biệt, kiểm tra source code ở commit mới.
