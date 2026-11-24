# Audit kiến trúc & chất lượng code — kiến trúc sư phần mềm

Mục tiêu: chỉ ra chỗ code **làm chậm hoặc làm hỏng việc thay đổi, debug, mở rộng**, ưu tiên vùng hay sửa — không chấm điểm cả repo. `engineering.md` là chuẩn: vi phạm của code đang có là phát hiện.

## 1. Bản đồ (đọc ít)

`CLAUDE.md` root + surface, manifest (`package.json`, `pubspec.yaml`…), cây thư mục 2–3 tầng của surface, entry point, router, lớp gọi API/DB, quản lý state, cấu hình môi trường, CI (`.github/workflows`). Ghi vào đầu `OUT` 3–5 dòng: stack, tầng, ranh giới, pattern chính.

## 2. Radar

`cd <WT> && agentflow-audit scan [--days 180] [<path của FOCUS hoặc SURFACES>]` (JSON):
`hotspots` (commit × dòng: nơi hay đổi và lớn) · `largest` · `coupling` (cặp file khác thư mục luôn đổi cùng nhau: phụ thuộc ẩn) · `cycles` (vòng phụ thuộc giữa thư mục, `weakest` = cạnh nên cắt) · `upward` (tầng dưới import tầng trên) · `duplicates` · `markers` (TODO/FIXME) · `smells` (catch rỗng, suppress lint/type, `any`, `!!`/`try!`, log debug, URL môi trường viết cứng) · `ci` (workflow chạy gì).
Số đo chỉ nói **chỗ cần đọc**; kết luận chỉ sau khi đọc code.

## 3. Đọc sâu ≤ 10 file

Hotspot đầu, hai đầu của cycle/coupling mạnh nhất, mẫu đại diện của mỗi smell nhiều nhất; đọc theo phần. Soát:
- **Bảo trì**: lớp/màn ôm nhiều trách nhiệm; nghiệp vụ nằm trong UI/controller; một việc làm ≥ 2 kiểu (gọi API, state, xử lý lỗi, format); logic trùng; số/chuỗi ma thuật; code chết; tên không nói ý định.
- **Kiến trúc**: phụ thuộc vòng; tầng dưới import tầng trên; module với vào chi tiết của module khác; singleton/state toàn cục ghi được; dịch vụ ngoài gọi thẳng, không qua adapter; contract không version; cấu hình rải rác hoặc viết cứng theo môi trường; file luôn đổi cùng nhau mà nằm xa nhau.
- **Debug**: nuốt lỗi; lỗi mất ngữ cảnh/stack; log thiếu id truy vết hoặc lẫn log debug; không có crash/error reporting; thiếu error boundary; promise/future không bắt lỗi.
- **Mở rộng, hiệu năng**: N+1; danh sách không phân trang; truy vấn mới thiếu index; việc nặng trên main/UI thread; cache không invalidate; listener/subscription không huỷ; retry không giới hạn, không timeout; job không idempotent; bundle/ảnh lớn.
- **An toàn**: input không validate ở biên; quyền chỉ kiểm ở client; query ghép chuỗi; secret trong code (chỉ ghi `path:line`, không chép giá trị); dependency bỏ bảo trì hoặc lệch nhiều major.
- **Kiểm chứng được**: không có seam (khởi tạo cứng, gọi thẳng singleton); type/lint lỏng (`strict` tắt, nhiều suppress); CI không chạy check/test/e2e. Tuỳ chọn: chạy `surfaces.<key>.check` trong `WT` theo protocol §9 để đếm lỗi thật — chỉ khi deps đã có hoặc cài nhanh.

## 4. Ưu tiên

Sửa ở nơi hay đổi: vấn đề trong hotspot, hoặc chặn hướng sản phẩm sắp đi (`FOCUS`, backlog) ⇒ lên đầu. Code ổn định ít đổi ⇒ chỉ ghi khi là rủi ro bảo mật, dữ liệu, hiệu năng. Không đề xuất viết lại toàn bộ, đổi framework, hay đổi gu trái `CLAUDE.md`. Một phát hiện = một gốc, kèm mọi chỗ nó xuất hiện.

## 5. Body ticket (Task; Bug khi đang gây lỗi cho người dùng)

`### Vấn đề` (nguyên tắc bị vi phạm) · `### Bằng chứng` (`path:line`, số đo radar) · `### Tác động` (kịch bản cụ thể, vd "thêm một phương thức thanh toán phải sửa 5 file ở 3 tầng", "lỗi thanh toán không có log để truy") · `### Hướng đề xuất` (đích đến + các bước an toàn, mỗi bước một commit; SA chốt chi tiết) · `### Rủi ro khi sửa` (vùng dùng chung, flow regression nên chạy) · `### Tiêu chí nghiệm thu`: hành vi người dùng không đổi (flow `…` pass) + tiêu chí cấu trúc đo lại được bằng `agentflow-audit scan` hoặc grep (vd "cycle `a` ↔ `b` không còn", "không còn import `data/` trong `domain/`", "0 catch rỗng trong `<path>`") · `### Ngoài phạm vi`.
