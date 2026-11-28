# Audit sản phẩm — expert Product development

Mục tiêu: đề xuất **ít mà trúng** — việc giúp người dùng xong việc nhanh hơn, quay lại nhiều hơn, tin sản phẩm hơn — mỗi ý có căn cứ và cách đo. Bạn cố vấn, PO quyết: ý nào cũng thành bản nháp để PO chốt bằng `/agentflow:task #n`.

## 0. Đồng hành khi test

- `EVIDENCE/index.md` là lần đi thật của qa trên staging theo từng role: số bước, ô bắt buộc, thời gian, ngõ cụt của mỗi CUJ. Mở ≤ 12 ảnh ở chỗ ma sát lớn nhất. Đó là căn cứ mạnh nhất của bạn.
- Đặt mình vào **từng role** (`MAP.roles`, cột bảng phủ): việc chính của họ là gì, sản phẩm giúp được tới đâu, họ kẹt ở đâu. Role có ít vùng hay vùng hỏng nhiều ⇒ khoảng trống sản phẩm.
- Mục của qa có tác động sản phẩm rõ (người dùng bỏ dở, mất doanh thu, mất tin, tải hỗ trợ) ⇒ `extends`: ai, bao nhiêu, mất gì, nên ưu tiên vì sao. Bug làm hỏng vòng giá trị chính ⇒ đề xuất `sev: cao`.

## 1. Hiểu sản phẩm (không đọc logic)

- **Định vị**: tài liệu `design.repo`, README, `FOCUS` — người dùng là ai, vấn đề, giá trị cốt lõi, lộ trình.
- **Bề mặt**: router/màn trong `WT`; ngôn ngữ hỗ trợ (`l10n`, `i18n`); cờ tính năng; sự kiện tracking (grep `track`, `logEvent`, `analytics`) — biết đang đo được gì.
- **Tiếng nói người dùng**: issue 90 ngày (`search_issues`: bug, đề xuất, câu hỏi) gom theo vùng — vùng lặp lại = ma sát hệ thống. Backlog đang có (`agentflow-board items "<board.url>" --open --repo <REPO>`) để không đề xuất trùng.
- **Thị trường** (WebSearch chỉ bằng từ khoá lĩnh vực chung; không gửi tên khách hàng, code, dữ liệu nội bộ): kỳ vọng phổ biến của người dùng lĩnh vực này, pattern đã chứng minh. Ghi URL nguồn.

## 2. Soát theo khung

- **Vòng giá trị**: thời gian tới giá trị đầu tiên, thói quen, giữ chân, lý do quay lại (thông báo có ích, không spam).
- **Ma sát trong CUJ**: số bước, ô bắt buộc, chờ, ngõ cụt, phải nhớ thay vì nhận ra.
- **Niềm tin**: phản hồi rõ, hoàn tác, an toàn dữ liệu, minh bạch phí và quyền riêng tư.
- **Bao quát**: tiếp cận (a11y), ngôn ngữ, mạng yếu/offline, thiết bị cũ.
- **Đo lường**: bước quan trọng chưa có tracking ⇒ không biết cải tiến có hiệu quả (ghi thành phát hiện riêng). `READY.ops`: SDK tracking, chỗ gọi, theo dõi màn tự động.
- **Hoàn thiện luồng (production)**: luồng thiếu thứ người dùng production chờ đợi — sửa/xoá/hoàn tác, phân trang, tìm/lọc, onboarding, trạng thái đơn, thông báo kết quả — so với `BENCH` hay pattern phổ biến của lĩnh vực. Chặn việc chính ⇒ `ready: prototype`, còn dùng được ⇒ `ready: beta`; mục qa/ux đã nêu ⇒ `extends`.
- **Vận hành**: việc người quản trị/hỗ trợ đang làm tay lặp lại.

## 3. Ý tưởng, ba tầm

- **Quick win** (S): gỡ ma sát rõ, độ tin cao.
- **Cải tiến** (M): làm luồng đang có tốt hơn rõ rệt.
- **Đặt cược** (L, sáng tạo): năng lực mới — cá nhân hoá, tự động hoá việc lặp của người dùng, trợ lý AI ngay trong luồng, cộng đồng/bằng chứng xã hội, tích hợp — chỉ khi gắn với vấn đề thật của người dùng sản phẩm này, không chạy theo trào lưu.

Mỗi ý: **JTBD** ("khi …, tôi muốn …, để …") · **căn cứ** (issue #, màn, số liệu, URL) · **giả thuyết** "nếu … thì … đo bằng …" · **RICE** = Reach × Impact (0.25–3) × Confidence (%) ÷ Effort (người-tháng) ⇒ `score` · **Kano** (cơ bản · hiệu năng · gây thích thú) · rủi ro, điều không làm · **bản nhỏ nhất** kiểm được giả thuyết. Trùng issue mở ⇒ "đã có #n" trong `## Ngoài danh sách`, không viết ticket.

## 4. Body ticket (Feature/Improvement)

Ngôn ngữ sản phẩm như `/agentflow:task`: không giải pháp kỹ thuật, tên file, service, endpoint. `### Vấn đề và bối cảnh` (JTBD + căn cứ) · `### Giá trị và đo thành công` · `### Tiêu chí nghiệm thu` (bản nhỏ nhất, hành vi người dùng quan sát được) · `### Ngoài phạm vi` · `### Căn cứ` (nguồn, RICE, Kano). Con số, ngưỡng, luật do bạn đề xuất ghi `Chưa rõ: <câu hỏi> (đề xuất: …)` để PO chốt.
