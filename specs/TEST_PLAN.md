# Test Plan — Content Tool ↔ NexaLab Pilot

## Nguyên tắc

- Đây là kế hoạch kiểm thử, chưa phải kết quả test. Chạy trên đúng commit và target đã xác nhận.
- Unit tests không cần DB. Integration/E2E cần database/API/FE cấu hình và seed phù hợp.
- Không dùng `fixture` như bằng chứng bài baseline đã được reviewer thật duyệt.
- Không chạy production test; staging thành công không chứng minh production readiness.

## Ma trận kiểm thử

| Lớp | Kiểm tra bắt buộc | Kết quả mong đợi |
|---|---|---|
| Book import UI | Import PDF mới / cùng file trùng hash / file thay phiên bản; sample và full | Nguồn có version/hash; duplicate được nhận diện; lựa chọn scope rõ; không gửi dữ liệu ra ngoài |
| Pipeline progression | Dừng/reopen sau import, OCR, review và authoring; thử lỗi OCR/thiếu runtime | UI tiếp tục từ checkpoint; lỗi hiển thị tại stage đúng; không đánh dấu bước sau complete khi prerequisite chưa đạt |
| MinerU | Xác minh local `mineru-kit` version, tier, model và source hash; sample rồi full | UI gọi MinerU local đúng; trạng thái chỉ báo dữ liệu engine thật cung cấp; lỗi/timeout có thể retry/resume an toàn |
| OCR review | Sửa/chấp nhận/đánh dấu block; kiểm tra source crop, history, elapsed time và hash | Original/source locator giữ nguyên; thao tác OCR không yêu cầu reviewer name và không tính là formal release approval |
| Gemini LaTeX (gated) | Gemini tắt; quyền/provider policy chưa xác nhận; sau khi gate mở thử đề xuất sửa công thức | Mặc định/manual flow vẫn hoạt động; khi bật thì chỉ proposal/diff, giữ original, cần operator áp dụng; không auto-review/publish |
| Lesson authoring UI | Tạo 2–3 Lesson từ OCR/reviewed content, lưu/reopen, sửa wording và export lại | Không cần chỉnh JSON; stable IDs và source evidence giữ nguyên; thiếu curriculum/evidence được chỉ rõ |
| Tool → BE plan | Export UI-authored pack rồi chạy BE `plan` | Manifest đúng contract; blocker/diff được hiển thị; plan không ghi DB; digest/export deterministic |
| Manifest/schema | Legacy fixture không có `basicExercises`; parse và digest golden value | Vẫn hợp lệ; digest cũ không đổi |
| Manifest/schema | Field `basicExercises` sai shape, duplicate IDs, answer không thuộc options | Bị từ chối ở validator phù hợp; ID hợp lệ giữ nguyên |
| Release gates | Baseline thiếu một trong 4 review; reviewer không active; subject = rights | Plan blocked với blocker cụ thể |
| Release gates | Baseline reviewer thật active; 4 role review hợp lệ, subject ≠ rights | Gate review qua; role khác có thể cùng người nếu họ thực sự làm review đó |
| Fixture | Synthetic pack trên staging; thiếu review, subject = rights, hoặc target pilot/production | Bị chặn theo đúng điều kiện; fixture không thành bài baseline |
| Materialization | Export exercise qua pack → `LessonStep.config` → API → FE/attempt | BASIC_EXERCISE, IDs/config chính xác; không thành required QUIZ |
| Pathway | Required exercise chưa hoàn tất, có step kế tiếp | Exercise không khóa step kế; step chưa hoàn tất vẫn giữ evidence/progress semantics |
| Pathway regression | Required QUIZ/LAB/assignment chưa hoàn tất theo flow cũ | Gate cũ giữ nguyên |
| Stable identity | Thử attempt, sửa wording và export lại với authored IDs giữ nguyên | Attempt/FE keys gắn đúng question/option; không sinh ID ngẫu nhiên |
| CLI dry-run | `content:release` không có `--apply`, target đúng/sai environment | Không ghi DB; target sai bị block |
| Apply/idempotency | Apply baseline hợp lệ; chạy lại đúng target/digest | Một receipt/version; lần hai trả receipt cũ, không nhân đôi |
| Apply/versioning | Sửa pack tạo digest chưa từng apply rồi apply | Tạo version/Lesson mới; version/Lesson cũ archive; historical attempts giữ nguyên và đúng step |
| Apply/atomicity | Gây lỗi có kiểm soát giữa transaction trong integration test | Không để lại release/content update một phần |
| Open Curriculum | GET list/detail sau staging apply | Chỉ Lesson released/published/shared xuất hiện; exercise hiển thị và attempt hoạt động |
| Progress semantics | Pipeline stage progress vs active-course/student progress | UI không gọi OCR/authoring stage là student progress; release không tự thêm Lesson vào course hoặc cập nhật course denominator |
| Video identity | Lesson có nhiều video ở cấp Lesson/section | Mỗi video materialize thành một VIDEO step ổn định; không dùng chung progress |
| Video segment coverage | Xem liên tục, tua tiến, tua lùi, xem lại, pause/buffer, retry và hai tab | BE chỉ cộng union khoảng xem liên tục hợp lệ; seek không lấp khoảng trống; retry/concurrency không đếm đôi |
| Video completion/resume | Đạt/chưa đạt threshold; reload; assignment và free practice | Completion do BE tính từ coverage; resume đúng video/giây/context; hai context không trộn evidence |
| Learning journey | Student view; teacher owner/outsider; nhiều Lesson/video | Student thấy bước hiện tại; teacher owner thấy timeline/ranges; outsider không đọc hoặc suy ra membership |
| OCR/review | Mẫu trang native text/OCR; đo disagreement, lỗi, review time và uncovered-ink flags | Có số liệu trước quyết định mở rộng; flag chỉ hỗ trợ review, không tự sửa |

## Trình tự chạy

1. **BE unit:** từ `D:\coding\nexalab-be`, chạy `npm test`; tập trung pack schema/gates, materialization, pathway, progress và release service.
2. **BE integration:** từ BE, chạy `npm run test:integration` với DB/API seeded đã xác nhận; kiểm tra apply, idempotency, rollback transaction và version mới.
3. **FE:** từ `D:\coding\nexalab-fe`, chạy `npm run lint` và `npm run build`; sau đó `npm run test:e2e` với API/FE và browser đã cấu hình.
4. **Local UI M1:** import KHTN 8, sample OCR, sửa block, đóng/mở lại workspace, tạo Lesson trong UI, export và BE plan. Chạy lại manual-only khi Gemini tắt; chưa gọi apply.
5. **Staging manual M2b/M3:** chỉ sau khi M1/M2a integration đạt; làm preflight NexaLab riêng; plan → review digest/blockers → apply baseline qua BE với approvals thật → Open Curriculum → exercise attempt → đổi digest → kiểm tra Lesson/attempt cũ.

Không bỏ qua preflight database vì unit tests xanh. Không cần thêm test suite mới chỉ để kiểm tra các hành vi đã có; bổ sung test đúng tại BE/FE module bị thay đổi.

## Bằng chứng cần lưu

- Commit BE/FE/Tool và phiên bản MinerU/model đã dùng.
- Log test/CI, plan digest, release receipt và API/FE kết quả staging.
- Thống kê OCR/review theo mẫu và quyết định tiếp tục/thu hẹp/dừng.
- Số liệu read-only preflight; mọi DB update phải có target, row count trước/sau và người thực hiện.
