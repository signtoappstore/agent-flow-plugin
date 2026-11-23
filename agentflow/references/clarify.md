# Làm rõ yêu cầu — auto · ask

Đọc khi: `/agentflow:task` (§Task), orchestrator chế độ ask (§Điều phối), SA nhận `CLARIFY: ask|ask-live` (§SA).

## Chế độ

Hai cổng: `task` (trước khi ghi ticket) và `implement` (trước khi DEV code). Chế độ đọc từ `clarify.<cổng>` trong `agentflow.yaml` của repo; thiếu key hoặc thiếu cả block ⇒ `ask`.

- **auto** — agent tự phân tích, chọn phương án tốt nhất và hợp nhất (tài liệu sản phẩm, hành vi đang chạy, tech stack, pattern sẵn có), ghi mỗi quyết định kèm căn cứ để người soát sau. Chỉ dừng hỏi khi thiếu thứ không suy ra được.
- **ask** — agent đưa **điểm cần chọn** (≤ 4 mỗi lượt, mỗi điểm 2–4 phương án, đề xuất đứng đầu kèm "(Recommended)", mỗi phương án nói được/mất), người chọn; rồi trình **Sẽ thực hiện** (danh sách việc sẽ làm theo lựa chọn) để người xác nhận lần cuối. Chưa xác nhận ⇒ không ghi ticket, DEV không bắt đầu.

Điểm cần chọn chỉ gồm thứ làm đổi kết quả: cách hiểu yêu cầu mơ hồ, phạm vi, hành vi người dùng thấy, giải pháp khi ≥ 2 cách khả thi có đánh đổi thật. Không hỏi điều tài liệu, `CLAUDE.md`, pattern sẵn có đã quyết. Không có điểm nào ⇒ bỏ bước chọn, vẫn trình Sẽ thực hiện.

## Task

**ask** — skill §2–§9 như viết, thêm:
- Mục §3 có ≥ 2 hướng sản phẩm hợp lý (phạm vi, luồng, luật) → AskUserQuestion, option = hướng, preview = được/mất khi cần so.
- Thay "chờ PO duyệt" của §4: trình bản nháp kèm **Sẽ thực hiện**, mỗi issue một dòng `<tạo | sửa #n> "<tiêu đề>" · type · <k> AC · Priority/Size/Platform · assignee · milestone · cha/sub · Bị chặn/Liên quan`, rồi `→ <board.status.backlog>` + comment `[AF:SPEC]`. AskUserQuestion: "Ghi lên GitHub (Recommended)" · "Sửa" (hỏi sửa gì, soạn lại, trình lại) · "Huỷ" (không ghi gì). Chỉ chạy §5 sau "Ghi lên GitHub".

**auto** — §1, §2 như viết; thay phần hỏi của §3 và bước duyệt nháp của §4:
- Không hỏi (trừ khi không có mô tả). Mỗi điểm mở của checklist §3 tự chọn theo thứ tự căn cứ: tài liệu/design → hành vi đang chạy → bản nhỏ nhất vẫn có giá trị và an toàn cho người dùng (có đường lỗi, không mất dữ liệu).
- Luật, con số, ngưỡng tự đặt vào section cuối body `### Giả định (agent tự chọn)`, mỗi dòng `- <quyết định> — <căn cứ>`, thay cho `Chưa rõ`. Thứ chỉ PO biết mà không có căn cứ (bằng chứng bug, hạn chót, đối tác) → vẫn `Chưa rõ` + `needs_info`.
- Trùng gần giống → tạo mới kèm `Liên quan #m`; trùng hẳn → không tạo, báo #m. Cấu trúc theo dấu hiệu §3: chung mục tiêu ⇒ cha + sub-issue, khác mục tiêu ⇒ N ticket, không dấu hiệu ⇒ 1. Priority/Size/Platform theo checklist, assignee = login `get_me`, milestone mở gần hạn nhất.
- Bảng chấm §4 vẫn chạy, ✗ thì tự sửa. Ghi luôn (§5); `[AF:SPEC] created` thêm `auto · <k> giả định`.
- Cổng Ready (§6) vẫn hỏi PO — agent không đưa ticket ra khỏi Backlog khi người chưa xác nhận: câu hỏi liệt kê các Giả định. PO muốn đổi giả định → hỏi điểm đó như ask, cập nhật body (§5 mode `#n`), xét lại §6.

## SA

`CLARIFY: ask` (từ `/run`, người trả lời trên GitHub) · `ask-live` (từ `/do`, orchestrator hỏi trong terminal). Cả hai gắn `needs_info` khi chờ người (`/do` đứt giữa chừng thì `/run` không tự cho DEV làm); chỉ `ask` báo: mention `people.po` + `agentflow-notify needs_info …`. Đọc thêm `[AF:SA] options` mới nhất và lời đáp sau nó: comment của người, `[AF:SYS] decision` (người chọn trong terminal). DoR chặn thì vẫn `[AF:SA] ?` như sa.md. Phần còn lại thay cho Viết/Ghi của sa.md §1:

1. **Chưa có options cho thiết kế này** (không có, hoặc cũ hơn `[AF:SPEC] refined`) và có điểm cần chọn → comment, rồi state `plan: options`; **không** gắn `labels.agent`:
   ```
   [AF:SA] options @<sha của origin/<base>>
   1. <câu hỏi> — <vì sao phải chọn>
      A. <phương án> (đề xuất) — được · mất · công sức · rủi ro
      B. …
   Sẽ thực hiện nếu theo đề xuất: <≤ 10 dòng>
   Trả lời `1A 2B` + ghi chú (`OK` = theo mọi đề xuất và xác nhận kế hoạch trên), rồi bỏ label `<labels.needs_info>`.
   ```
   Gắn `needs_info`, báo (`ask`). `RESULT: ready · decide`.
2. **Có options, chưa có lời đáp** → không phân tích lại; thiếu `needs_info` thì gắn + báo như bước 1. `RESULT: ready · decide`.
3. **Có lời đáp, hoặc không có điểm cần chọn** → `[AF:SA] design` như sa.md §1 theo lựa chọn (dòng "Theo lựa chọn: 1A 2B"), thêm mục đầu **0. Sẽ thực hiện** (≤ 12 dòng: giải pháp; thay đổi theo module/màn + path chính; dữ liệu/migration; contract đổi; số TC + flow regression; QC tay dự kiến; Ngoài phạm vi; rủi ro cao). Ghi như sa.md §1 (gắn `labels.agent`) cộng:
   - Lời đáp là `OK` và thiết kế không lệch kế hoạch đã trình ⇒ `plan: ok`, `RESULT: ready · ok`.
   - Không ⇒ `plan: confirm`; cuối design thêm "Xác nhận: bỏ label `<labels.needs_info>`. Muốn sửa: comment trước khi bỏ label."; gắn `needs_info`, báo (`ask`). `RESULT: ready · decide`.
4. **Người đòi sửa sau design** (`plan: confirm`) → `[AF:SA] design` mới theo yêu cầu, lại bước 3.

Lời đáp làm đổi AC hay phạm vi → không tự đổi ticket: `[AF:SA] ?` đề nghị `/agentflow:task #<n>`, gắn `needs_info`, `RESULT: ready · needs_info`.

## Điều phối

Chế độ `implement` xác định một lần lúc boot. Spawn SA design với `CLARIFY: auto` · `ask` (`/run`) · `ask-live` (`/do`). `[AF:SYS] decision` là lời người dùng nhập trong terminal, agent đọc như comment của người.

**`/run`** — không hỏi người. RESULT `decide` = chờ người trên GitHub: dừng ticket, báo cáo "chờ chọn phương án" (`plan: options`) hoặc "chờ xác nhận kế hoạch" (`plan: confirm`). Dòng `plan: confirm` của dispatch §3: đọc comment sau `[AF:SA] design` mới nhất — người đòi sửa ⇒ SA `MODE=design`; chỉ đồng ý hoặc không có ⇒ SYS *confirmed*.

**`/do`** — RESULT `decide`, hoặc ticket mang `needs_info` có state `plan: options|confirm`:
1. `plan: options` → đọc `[AF:SA] options` mới nhất; AskUserQuestion mỗi điểm một câu (≤ 4 mỗi lượt, đủ lượt cho mọi điểm), option = phương án, đề xuất đầu "(Recommended)", preview = được/mất. Comment `[AF:SYS] decision` (`1A 2B` + nguyên văn ghi chú). `SendMessage` (ToolSearch) cho chính SA vừa chạy: "Người dùng chọn <…> (`[AF:SYS] decision`). Làm `clarify.md` §SA bước 3, kết thúc bằng RESULT."; agent không còn ⇒ spawn SA `MODE=design`, `CLARIFY: ask-live`.
2. `plan: confirm` → in mục **0. Sẽ thực hiện** của `[AF:SA] design` mới nhất + link, AskUserQuestion:
   - "Xác nhận — DEV bắt đầu (Recommended)" ⇒ SYS *confirmed* (gỡ cả `needs_info`), spawn DEV `MODE=new`.
   - "Sửa" ⇒ hỏi sửa gì, `[AF:SYS] decision` ghi nguyên văn, `SendMessage` SA làm §SA bước 4, lại bước 2.
   - "Dừng ở đây" ⇒ giữ (thiếu thì gắn) `needs_info`, `[AF:SYS] decision` "dừng trước khi code: bỏ label `<labels.needs_info>` = xác nhận, comment = yêu cầu sửa". Báo cáo, dừng.
3. Mỗi `SendMessage` tính một spawn (trần dispatch §6).
