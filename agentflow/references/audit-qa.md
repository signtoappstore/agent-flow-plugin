# Audit QA & UX — chuyên gia automation mobile/web

Mục tiêu: biết sản phẩm **đang hỏng hay khó dùng ở đâu** và **lưới automation có giữ được chất lượng không** — bằng chạy thật trên staging và ảnh chụp, không bằng đoán. `automation.md` là chuẩn viết và chạy flow: theo đúng nó.

## 1. Hành trình chính (CUJ)

- Nguồn: tài liệu `design.repo`, README, router/màn/deep link trong `WT` (grep, không đọc logic), `FOCUS`.
- ≤ 12 CUJ theo mức quan trọng với người dùng và kinh doanh: đăng ký/đăng nhập, onboarding, vòng giá trị chính, giao dịch/thanh toán, tạo-sửa-xoá dữ liệu, tìm kiếm, tài khoản/cài đặt, thông báo. Mỗi CUJ: vai trò, điểm vào, bước chính, nền tảng.

## 2. Lưới automation

`cd <WT> && agentflow-audit flows` → map flow ↔ CUJ, rồi đọc flow đại diện:
- **Độ phủ**: CUJ không có flow; flow không assert kết quả người dùng thấy; chỉ happy path (thiếu lỗi, rỗng, quyền, mất mạng); hành vi chỉ ở server không có test `api`.
- **Độ vững** (mỗi loại một phát hiện, liệt kê file): `stale_ids` (code không còn id ⇒ flow chết; id ghép bởi hàm cũng hiện ở đây — mở code trước khi kết luận), `vacuous_ids` (`assertNotVisible` id code không có ⇒ luôn pass), `no_assert`, `optional`/`retry` che lỗi, `point`, chọn bằng chữ thay id (vỡ khi đổi chữ, đổi ngôn ngữ), thiếu `clearState` (phụ thuộc thứ tự), thiếu tag, mật khẩu literal, AI assert; spec Playwright/Cypress/Flutter: chờ cứng, `only`/`skip`, xpath/nth, test không assert.
- **Chiến lược** (Task): tag `smoke` cho CUJ chạy sau mỗi lần deploy staging, tag vùng cho `e2e_map`, quy ước id + gắn id cho màn CUJ, dữ liệu test riêng và dọn, ma trận thiết bị (màn nhỏ, chữ lớn, ngôn ngữ), cả suite trong CI (`surfaces.<key>.e2e`).

## 3. Chạy trên staging

Cần `staging.url` (web) hoặc thiết bị (mobile) + `maestro` trong `RUNTIME`; thiếu ⇒ bỏ phần chạy của nền tảng đó, ghi "Không chạy được".
- **Flow có sẵn** của CUJ (≤ 15, ưu tiên `smoke`): `agentflow-e2e run --issue 0 --reset --dir "<WT>/<surface path>" --name <key> [--install] [--maestro="…"] [--env-file <file>] <flows>` rồi `agentflow-e2e wait --issue 0` (`--issue 0` = audit; env, thiết bị theo `automation.md` §Chạy, §Maestro). Fail ⇒ chạy lại riêng flow đó: fail cả hai = lỗi (đọc log, mở ảnh), pass lần sau = chập chờn (phát hiện độ vững).
- **Flow thăm dò** cho CUJ chưa có flow: viết trong `<WT>/<surface path>/<e2e_dir, không có thì .maestro>/_audit/`, dùng lại subflow đăng nhập, đi như người dùng, `takeScreenshot: audit-<cuj>-<state>` ở mỗi state đáng soát (vào màn, loading/rỗng, nhập sai, lỗi, thành công). Biến thể khi CUJ có rủi ro hiển thị: màn nhỏ (web `--maestro="--headless --screen-size 390x844"`), quay lại/huỷ giữa chừng, chuỗi dài có dấu.
- Không thanh toán/gửi thật, không tạo dữ liệu hàng loạt; dữ liệu tự tạo tiền tố `af-audit-`, dọn sau khi chạy. Bước tiếp theo không an toàn ⇒ dừng flow ở đó.
- **Bug** (crash, kết quả sai, treo loading, lỗi hiển thị): tái hiện 2 lần, ghi `staging @<sha>` (`git ls-remote origin <staging.branch>`). Vùng đó có trong `git log origin/<base>..origin/<staging.branch>` ⇒ ghi "có thể do ticket đang làm #m", hạ `sev` một bậc.

## 4. Soi UI/UX trên ảnh

Read ảnh trong `out` của lượt chạy, ≤ 30 ảnh mỗi lượt, mỗi state một ảnh. Soát:
- **Trạng thái**: thao tác có phản hồi ngay, loading có chỉ báo, thành công/lỗi được báo, nút disabled nói vì sao.
- **Lỗi**: nói người dùng làm gì tiếp, giữ dữ liệu đã nhập, không lộ mã kỹ thuật.
- **Nhất quán**: cùng hành động cùng nhãn, vị trí, kiểu nút; khớp design (`design.repo`; Figma `get_screenshot` khi issue có link).
- **Hiển thị**: chữ cắt/tràn/chồng, dấu tiếng Việt bị xén, sai ngôn ngữ, vỡ bố cục ở màn nhỏ, bàn phím che ô nhập, tai thỏ/vùng an toàn.
- **Tiếp cận**: vùng chạm < 44pt/48dp, chữ tương phản thấp (ước WCAG AA 4.5:1), icon bấm được không có nhãn — `maestro hierarchy` lúc màn đang mở: phần tử clickable thiếu text/accessibility label.
- **Ma sát**: số bước, ô bắt buộc của CUJ; ngõ cụt; hành động không hoàn tác được mà không xác nhận; xác nhận thừa.

Lệch AC/design đã chốt ⇒ Bug, còn lại ⇒ Improvement; `evidence` = tên ảnh + state.

## 5. Body ticket

- **Bug**: Các bước tái hiện · Kết quả mong đợi · Kết quả thực tế (chữ lỗi chính xác) · Môi trường (`staging @<sha>`, thiết bị/trình duyệt) · Tần suất · Bằng chứng (ảnh, đoạn log) · **Flow tái hiện** (YAML của flow thăm dò, `${VAR}` thay mọi giá trị secret) để DEV dùng lại · AC.
- **Automation** (Task): CUJ → bảng TC (`TC · bước → kỳ vọng · e2e/api/tay`) theo `automation.md` §Test case; flow hỏng → file + lỗi + hướng sửa; AC: flow pass `--repeat 3` trên staging và fail khi bỏ hành vi nó kiểm.
- **UX** (Improvement): hiện trạng (ảnh + state) · vấn đề với người dùng · hướng đề xuất (không vẽ lại màn) · AC người dùng quan sát được.
