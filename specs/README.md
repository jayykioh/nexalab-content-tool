# NexaLab Content Tool — Specs Kit

Đây là bộ tài liệu scope và triển khai pilot book-to-Lesson. Không phải bằng chứng các luồng đã chạy thành công.

## Đọc theo thứ tự

1. Canonical source: `D:\coding\nexalab-be\_bmad-output\specs\spec-nexalab-content-tool-mvp\SPEC.md` và `master-plan.md`.
2. `NexaLab_Content_Tool_Master_Plan_Lean_v5.5.md` — bản mirror của phạm vi, quyết định và roadmap.
3. `content-tool-nexalab-contract.md` — snapshot hợp đồng BE/FE; đối chiếu source ở commit implement trước khi code.
4. `IMPLEMENTATION_CHECKLIST.md` — các gate và việc cần hoàn thành theo mốc.
5. `TEST_PLAN.md` — kiểm thử UI, BE, FE, release và staging E2E.

Canonical SPEC/master plan xác định phạm vi pilot; contract là snapshot kỹ thuật, không phải API promise. Khi khác biệt, kiểm tra code/PRD hiện hành và đồng bộ decision trước khi implement. Checklist/test plan là tài liệu dẫn xuất; không tự mở rộng scope. Master plan v5.5 supersedes v5.4; story M1 cũ chỉ ghi lịch sử một CLI slice, không phải DoD luồng sản phẩm.

`NexaLab preflight ngoài scope` trong master plan thuộc BE/database/environment, không thuộc repo Content Tool. Chỉ thực hiện trên target đã định danh và trước staging apply/expose.
