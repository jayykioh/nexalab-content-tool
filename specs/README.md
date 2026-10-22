# NexaLab Content Tool — Specs Kit

Đây là bộ tài liệu để bắt đầu implement pilot 2–3 Lesson. Không phải bằng chứng các luồng đã chạy thành công.

## Đọc theo thứ tự

1. `NexaLab_Content_Tool_Master_Plan_Lean_v5.4.md` — phạm vi, quyết định và roadmap chuẩn.
2. `content-tool-nexalab-contract.md` — snapshot hợp đồng BE/FE; đối chiếu source ở commit implement trước khi code.
3. `IMPLEMENTATION_CHECKLIST.md` — các gate và việc cần hoàn thành theo mốc.
4. `TEST_PLAN.md` — kiểm thử BE, FE, release và staging E2E.

Plan xác định phạm vi pilot; contract là snapshot kỹ thuật, không phải API promise. Khi khác biệt, kiểm tra code/PRD hiện hành và ghi nhận quyết định cần thiết trước khi implement. Checklist/test plan là tài liệu dẫn xuất; không tự mở rộng scope.

`NexaLab preflight ngoài scope` trong master plan thuộc BE/database/environment, không thuộc repo Content Tool. Chỉ thực hiện trên target đã định danh và trước staging apply/expose.
