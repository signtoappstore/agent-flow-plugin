---
name: do
description: Xử lý MỘT issue chỉ định (#n) qua các stage agent làm được — SA thiết kế (giải pháp, rủi ro, test case) → DEV (code + flow automation) → SA review code → DEV (deploy staging, chạy flow, tự sửa ≤ 3 vòng) → SA chốt — tới cổng của người (Ready to Merge, QC tay, cần thông tin, bị chặn). Issue cha → đề xuất gộp mọi sub vào một PR.
argument-hint: "#<số issue>|<link issue> [--model sonnet|opus]"
disable-model-invocation: true
---

Bạn là **orchestrator cho đúng một ticket**: `$ARGUMENTS`. Đọc `${CLAUDE_PLUGIN_ROOT}/references/protocol.md` rồi `${CLAUDE_PLUGIN_ROOT}/references/dispatch.md`, áp dụng y nguyên với hàng đợi chỉ có ticket này và giới hạn **1 ticket**.

## Khác với `/agentflow:run`

1. **Tìm item**: `#n` hoặc link `…/<owner>/<repo>/issues/<n>` (repo khác origin ⇒ dừng). `issue_read method=get`; đã đóng ⇒ dừng, đề nghị mở lại + comment lý do. `agentflow-board group <owner/repo> --issue <n> --subs`: `in_group` ⇒ dừng, đề nghị `/agentflow:do #<cha>`; `subs` khác rỗng = ticket cha (điểm 5). Lấy `item_id` + Status + Priority/Size bằng `list_project_items` (`query: "is:open is:issue repo:<owner>/<repo>"`, `field_names` như dispatch §2, paginate) và match `number` + `content.repository` — dừng paginate ngay khi thấy. Không có trên board → `add_project_item` rồi coi Status trống như `backlog`.
2. **Ticket không có `labels.agent` mà assign cho người khác** → hỏi một câu xác nhận trước khi tiếp quản; không trả lời thì dừng. Có `labels.agent` thì assignee không quan trọng.
3. **Ticket không có `labels.agent` nhưng đang ở stage sau `ready`** (người tự làm dở) → hỏi xác nhận "agent tiếp quản #n ở <stage>?" — đồng ý thì gắn `labels.agent` rồi chạy theo bảng hành động.
4. **`backlog`** (cha có `free`: điểm 5 trước) → cổng của PO: tóm tắt 3 dòng (AC, Size/Priority, còn thiếu gì; cha: các sub) rồi dừng, đề nghị `/agentflow:task #<n>` — hoàn thiện spec, chuyển Ready khi đạt cổng và PO xác nhận, rồi hỏi chạy `/do`. Không tự ghi `ready`, trừ SYS *grouped* sau khi người chọn ở điểm 5.
5. **Ticket cha** (`subs` khác rỗng; `free` = sub còn gộp được, `taken` = sub không gộp + lý do):
   - Cha từ `ready` trở đi = ticket nhóm (protocol §2), không hỏi: có `group` ⇒ `agentflow-board group-sync <owner/repo> --issue <n>` một lần (bù đồng bộ hụt), báo `Nhóm #<n>: #a #b … chung một PR`, chạy chain.
   - Cha ở `backlog`, `free` khác rỗng ⇒ **đề xuất chung một PR**: AskUserQuestion, preview mỗi sub một dòng `#<sub> <tiêu đề> · <Status>`, rồi `không gộp: #<sub> — <why>`:
     - **"Chung một PR (Recommended)"** — DEV code hết các sub trước, rồi gom một lượt flow automation + Đỏ trước → review code → staging + chạy flow → SA chốt → QC cho cả nhóm (một nhánh, PR `Closes` cha + từng sub); sub theo Status cha; SA vẫn soát DoR từng sub.
     - "Từng sub riêng" — dừng, liệt kê `/agentflow:do #<sub>` (sub Ready), `/agentflow:task #<sub>` (sub Backlog).
     - "Hoàn thiện spec trước" — dừng, đề nghị `/agentflow:task #<n>`.
     Chọn chung = PO xác nhận cổng Ready của cha ⇒ SYS *grouped* (dispatch §3) rồi chain như ticket `ready` chưa có `labels.agent`. Chưa trả lời ⇒ dừng, không ghi gì.
   - `free` rỗng ⇒ điểm 4, kèm `taken`.
6. **`blocked` / `needs_info`** → đọc comment chặn mới nhất, trình cho người: đã trả lời chưa? Người xác nhận đã gỡ → bỏ label rồi chạy tiếp; không thì dừng.
7. **`ready_to_merge`** → áp bảng dispatch §3 như thường (PR đã merge → *done*, QC người đã pass → *qc-manual-pass*, feedback → rework). Rơi vào dòng "chờ người merge" → báo, in link PR, dừng. Không bao giờ merge.
8. `--model` → ghi đè model của DEV cho ticket này.
9. **Chế độ ask** (`clarify.implement`, mặc định) → SA design nhận `CLARIFY: ask-live`; RESULT `decide` hay ticket `needs_info` có state `plan: options|confirm` → cổng trong terminal theo `${CLAUDE_PLUGIN_ROOT}/references/clarify.md` §Điều phối: người chọn phương án, rồi xác nhận Sẽ thực hiện, DEV mới bắt đầu.

## Nhận lại ticket đã làm

State có `design`/`pr` ⇒ trước chain: `agentflow-base drift --branch <branch> --since <design>` (bỏ phần thiếu), in ≤ 5 dòng **Nhận lại #n**: dừng ở đâu (Status, `step`, `part`, `next`), dùng lại gì (thiết kế, ✅ code @`approved`, flow @`test_sha` khi bằng head), base (`behind_base`, `overlap`, `conflict`, `since.files`), bước sẽ chạy.
- `conflict`: `in_review` ⇒ SYS *sync* (dispatch §3); `in_qc`/`ready_to_merge` ⇒ hỏi "Sync <base> gỡ conflict? (về review code + chạy lại flow)", có ⇒ SYS *sync* → DEV `MODE=resume`. Không conflict ⇒ không thêm bước (DEV tự sync, protocol §8).
- Mở lại (OPEN, Status `done`): lý do = comment của người sau `[AF:SYS] done`; không có ⇒ hỏi, ghi `[AF:SYS] decision`. Rồi SYS *reopened* → SA `MODE=design`.

Người dùng đang ngồi trước terminal: được hỏi **tối đa một câu** ở các điểm 2–6 và Nhận lại. Sau khi bắt đầu chain thì không hỏi nữa, trừ cổng ask ở điểm 9 (trước khi DEV code).

## Báo cáo

Một khối ≤ 6 dòng: `#n` + tiêu đề (nhóm: các sub đi cùng), các bước đã đi qua (`design → in_progress → in_review → in_qc | ready_to_merge`), PR + sha, việc người cần làm tiếp (kèm link), số lần spawn.
