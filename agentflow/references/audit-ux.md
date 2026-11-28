# Audit UI/UX — expert UI/UX designer

Mục tiêu: chỉ ra chỗ giao diện **làm người dùng nhầm, chậm, bỏ dở hay mất tin**, chỗ sản phẩm **còn là prototype, chưa đạt production** ở thời điểm chạy, và cách làm nó **đẹp hơn, nhất quán hơn** dựa trên chính hệ thiết kế của nó. Mỗi ý phải gắn với ảnh hoặc số đo, không nói theo gu. Luật repo và design đã chốt thắng gu riêng.

## 1. Nắm hệ thiết kế và chuẩn (đọc ít)

- `READY` (JSON `agentflow-audit ready`): `design_system.token_files` (token màu, chữ, khoảng cách, bo góc, đổ bóng), `hardcoded` (màu/font/spacing lệch lưới 4 viết cứng ngoài token), `font_sizes`, `radii` (giá trị đang dùng), `icon_sets`/`icon_mixed`, `emoji`; `prototype`; `assets`; `identity`; `fonts`; `copy`; `states`; `areas` (tín hiệu theo vùng). Số chỉ nói **chỗ cần nhìn**, đọc code hoặc ảnh rồi mới kết luận.
- Design đã chốt: `design.repo`, link Figma trong issue/tài liệu (`get_screenshot`, chỉ đọc). Không có ⇒ chuẩn là pattern đang dùng nhiều nhất trong app.
- **Chuẩn production**: hệ thiết kế trong code · chuẩn nền tảng (Apple HIG, Material 3, WCAG 2.2 AA: vùng chạm, vùng an toàn, cỡ icon, app icon/splash) · mốc lĩnh vực: `BENCH`, trống ⇒ WebSearch ≤ 3 app cùng lĩnh vực bằng từ khoá lĩnh vực chung (không gửi tên sản phẩm, code, dữ liệu nội bộ), ghi URL nguồn. Mục chỉ dựa trên mốc lĩnh vực ⇒ Improvement, không bao giờ Bug.

## 2. Đọc bằng chứng

`EVIDENCE/index.md` rồi ≤ 40 ảnh: mỗi vùng × role một ảnh mặc định, cộng các state loading/rỗng/lỗi/thành công, màn nhỏ. Đọc theo role: admin cần bảng dày, lọc nhanh; người dùng di động cần ít bước, chạm dễ; guest cần hiểu giá trị trước khi đăng ký. Không có `EVIDENCE` ⇒ đọc component của màn trong `PLAN`/`MAP` và soát tĩnh.

## 3. Soát trải nghiệm

- **Thứ bậc, nhịp**: mỗi màn một hành động chính nổi bật; tiêu đề, nội dung, phụ đề tách rõ; khoảng cách theo thang token (4/8), canh lề thẳng, mật độ hợp role; cỡ chữ ≤ 5 bậc.
- **Nhất quán**: cùng hành động cùng nhãn, vị trí, kiểu nút, icon; cùng component cho cùng việc; màu mang nghĩa (lỗi, cảnh báo, thành công) thống nhất.
- **Trạng thái**: phản hồi ngay khi bấm; loading có chỉ báo; rỗng có hướng dẫn + hành động; lỗi nói làm gì tiếp, giữ dữ liệu đã nhập; thành công được xác nhận; disabled nói vì sao.
- **Form, điều hướng**: nhãn luôn thấy, kiểm tra tại ô, bàn phím đúng kiểu; biết mình ở đâu, quay lại được, không ngõ cụt; hành động không hoàn tác được thì xác nhận.
- **Hiển thị, tiếp cận**: chữ cắt/tràn, dấu tiếng Việt bị xén, tai thỏ, bàn phím che ô, chữ lớn, dark mode; tương phản ≥ 4.5:1, vùng chạm ≥ 44pt/48dp, icon bấm được có nhãn, không truyền nghĩa chỉ bằng màu.

## 4. Soát mức production

- **Dấu vết prototype**: lorem, dữ liệu/người giả, ảnh placeholder, "sắp ra mắt", nút hay link không làm gì, màn chưa nối API, lỗi hiện mã kỹ thuật, tiêu đề/tên app/file mẫu của template (`prototype.*`).
- **Design system**: màu, font, spacing, bo góc viết cứng hay nhiều giá trị lẻ; component tự chế trùng việc với component chung; font mặc định của hệ điều hành khi sản phẩm có thương hiệu (`fonts.custom`).
- **Icon**: trộn bộ icon hay kiểu (filled lẫn outlined) trong cùng một UI, emoji làm icon, icon raster nhỏ thay vector, cỡ/nét không đều.
- **Asset & hình ảnh**: ảnh mờ, vỡ, méo; thiếu @2x/@3x hay density Android; ảnh nặng làm màn tải chậm; ảnh tham chiếu không có; ảnh sáng chói trong dark mode (`assets.*`).
- **Graphic & minh hoạ**: màn rỗng, onboarding, lỗi không có minh hoạ hay minh hoạ lệch phong cách nhau; ảnh stock trông giả; không đồng bộ nhận diện thương hiệu.
- **Nhận diện app**: app icon (đủ cỡ, 1024 cho store, adaptive Android), splash, favicon, manifest, ảnh chia sẻ, tên hiển thị (`identity`).
- **Chữ**: chuỗi chưa dịch hay tiếng Anh lẫn tiếng Việt (`copy`), giọng văn không đồng nhất, định dạng tiền/ngày/số sai thói quen địa phương.

## 5. Sáng kiến đẹp hơn

Ý **nâng thẩm mỹ** (Improvement) chỉ dùng token và component đang có, hoặc đề xuất thêm đúng một token còn thiếu: thống nhất bo góc và đổ bóng card, skeleton thay spinner, rỗng có minh hoạ + CTA, CTA chính tương phản hơn, nhịp khoảng cách đều. Một gốc ⇒ một phát hiện kèm mọi màn áp dụng. Không vẽ lại cả màn, không đổi nhận diện thương hiệu.

## 6. Hội chẩn, mức độ, mức sẵn sàng

- Mục của qa về hiển thị/trải nghiệm ⇒ `extends`, nêu hướng thiết kế sửa; mục đó là dấu vết prototype ⇒ thêm `- ready: prototype` vào góc nhìn.
- `sev`: `cao` = cản việc chính (không đọc được, nút bị che, hiểu sai số tiền) hoặc dấu vết prototype người dùng thấy trên luồng chính, thiếu app icon/splash · `vừa` = gây nhầm, chậm, lệch design đã chốt, lệch design system hay asset người dùng thấy · `thấp` = chỉ lệch trong code, đánh bóng. Lệch design đã chốt ⇒ Bug, còn lại ⇒ Improvement.
- `- ready:` trên mục chặn vùng của nó khỏi production: `prototype` = dấu vết prototype người dùng thấy, luồng chính chưa nối, thiếu state lỗi/rỗng ở màn chính · `beta` = dùng được nhưng còn lệch design system/asset mức vừa.
- **Bảng mức** cuối `OUT`, chỉ vùng có ô `✓`/`✗`/`⛔` trong `COVER` (tên đúng như bảng phủ):

```
## Mức sẵn sàng
| Vùng | Mức | Lý do |
|---|---|---|
| <vùng> | Prototype | qa:F2, ux:F4 — <một câu> |
```

Mức theo mục dẫn ra (của mọi lăng kính, kể cả Bug của qa): có `ready: prototype` ⇒ Prototype · có `ready: beta` hoặc `sev` cao/vừa ⇒ Beta · còn lại ⇒ Production. Prototype và Beta phải dẫn ít nhất một mục; `agentflow-audit findings` từ chối mức lệch với mục dẫn ra.

## 7. Body ticket

`### Hiện trạng` (ảnh + state + role) · `### Vấn đề với người dùng` (nguyên tắc hay chuẩn production bị vi phạm, ai bị ảnh hưởng) · `### Hướng thiết kế` (token/component, bố cục, các màn áp dụng; mô tả bằng chữ) · `### Asset cần` khi thiếu asset (tên, cỡ, định dạng vector/raster, @2x/@3x hay density, bản dark, nơi dùng) · `### Tiêu chí nghiệm thu` (quan sát được, vd "tương phản CTA ≥ 4.5:1", "mọi card dùng `radius.md`", "không còn emoji làm icon", "app icon đủ cỡ, có bản 1024") · `### Ngoài phạm vi`. Không dùng lệnh `*WithAI` (gửi ảnh staging ra ngoài).
