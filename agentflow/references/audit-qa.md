# Audit QA — tester automation mobile/web, test theo từng role

Mục tiêu: biết sản phẩm **đang hỏng hay khó dùng ở đâu, với role nào** và **lưới automation có giữ được chất lượng không**, bằng chạy thật trên staging và ảnh chụp, không bằng đoán. Bạn cũng gom **bộ bằng chứng** cho hội đồng (UI/UX, Product, Engineering) đọc sau bạn. `automation.md` là chuẩn viết và chạy flow: theo đúng nó.

## 1. Bản đồ, role, kế hoạch

- `MAP`: `roles` (gợi ý theo code, `hits`), `accounts` (role → tên key tài khoản test), `env_files`, `missing_accounts`, `unguarded` (endpoint không thấy chữ auth gần đó). `PLAN.selected`: vùng lượt này, theo thứ tự, kèm `why` (`verify #n` · `changed` · `new` · `stale`/`open bug`) và ô cũ của từng role.
- **Role thật** = người dùng thật của sản phẩm (bỏ từ code không phải vai người dùng): `MAP.roles` ∪ role có tài khoản, thêm `guest` khi có màn công khai. Cột bảng phủ giữ đúng tên của lần trước (`PLAN.roles`); role mới thêm cột.
- Mỗi vùng, mỗi role: **được phép** (vào được, làm được việc chính của vùng) hay **bị chặn**. Căn cứ: tài liệu `design.repo`, guard/middleware/menu theo role trong code (grep, không đọc logic). Không rõ ⇒ thử, rồi ghi suy luận.
- Hành trình chính (CUJ) của mỗi role: đăng ký/đăng nhập, onboarding, vòng giá trị chính, giao dịch/thanh toán, tạo-sửa-xoá, tìm kiếm, tài khoản/cài đặt, thông báo, màn quản trị của role đó.

## 2. Lưới automation

`cd <WT> && agentflow-audit flows` → map flow ↔ CUJ × role, rồi đọc flow đại diện:
- **Độ phủ**: CUJ/role không có flow; flow không assert kết quả người dùng thấy; chỉ happy path (thiếu lỗi, rỗng, quyền, mất mạng); không flow nào kiểm role bị chặn; hành vi chỉ ở server không có test `api`.
- **Độ vững** (mỗi loại một phát hiện, liệt kê file): `stale_ids` (mở code trước khi kết luận: id ghép lúc chạy cũng hiện ở đây), `vacuous_ids`, `no_assert`, `optional`/`retry` che lỗi, `point`, chọn bằng chữ thay id, thiếu `clearState`, thiếu tag, mật khẩu literal, AI assert; spec Playwright/Cypress/Flutter: chờ cứng, `only`/`skip`, xpath/nth, không assert.
- **Chiến lược** (Task): tag `smoke` cho CUJ chạy sau mỗi deploy staging, tag vùng cho `e2e_map`, subflow đăng nhập nhận role, quy ước id, dữ liệu test riêng và dọn, ma trận thiết bị.

## 3. Chạy ma trận vùng × role trên staging

Cần `staging.url` (web) hoặc thiết bị (mobile) + `maestro` trong `RUNTIME`; thiếu ⇒ nền tảng đó chỉ soát tĩnh, ghi "Không chạy được". Env: `--env-file <f>` cho mỗi `MAP.env_files` (không Read file đó); flow dùng `${E2E_<ROLE>_EMAIL}`… như `MAP.accounts`.
- **Lệnh**: `agentflow-e2e run --issue 0 --dir "<WT>/<surface path>" --name <key> [--install] [--maestro="…"] [--env-file <file>] <flows>` rồi `agentflow-e2e wait --issue 0` (`--issue 0` = audit; `--reset` chỉ lần chạy đầu tiên vì nó xoá ảnh của lượt trước). Sau mỗi `wait`: chép ảnh ra `EVIDENCE/` trước lượt chạy kế.
- Theo thứ tự `PLAN.selected`, trần mỗi lượt: ≤ 25 lần chạy flow, ≤ 40 ảnh. Vùng chưa tới giữ `·`, lần sau `plan` đưa lên đầu.
- **verify #n**: `issue_read` #n, chạy lại "Flow tái hiện" (hay các bước) của nó. Pass ⇒ `#n ✓`; còn lỗi ⇒ phát hiện `regressed: #n`.
- **Được phép**: flow có sẵn của CUJ (ưu tiên `smoke`), CUJ chưa có flow thì viết **flow thăm dò** trong `<WT>/<surface path>/<e2e_dir, không có thì .maestro>/_audit/`, dùng lại subflow đăng nhập với tài khoản của role. Đi như người dùng, `takeScreenshot: audit-<vùng>-<role>-<state>` ở mỗi state đáng soát (vào màn, loading/rỗng, nhập sai, lỗi, thành công). Thêm biến thể khi vùng có rủi ro hiển thị: màn nhỏ (web `--maestro="--headless --screen-size 390x844"`), quay lại/huỷ giữa chừng, chuỗi dài có dấu.
- **Bị chặn**: role không được phép mở thẳng URL/deep link của vùng và gọi một API của vùng (`runScript` `http` với phiên của role, hoặc `curl` vào `staging.url`). Bị chuyển hướng, 401/403, không lộ dữ liệu ⇒ `⛔`. Vào được hay thấy dữ liệu ⇒ Bug `cao`, `role:` = role đó, fp `qa/<vùng>/authz-<role>`.
- **Dữ liệu không lộ chéo**: hai tài khoản cùng role (hoặc id của tài khoản khác trong URL/API) ⇒ không xem hay sửa được dữ liệu của nhau. Chỉ khi có đủ tài khoản.
- Không thanh toán/gửi thật, không tạo dữ liệu hàng loạt; dữ liệu tự tạo tiền tố `af-audit-`, dọn sau khi chạy. Bước tiếp theo không an toàn ⇒ dừng flow ở đó.
- **Bug** (crash, kết quả sai, treo loading, lỗi hiển thị, sai quyền): tái hiện 2 lần, ghi `staging @<sha>` (`git ls-remote origin <staging.branch>`) và role. Fail lần đầu, pass lần sau = chập chờn (phát hiện độ vững). Vùng đó có trong `git log origin/<base>..origin/<staging.branch>` ⇒ ghi "có thể do ticket đang làm #m", hạ `sev` một bậc.

## 4. Bộ bằng chứng cho hội đồng

`EVIDENCE/index.md`, mỗi ảnh một dòng: `<file> · <vùng> · <role> · <state> · <bước dẫn tới> · <điều thấy: lỗi hiện ra, lỗi console/mạng trong log, chờ > 3 s>`. Mỗi CUJ thêm một dòng: role · số bước · số ô bắt buộc · thời gian · ngõ cụt. Hội đồng chỉ đọc file này và ảnh nó trỏ tới: ghi đủ để họ không phải chạy lại.

## 5. Soi ảnh tìm lỗi

Read ảnh trong `EVIDENCE/`, mỗi state một ảnh: lỗi **chức năng** và lỗi **hiển thị thấy rõ** (chữ cắt/tràn/chồng, dấu tiếng Việt bị xén, sai ngôn ngữ, vỡ bố cục ở màn nhỏ, bàn phím che ô nhập, không phản hồi khi bấm, lỗi lộ mã kỹ thuật, mất dữ liệu đã nhập). Còn chuyện thẩm mỹ, nhất quán, hệ thiết kế thì để ux. Lệch AC/design đã chốt ⇒ Bug; `evidence` = tên ảnh + state + role.

## 6. Bảng phủ — file `COVER`

```
## Bản đồ phủ
| Vùng | <role> | <role> | … |
|---|---|---|---|
| <tên vùng đúng như PLAN> | ✓ | ✗ qa:F2 | ⛔ |
## Xác minh sửa
- #12 ✓
```

`✓` được phép và đạt · `✗ <id phát hiện>` lỗi · `⛔` bị chặn đúng quyền · `·` chưa test · `—` role không áp dụng (vd guest ở vùng chỉ dành cho người đã đăng nhập, khi đã kiểm bị chặn ở vùng khác). Chỉ ghi dòng của vùng đã test lượt này.

## 7. Body ticket

- **Bug**: Các bước tái hiện · Kết quả mong đợi · Kết quả thực tế (chữ lỗi chính xác) · Môi trường (`staging @<sha>`, thiết bị/trình duyệt, role, tên key tài khoản) · Tần suất · Bằng chứng (ảnh, đoạn log) · **Flow tái hiện** (YAML của flow thăm dò, `${VAR}` thay mọi giá trị secret) để DEV và lần checklist sau dùng lại · AC.
- **Sai quyền**: role · vùng · cách vào (URL/API) · thấy gì · kỳ vọng (chặn ở server, không chỉ ẩn nút) · AC: role đó nhận 403/chuyển hướng ở cả UI lẫn API, flow kiểm bị chặn pass.
- **Automation** (Task): CUJ × role → bảng TC (`TC · role · bước → kỳ vọng · e2e/api/tay`) theo `automation.md` §Test case; flow hỏng → file + lỗi + hướng sửa; **flow thăm dò đã pass** đáng giữ → ≤ 3 flow YAML mỗi ticket "Đưa flow thăm dò vào regression: <vùng>". AC: flow pass `--repeat 3` trên staging và fail khi bỏ hành vi nó kiểm.
