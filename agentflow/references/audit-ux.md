# Audit UI/UX — expert UI/UX designer

Mục tiêu: chỉ ra chỗ giao diện **làm người dùng nhầm, chậm, bỏ dở hay mất tin**, và đề xuất cách làm sản phẩm **đẹp hơn, nhất quán hơn** dựa trên chính hệ thiết kế của nó. Mỗi ý phải gắn với ảnh, không nói theo gu. Luật repo và design đã chốt thắng gu riêng.

## 1. Nắm hệ thiết kế (đọc ít)

- Token: màu, chữ, khoảng cách, bo góc, đổ bóng. Tìm bằng grep `tailwind.config`, `theme`, `tokens`, CSS variables, `ThemeData`, `colors.dart`, `AppColors`. Thêm thư viện component dùng chung, dark mode, ngôn ngữ hỗ trợ.
- Design đã chốt: `design.repo`, link Figma trong issue/tài liệu (`get_screenshot`, chỉ đọc). Không có ⇒ chuẩn là pattern đang dùng nhiều nhất trong app.
- Đo nhanh độ lệch token: grep màu hex hoặc cỡ chữ viết cứng trong code UI, đếm file. Đó chỉ là chỗ cần nhìn, chưa phải phát hiện.

## 2. Đọc bằng chứng

`EVIDENCE/index.md` rồi ≤ 40 ảnh: mỗi vùng × role một ảnh mặc định, cộng các state loading/rỗng/lỗi/thành công, màn nhỏ. Đọc theo role: admin cần bảng dày, lọc nhanh; người dùng di động cần ít bước, chạm dễ; guest cần hiểu giá trị trước khi đăng ký. Không có `EVIDENCE` ⇒ đọc component của màn trong `PLAN`/`MAP` và soát tĩnh.

## 3. Soát

- **Thứ bậc thị giác**: mỗi màn một hành động chính nổi bật; tiêu đề, nội dung, phụ đề tách rõ; mắt đi đúng thứ tự công việc.
- **Nhịp và lưới**: khoảng cách theo thang token (4/8), canh lề thẳng, mật độ hợp role; cỡ chữ ≤ 5 bậc; độ dài dòng dễ đọc.
- **Nhất quán**: cùng hành động cùng nhãn, vị trí, kiểu nút, icon; cùng component cho cùng việc; màu mang nghĩa (lỗi, cảnh báo, thành công) dùng thống nhất.
- **Trạng thái**: phản hồi ngay khi bấm, skeleton/loading có chỉ báo, rỗng có hướng dẫn + hành động, lỗi nói làm gì tiếp và giữ dữ liệu đã nhập, thành công được xác nhận, nút disabled nói vì sao.
- **Form**: nhãn luôn thấy, kiểm tra ngay tại ô, bàn phím đúng kiểu, tự điền, ô bắt buộc tối thiểu, thông báo lỗi cạnh ô.
- **Điều hướng**: biết mình ở đâu, quay lại được, không ngõ cụt; hành động không hoàn tác được thì có xác nhận, xác nhận thừa thì bỏ.
- **Hiển thị**: chữ cắt/tràn, dấu tiếng Việt bị xén, chuỗi dài, tai thỏ/vùng an toàn, bàn phím che ô, màn nhỏ và chữ lớn, dark mode.
- **Tiếp cận**: tương phản chữ ≥ 4.5:1 (ước từ ảnh), vùng chạm ≥ 44pt/48dp, icon bấm được có nhãn (`maestro hierarchy` khi qa ghi), không truyền nghĩa chỉ bằng màu.
- **Cảm nhận và tin cậy**: ảnh/icon sắc nét, đồng bộ phong cách; số tiền, phí, quyền riêng tư hiển thị minh bạch; microcopy rõ, cùng giọng.

## 4. Sáng kiến đẹp hơn

Ý **nâng thẩm mỹ** (Improvement) chỉ dùng token và component đang có, hoặc đề xuất thêm đúng một token còn thiếu. Ví dụ: thống nhất bo góc và đổ bóng card, skeleton thay spinner, rỗng có minh hoạ + CTA, header gọn hơn, CTA chính tương phản hơn, nhịp khoảng cách đều. Một gốc ⇒ một phát hiện kèm mọi màn áp dụng. Không vẽ lại cả màn, không đổi nhận diện thương hiệu.

## 5. Hội chẩn và mức độ

Mục của qa về hiển thị/trải nghiệm ⇒ `extends`, nêu hướng thiết kế sửa (token, component, bố cục). `sev`: `cao` = cản việc chính (không đọc được, nút bị che, không bấm được, hiểu sai số tiền) · `vừa` = gây nhầm, chậm, lệch design đã chốt · `thấp` = đánh bóng, thẩm mỹ. Lệch design đã chốt ⇒ Bug, còn lại ⇒ Improvement.

## 6. Body ticket

`### Hiện trạng` (ảnh + state + role) · `### Vấn đề với người dùng` (nguyên tắc bị vi phạm, ai bị ảnh hưởng) · `### Hướng thiết kế` (token/component, bố cục, các màn áp dụng; mô tả bằng chữ) · `### Tiêu chí nghiệm thu` (quan sát được, vd "tương phản CTA ≥ 4.5:1", "mọi card dùng `radius.md` + `shadow.sm`", "màn rỗng có minh hoạ + nút tạo mới") · `### Ngoài phạm vi`. Không dùng lệnh `*WithAI` (gửi ảnh staging ra ngoài).
