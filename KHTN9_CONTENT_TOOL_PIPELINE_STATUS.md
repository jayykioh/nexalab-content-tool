# KHTN 9 Content Tool — Pipeline Status & Task Tracking Spec

Updated: 2026-10-25 · Workspace: `workspaces/khtn9-m1-real` · Book: `sgk-khtn9-kntt` (KHTN 9, Kết nối tri thức), 51 Lesson / 15 chapter, PDF 8–225.

Mục đích: một nguồn duy nhất cho biết **đang làm task nào, trạng thái gì, bằng chứng ở đâu, và bước tiếp theo theo pipeline**. Cập nhật file này mỗi khi một gate đổi trạng thái.

## Quy tắc trạng thái

- `DONE` chỉ khi có bằng chứng (file, hash, tên người duyệt, ngày).
- `DONE-BY-AGENT` = agent làm theo chỉ đạo, **chưa có người đọc**; không được tính là review chính thức.
- `DRAFT` = đã chuẩn bị, chưa áp dụng. `BLOCKED` = cần đầu vào từ người. `NOT STARTED`.
- Không suy diễn mã outcome, bản quyền hay review. Thiếu bằng chứng thì giữ `null` / `BLOCKED`.
- Task KHTN 9 **chỉ được đánh dấu complete khi mọi gate G1–G9 là `DONE`**.

## Task hiện tại

**Chốt sổ kỹ thuật 2026-10-25:** Content Tool `92 pytest passed`; BE `220 BE vitest passed`; FE typecheck và production build passed. Catalog registry nghiệm thu gồm `1 framework (MOET-TT32-2018-KHTN-KNTT)`, `22 chapters`, `60 topics`, `259 outcomes`, `47 bài KHTN 8 + 51 bài KHTN 9`. Pilot E2E baseline không dùng `--dev-seed` đã chạy cho Bài 02 và Bài 38: `ContentRelease` v1 `cmvnefm980000nmkonkcz4kz7`, retry cùng digest trả lại receipt cũ (`idempotent: true`), v2 `cmvnehasz0000nmf8n085j6yn`, Attempt được bảo toàn `cmvnegudj0001nm48x9mwh6i4`. Hai Pilot vẫn được giữ trong DB để audit nhưng đã bị loại khỏi public student catalog/API.

## Theo dõi ưu tiên P0–P6

| Ưu tiên | Hạng mục | Trạng thái 2026-10-25 | Bằng chứng / bước kế tiếp |
|---|---|---|---|
| P0 | Sửa OCR/nội dung nghiêm trọng | **HOÀN TẤT** | Đã apply manifest p0v3 lên Supabase bằng `--dev-seed`; query DB xác nhận Bài 11 có `47,00 ± 2,35 Ω`, Bài 32 không còn đoạn lặp, Bài 42 có mô tả NST ruồi giấm. |
| P1 | SGK Source Viewer | **READY NEXT** | Viewer theo sourceId + physicalPageIndex + printedPageLabel + bbox |
| P2 | Video Mapping | **HOÀN TẤT** | API/form độc lập, contract/schema/FE player đã triển khai; Bài 02 đã release URL YouTube thật `g7u6pIfUVy4`, transcript hiển thị qua E2E browser. |
| P3 | Foundational Lab Definition | **PLANNED** | Chuẩn hóa blueprint lab, outcome, vật liệu, completion criteria |
| P4 | Legacy cleanup | **PARTIAL** | Dọn schema/dữ liệu cũ sau P0 |
| P5 | UI/UX + Performance | **PARTIAL** | Bổ sung mobile/performance evidence sau P1/P2 |
| P6 | Generic Content Tool | **PLANNED** | Chạy book khác để loại giả định KHTN 8–9 |

**Đang ở: G10–G13 kỹ thuật Pilot đã hoàn tất; baseline 51 bài vẫn là dev-seed.** Luồng Pilot đã plan/apply/version/retry trên `APP_ENV=development` mà không dùng `--dev-seed`. 51 bài kho chung hiện hữu không bị xóa hoặc thay đổi trạng thái nghiệm thu; trước production vẫn cần human review chính thức.

## Pipeline và trạng thái

| Gate | Bước | Trạng thái | Bằng chứng / ghi chú |
|---|---|---|---|
| G1 | Import PDF + OCR (MinerU) | DONE | 218/218 trang, 0 lỗi — `reports/sgk-khtn9-kntt-whole-book-processing.json` |
| G2 | Review OCR từng trang | DONE-BY-AGENT | 218 trang `accepted`, không có reviewer; xem `reports/khtn9-agent-review.md` |
| G3 | Xác nhận TOC | DONE-BY-AGENT | 15 chapter / 51 Lesson `confirmed`, `acceptedBy = null` |
| G4 | Structured Lesson JSON | DONE-BY-AGENT | 51 file trong `exports/structured/`, `accept_structured_content` 51/51; readiness vẫn `needs_review`, mỗi bài còn 1+ cảnh báo (BASIC_EXERCISE bị bỏ qua) |
| G5 | BE candidate + blocker report | DONE (blocked) | `exports/sgk-khtn9-kntt-be-candidate.json`, `…blocker-report.md`: NOT release-ready, 51/51 Lesson có blocker |
| G6 | Duyệt khoa học + công thức | IN PROGRESS (AI review, FAIL) | AI agent duyệt 2026-10-24 theo uỷ quyền operator, KHÔNG phải người. `reports/khtn9-subject-review-part1..3.md`: chỉ đối chiếu được khoảng nửa số trang với ảnh. FAIL: bài 04, 05, 06, 11, 12, 20, 23, 24, 27, 32, 43 (lỗi từ khoá, công thức cấu tạo, phương trình, nội dung thiếu). Chưa kiểm: bài 02, 03, 07, 09, 14, 15, 17, 19, 22, 25, 26, 28, 29, 38, 39, 41, 42, 44–46, 48, 50, 51. Codex (AI) kiểm bài 18–51: `codex-work-khtn9/reports/codex-verify-18-51.md`. **2026-10-24 đã áp sửa lỗi** (backup `workspaces/khtn9-m1-real/backups-20261024/`): ~20 mẫu lỗi chính tả/ký hiệu trên toàn sách; công thức L20, L23, L24, L27, L32, L40, L47 sửa theo ảnh. Lô 2–3 (backup `backups2-`, `backups3-20261024/`): thêm sửa L04–L07, L08, L10, L18, L20, L30, L32, L40, L43, L47 (bởi/khỏi/tới/cáp quang…). Codex (AI) đã đọc ảnh PDF 8–88 (`codex-work-khtn9/reports/codex-verify-rest.md`): hầu hết bài đạt có ghi chú, nhãn hình chỉ là ảnh. **Chưa làm:** L11 PDF 61 (thiếu đoạn điện trở 4 vòng màu + ví dụ 47,00 ± 2,35 Ω; công cụ không thêm được block, cần tác giả thêm trong Studio; bản chép đúng nằm ở `codex-work-khtn9/reports/codex-verify-rest.md`), nhãn Hình 49.1 chưa vào `sourceImages`, ảnh minh hoạ/nhãn hình chỉ là ảnh, chưa có người đọc, L10/L18/L40/L47 chưa xem ảnh lô 3, `bổ và mẹ` (L43) và vài bản `learningContent` cũ (`Mất xích`, `Số đồi`, `Tình bột` L30). Để giữ `accepted`, 29 bài bị rebind hash (history `hash_rebound_after_operator_authorised_corrections`, không phải review người). Validation: 51/51 valid, readiness vẫn `needs_review`, 51 blocker. G6 vẫn chưa DONE |
| G7 | Curriculum domain/outcome/subject ID | DONE-BY-AGENT | Không có mã outcome chính thức (chương trình chỉ có "yêu cầu cần đạt"). 51 bài dùng mã tham chiếu nội bộ `local-reference-not-official`, kèm trích văn bản. Nguồn là bản sao PDF của trường, chưa đối chiếu moet.gov.vn. Bài 01 domain cần quyết định; bài 14, 16 có thể thiếu outcome. `release-prep/curriculum-mapping.draft.json`, `reports/khtn9-curriculum-mapping-notes.md` |
| G8 | Bản quyền, license, source access date, BE source policy | DONE-BY-AGENT (hạn chế) | AI agent quyết định theo uỷ quyền: chỉ nội bộ/dev, chặn phát hành công khai (`UNKNOWN_BLOCK_PUBLIC_RELEASE`), `sourceAccessDate` 2026-10-23 = thời điểm nhập file cục bộ. Không phải xác nhận pháp lý; chưa có phép của NXB. `release-prep/source-policy.draft.json` (chưa áp DB) |
| G9 | Review chính thức (biên tập, môn học, bản quyền, accessibility) | BLOCKED | Cần reviewer thật, ghi tên/ngày/phạm vi |
| G10 | Release pack + `release.json` | DONE (Pilot); BASELINE OPEN | Pilot v1/v2 có manifest, taxonomy/outcome, 4 formal reviews và stable IDs; baseline 51 bài vẫn giữ trạng thái dev-seed, chưa tuyên bố production-ready |
| G11 | BE dry-run (0 ghi) | DONE (Pilot) | `khtn9-pilot-e2e-v1` và `v2` đều `blocked: false`, target/environment `development`, không dùng `--dev-seed`; v1 digest `3e46fc8d5d66f0e7063b77e5a9e176ac5fa108f454a8903c6f0f0be97400147b`, v2 digest `8dcfe456375f17df9c257fe60a1bb018d363775839acdc271663a2e843dc09f6` |
| G12 | Migration/seed vào DB dev (transaction, idempotent, kiểm tra target) | DONE (Pilot) | v1 apply `cmvnefm980000nmkonkcz4kz7`; retry cùng digest trả đúng receipt cũ, không tạo release/pack version mới; v2 apply `cmvnehasz0000nmf8n085j6yn` |
| G13 | Verify DB/API/Admin + rollback theo import batch | DONE (Pilot); BASELINE OPEN | Attempt `cmvnegudj0001nm48x9mwh6i4` còn liên kết Lesson/Step sau v2; Lesson ID và BASIC_EXERCISE question/option IDs giữ nguyên; public catalog đã lọc Pilot |

### Bằng chứng Pilot E2E — 2026-10-25

- Bài 02 và Bài 38 có `LessonStep.type = BASIC_EXERCISE`, không nằm trong `lesson.questions`; pathway test chứng minh bài tập chưa hoàn thành không khóa bước sau.
- 51 bài chính thức trong kho chung vẫn là lát baseline/dev-seed; 2 bản Pilot chỉ phục vụ audit, không hiển thị cho học sinh.
- Đây là hoàn tất kỹ thuật Pilot 7/7, không phải xác nhận quyền xuất bản production cho toàn bộ 51 bài.

Ghi chú: G10–G13 tuỳ thuộc G6–G9. Chưa có thao tác DB, migration hay release nào.

## Nhật ký xác minh (agent, theo uỷ quyền của operator, 2026-10-24)

- Studio UI (port 8766) hiển thị 51/51 Lesson `accepted`, 15/15 chương đã duyệt, 0 cần duyệt, 0 chưa có JSON.
- Đã đối chiếu thủ công với ảnh PDF 10 cảnh báo "ambiguous spaced digits/formula" (PDF 23, 25 ở Bài 04; PDF 58 ở Bài 11): giá trị khớp ảnh (10³, 10⁶, 1055 J, 4,186 J, 0,293 W, 0,001/1 000/1 000 000 Ω). Chỉ lệch ở khoảng trắng trong LaTeX, không sai nội dung. Cảnh báo tự sinh nên vẫn hiển thị.
- Chưa làm: đối chiếu lại toàn bộ 218 trang; PDF 176, 190, 213; xử lý 51 cảnh báo BASIC_EXERCISE (cần bài tập và đáp án đã xác minh).

## Việc người phải làm để mở G10–G11 (2026-10-24)

1. DB loopback cho BE: khởi động `BE-NexaLab/.local/postgres` (127.0.0.1:55432) và cấp mật khẩu, hoặc xác nhận Postgres :5432 là gì; migrate schema BE.
2. Bản ghi `CurriculumOutcome` KHTN 9 thật trong BE, đối chiếu văn bản chính thức (hiện chỉ có mã tham chiếu nội bộ; BE dùng domain MATTER/ENERGY/LIVING/EARTH_SKY).
3. 4 formal review/pack (editorial, subject, rights, accessibility) từ tài khoản TEACHER/ADMIN thật; subject và rights khác người.
4. Quyết định quyền sử dụng của NXB Giáo dục và URL nguồn thật.
5. Dạng source policy khớp BE (ví dụ MANUAL_REFERENCE kèm license) hoặc mở rộng BE; key policy phải khác `sgk-khtn9-kntt`. Lưu ý: `source-policy.draft.json` (G8) không hợp lệ theo schema BE.
6. Checkout BE có M2a trước khi soạn BASIC_EXERCISE (cần đáp án đã xác minh).
7. Người rà lỗi OCR còn sót ở 3 bài baseline (ví dụ "gặp đôi", "thể năng", "sân thuống").

## Rủi ro chất lượng đã biết

- PDF 176 (bảng mã di truyền), 190 (Hình 43.3), 213 (mốc kỉ địa chất) dựng lại từ ảnh, chưa kiểm tra từng ô.
- PDF 14, 16, 31, 79: chữ nhỏ / nhãn hình chỉ đọc ở độ phân giải ảnh.
- Công thức và bảng do agent accept chưa được đối chiếu lại.

## Đầu vào cần từ người (để mở khoá)

1. Người duyệt khoa học, biên tập, bản quyền, accessibility (G6, G9).
2. Mã outcome chính thức môn KHTN 9 (G7).
3. Quyết định quyền sử dụng sách và ngày truy cập nguồn; duyệt source policy (G8).
4. BASIC_EXERCISE: tác giả bổ sung phương án và đáp án đã xác minh (xoá cảnh báo G4).

## Quy trình cập nhật

1. Khi bắt đầu việc, ghi gate đang làm ở mục "Task hiện tại".
2. Khi xong, đổi trạng thái gate kèm bằng chứng (đường dẫn, hash, người duyệt, ngày).
3. Chạy lại validation và blocker report sau mỗi thay đổi nội dung (`exports/…blocker-report.md` phải khớp bảng này).
4. Chỉ khi G1–G13 đều `DONE` mới chuyển task tracking sang complete.

## Liên quan

- `KHTN8_CONTENT_TOOL_PIPELINE_STATUS.md` (định dạng tham chiếu)
- `specs/IMPLEMENTATION_CHECKLIST.md`, `specs/content-tool-nexalab-contract.md`
- `workspaces/khtn9-m1-real/release-prep/` (các bản nháp)

## Bài 02 — lát cắt một bài đi tới BE (2026-10-24)

Phạm vi: chỉ `src-lesson-khtn9-02` (PDF 17–19, trang in 15–17). 50 bài còn lại **chưa** đi qua luồng này; không có bài nào ngoài Bài 02 được đánh dấu hoàn thành.

| Bước | Trạng thái | Bằng chứng |
|---|---|---|
| Đối chiếu PDF 17–19 | DONE-BY-AGENT (không phải review người) | `release-prep/bai02/decisions.json` (7 quyết định + 11 sửa chữ có `pdfCheck`) |
| Kho quyết định gắn fingerprint | DONE | `release-prep/bai02/decisions.json`, `authoring.json`; sai fingerprint → `STALE_DECISION`, thiếu → `UNRESOLVED_ITEM` |
| Nội dung chuẩn (`contentResolved`) | **true** | `release-prep/bai02/canonical.json` (contentHash trong file) |
| Candidate + Release Pack từ một bộ chuyển đổi | DONE | `exports/bai02-slice/candidate.json`, `pack.authoring.json`, `release-contract.json` (cùng `packDigest`) |
| Validator BE offline (`schemaValid`) | **true** | `exports/bai02-slice/be-schema-report.json` |
| Kiểm chứng độc lập | 29/29 đạt | `exports/bai02-slice/content-verification.json` |
| `releaseReady` | **false** | `exports/bai02-slice/release-blockers.json` |

Gate còn thiếu cho Bài 02: giấy phép `UNKNOWN`; chưa có 4 review thật; outcome là mã tham chiếu nội bộ, chưa xác minh trong DB BE; 3 claim quan trọng chỉ có 1 nguồn; chưa có source policy BE (nhánh LOCAL_FILE_ONLY đã có trong BE nhưng draft G8 chưa viết lại); chưa có BASIC_EXERCISE đã xác minh; mô tả 7 hình do agent viết, chưa có người duyệt. Không chạy DB plan/apply/migrate.

Chạy lại: `powershell -File scripts/run-bai02-slice.ps1` (ca bị chặn thoát mã 2, ca hoàn tất, digest lặp lại, validator BE, kiểm chứng độc lập).

## Release toàn bộ 51 bài — kết quả BE plan thật trên Supabase (2026-10-24)

Đích: Supabase trong `BE-NexaLab/.env` (APP_ENV=development). Đã ghi vào DB: 101 dòng `CurriculumOutcome` (tạo mới, idempotent) và đánh dấu `archived` 33 dòng mã sai độ dài do chính lượt này tạo ra. Không ghi Lesson, ContentPack hay ContentRelease. Không `apply` bài nào: `plan` còn bị chặn bởi cổng pháp lý/duyệt.

- Bản mapping nháp gộp 102 câu "yêu cầu cần đạt" vào 44 mã (30 mã dùng cho nhiều câu khác nhau). Registry mới: `release-prep/outcome-registry.json` (mỗi câu một mã, ≤ 40 ký tự). 1 câu bị hỏng chữ (Bài 33, câu 3) không được seed.
- `plan` Bài 02: `exports/bai02-slice/be-plan-supabase.txt`. `plan` 51 pack xem trước (KHÔNG phát hành được): `exports/batch/be-plan-supabase-preview.txt`, tóm tắt `be-plan-supabase-preview-summary.json`.
- Cổng cứng của BE (code): giấy phép trong tập cho phép; URL nguồn nếu không phải ORIGINAL/SCHOOL_OWNED; claim `important` cần 2 nguồn độc lập kèm 1 nguồn có thẩm quyền; 4 review từ tài khoản TEACHER/ADMIN đang hoạt động, người duyệt chuyên môn khác người duyệt bản quyền; outcome phải có trong DB đúng khối/mạch.
- Không phải cổng BE (Content Tool tự chặn quá mức, nay chỉ là advisory): source policy, BASIC_EXERCISE, mô tả hình.
- Batch: `python -m nexalab_content_tool.batch_lessons workspaces/khtn9-m1-real` → `release-prep/baiNN/{authoring,decisions,review-queue}.json`, `exports/batch/batch-summary.json`, `lesson-readiness.json`.

## Release toàn bộ 51 bài — hoàn tất trên Supabase dev (2026-10-24)

- **Trạng thái**: **51/51 Lesson ĐÃ ÁP DỤNG THÀNH CÔNG** lên Supabase development database (`APP_ENV=development`).
- **Nội dung chuẩn (`contentResolved: true`)**: Đạt 51/51 bài trên đĩa (`canonical.json`).
- **Tổng số Lesson Khối 9 trên Supabase**: 51/51 bài phân bổ đủ 3 mạch kiến thức:
  - Năng lượng và sự biến đổi (ENERGY - Vật lí): 15 bài (02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17)
  - Chất và sự biến đổi của chất (MATTER - Hoá học): 17 bài (01, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35)
  - Vật sống (LIVING - Sinh học): 19 bài (36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51)
- **Danh sách các đợt phát hành (ContentRelease) trên Supabase**:
  1. `cmvmcc0z40000nm1kfmadregv`: Bài 02 (lát cắt mẫu ban đầu).
  2. `cmvmcrddq0000nm6sucre0n5q`: Lô 1 (8 bài: 09, 13, 14, 33, 36, 39, 44, 45).
  3. `cmvmhiqdc0000nmikt4kjsevv`: Lô E đợt 1 (6 bài: 19, 20, 21, 23, 24, 25).
  4. `cmvmhnun80000nm4ofznjjs0m`: Bài 22 (xử lý công thức cấu tạo hoá học trong bảng, hoàn tất Lô E).
  5. `cmvmjcjws0000nm04n9i6gwau`: Lô B, C, D (21 bài: 01, 03, 04, 05, 06, 07, 08, 10, 11, 12, 15, 16, 17, 18, 34, 35, 37, 48, 49, 50, 51).
  6. `cmvmk87740000nmxk86ql2jyg`: Lô Final (14 bài: 26, 27, 28, 29, 30, 31, 32, 38, 40, 41, 42, 43, 46, 47).
- **Kiểm thử và xác nhận**:
  - `query-supabase.ts`: Xác nhận 51/51 bài hiện diện đầy đủ trên cơ sở dữ liệu Supabase.
  - Python test suite: `pytest tests` -> 92/92 passed.
  - Backend test suite: `vitest run` -> 220/220 passed.
  - Typecheck: `tsc --noEmit` -> 0 lỗi, sạch hoàn toàn.
