# KHTN 9 — Hướng dẫn phê duyệt qua UI (G2–G4)

Mục đích: bạn tự phê duyệt trong Studio để có chứng cứ do người thực hiện, thay vì chấp nhận do agent. Tiến độ tổng nằm ở `KHTN9_CONTENT_TOOL_PIPELINE_STATUS.md`.

## 0. Mở Studio

```powershell
cd "D:\FPT\Ky8\WDP301\project\NexaLAB_Content tool"
uv run nexalab-content studio workspaces/khtn9-m1-real --port 8766
```

Mở http://127.0.0.1:8766 . UI có 3 tab: **1. Chọn bài**, **2. Sửa OCR**, **3. Duyệt nội dung**.

## 1. G2 — Duyệt OCR từng trang (tab 2. Sửa OCR)

1. Tab 1: chọn sách `sgk-khtn9-kntt`, chọn Chương rồi Lesson, bấm **Tiếp tục: duyệt nội dung Lesson** (hoặc chuyển sang tab 2).
2. Danh sách trang bên trái, ảnh PDF ở giữa, các block OCR bên phải. So từng block với ảnh.
3. Sửa block sai, rồi bấm **Lưu và đánh dấu trang đạt**. Nếu chưa chắc: **Cần sửa thêm**. Nếu trang không dùng: **Không dùng trang này**.
4. Ưu tiên kiểm tra trước (rủi ro cao): PDF **176, 190, 213** (bảng mã di truyền, Hình 43.3, mốc kỉ địa chất), PDF **14, 16, 31, 79**, và công thức ở PDF **23, 25, 58**.
5. Trang đã `accepted` giữ nguyên; chỉ cần mở lại trang bạn muốn xác minh lại, không cần duyệt lại cả 218 trang.

## 2. G3 — Xác nhận TOC (tab 1, mục "Thiết lập danh sách Chương và Lesson")

1. Mở mục đó, chọn một Lesson ở "Đối chiếu ranh giới Lesson với PDF".
2. Xem 3 ảnh: trang đầu, trang cuối, trang kế tiếp. Tick **Tôi đã kiểm tra trang đầu, trang cuối và trang kế tiếp**.
3. Lưu ý: bài 07, 09, 39, 49 OCR không đọc được chữ "Bài N"; kiểm tra bằng thứ tự bài.
4. Cuối cùng bấm **Xác nhận phạm vi đã đối chiếu**. Trạng thái hiện tại đã `confirmed` do agent; xác nhận lại nếu bạn muốn chứng cứ của người.

## 3. G4 — Duyệt nội dung Lesson (tab 3. Duyệt nội dung)

Làm cho từng Lesson (51 bài):

1. Chọn trang PDF ở "Trang PDF đang đối chiếu", đọc ảnh bên trái.
2. Kiểm tra bên phải: Tóm tắt, Các phần nội dung, Đơn vị kiến thức, Công thức và bảng.
3. Mở "Cảnh báo và tham chiếu nguồn". Mỗi bài còn cảnh báo:
   - `BASIC_EXERCISE omitted`: cả 51 bài. Muốn xoá cảnh báo thì bật **Thêm bài tập cơ bản** trong phần BASIC_EXERCISE tuỳ chọn và nhập câu hỏi, 2 phương án, đáp án đã xác minh. Nếu không có bài tập, chấp nhận cảnh báo.
   - `ambiguous spaced digits/formula`: PDF 23, 25 (bài 04), PDF 58 (bài 11). Sửa theo ảnh.
4. Tick **Tôi đã đối chiếu đầy đủ các trang PDF và xử lý các cảnh báo của Lesson này.**
5. Bấm **Lưu để làm tiếp**, sau đó **Đánh dấu Lesson đã duyệt**.
6. Hết chương: bấm **Cập nhật JSON của Chương**. Hết sách: tab 1 mục "OCR và cập nhật dữ liệu nguồn", bấm **Cập nhật JSON và báo cáo**.

Ghi chú: công cụ ghi `acceptedBy = null` (không lưu danh tính). Hãy ghi tên người duyệt và ngày vào bảng ở file status.

## 4. Kiểm tra sau khi duyệt

Chạy lại validation, kỳ vọng `contentReviewStatus: accepted` cho 51 bài và `pendingOcrReviewPages` rỗng. Bài còn cảnh báo sẽ vẫn `needs_review` cho đến khi xử lý.

## 5. Chưa làm trên UI này

Phần "Phát hành sang BE" (formal reviews, manifest, BE plan dry-run) chỉ dùng sau khi G6–G9 có bằng chứng thật (reviewer, outcome chính thức, quyết định bản quyền). Không tick formal review nếu chưa có người thực hiện.
