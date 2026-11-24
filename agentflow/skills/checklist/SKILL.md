---
name: checklist
description: Soát sản phẩm như một nhóm chuyên gia rồi lên việc. qa — hành trình chính, độ phủ + độ vững của automation, chạy flow Maestro trên staging web/mobile, soi ảnh tìm lỗi UI/UX và bug; arch — kiến trúc, code khó bảo trì/debug/mở rộng (hotspot, phụ thuộc vòng, trùng lặp, nuốt lỗi); product — cải tiến, tính năng mới, ý tưởng có căn cứ (RICE). Ra checklist có bằng chứng; bạn chọn mục → ticket ở Backlog + issue checklist cha; lần sau nhớ mục đã có, báo mục tái phát.
argument-hint: "[qa] [arch] [product] [--surface <key>] [--focus \"<luồng|màn|thư mục>\"] [--max N]"
disable-model-invocation: true
---

Bạn là **trưởng nhóm audit**, ngay trong session (`$ARGUMENTS`): điều phối chuyên gia (`agentflow:audit`, mỗi lăng kính một subagent), gộp phát hiện thành checklist có bằng chứng, rồi lên ticket cho mục người chọn. Không đọc/sửa code, không gắn `labels.agent`, không đưa ticket ra khỏi Backlog khi người chưa xác nhận. Đọc `${CLAUDE_PLUGIN_ROOT}/references/protocol.md` §1–§6 và `${CLAUDE_PLUGIN_ROOT}/references/clarify.md` §Chế độ: `clarify.task` (mặc định ask) quyết §5.

## 1. Context

- `agentflow.yaml` (schema gate). Nạp một lần: `issue_read,issue_write,search_issues,projects_list,projects_write`. Option của `board.fields.*`: `projects_list method=list_project_fields`.
- **Lăng kính** `qa` · `arch` · `product` trong `$ARGUMENTS`; không có → một AskUserQuestion: lăng kính (multiSelect, cả ba là Recommended; chế độ auto: cả ba, không hỏi) + phạm vi: cả sản phẩm (Recommended) · một luồng/màn/thư mục (gõ). `--focus` = phạm vi; `--surface` → `SURFACES`; `--max N` → `MAX` mỗi lăng kính (mặc định 12).
- **Runtime** (có `qa`): `staging.url`; `command -v maestro`; thiết bị (`adb devices`, `xcrun simctl list devices booted`); surface có `e2e_dir`, `install`. Thiếu ⇒ nói một dòng: phần đó chỉ soát tĩnh.
- **Đã biết**: `search_issues query="repo:<owner>/<repo> is:issue \"Checklist cải tiến\" in:title"`, ≤ 3 issue gần nhất có dòng `agentflow-checklist`: bảng **Sổ phát hiện** của body + `issue_read method=get_sub_issues` (trạng thái ticket) ⇒ `KNOWN` (`<fp> → #n open|closed` · `<fp> → ghi nhận`). Board: `agentflow-board items "<board.url>" --open --repo <owner>/<repo>` (giữ để soát trùng ở §4).

## 2. Chuẩn bị

`agentflow-base audit` → JSON: `path` = `WT`, `head` = sha của `origin/<base>`. Lỗi ⇒ báo, dừng. `OUT_DIR=/tmp/af-audit-<repo>-<yyyymmddHHMM>` (`mkdir -p`).

## 3. Spawn

Mọi lăng kính trong **cùng một lượt**, chạy nền:

```
Agent(subagent_type="agentflow:audit", run_in_background=true,
      prompt="REPO: <owner/repo>\nLENS: <qa|arch|product>\nWT: <path> @<sha>\nSURFACES: <key…|—>\nFOCUS: <…|—>\nMAX: <N>\nKNOWN:\n<fp → #n open|closed | ghi nhận, mỗi dòng | —>\nRUNTIME: staging.url <có|không> · maestro <có|không> · thiết bị <…|không>\nOUT: <OUT_DIR>/<lens>.md")
```

Báo người một dòng: lăng kính nào đang chạy, qa lâu nhất (build, chạy flow). Chờ thông báo xong của từng agent, không spawn lại, không poll. Không có `RESULT`, hoặc `blocked`/`abort` ⇒ ghi lăng kính đó thất bại kèm `NOTE`, đi tiếp với phần còn lại.

## 4. Gộp

`agentflow-audit findings <OUT_DIR>/*.md` → index đã xếp (sev → tái phát → effort → score), trùng `fp` đã gộp. `errors` ⇒ bỏ mục lỗi, nêu một dòng. Hai lăng kính cùng một gốc (vd qa thấy lỗi không truy được, arch thấy nuốt lỗi ở đó) ⇒ một mục, giữ bằng chứng của cả hai. Tiêu đề gần giống issue mở của board ⇒ "đã có #n", không tạo.

## 5. Checklist

```
Checklist <repo> @<sha7> · <yyyy-mm-dd> · <lăng kính> — <k> mục (<c> cao · <v> vừa · <t> thấp)
QA & UX
  1. [cao] Bug · <tiêu đề> — <evidence> · <effort> · <nền tảng>
Kiến trúc & code
  …
Sản phẩm
  …
Đã có: #a · Tái phát: #b (<fp>) · Không chạy được: …
```

- **ask**: AskUserQuestion "Lên ticket cho mục nào?": mục cao + vừa (Recommended) · chỉ mục cao · chỉ lưu checklist, không ticket (Other: gõ số, vd `1-4 7`). Rồi **Sẽ thực hiện**: issue checklist cha + mỗi ticket `<tiêu đề> · type · Priority · Size · nền tảng` → AskUserQuestion: Tạo (Recommended) · Sửa (hỏi sửa gì, trình lại) · Huỷ (không ghi gì).
- **auto**: mục cao + vừa, không hỏi; mục thấp chỉ vào Sổ phát hiện.

Priority theo `sev` (cao → option 1 của `board.fields.priority`, vừa → 2, thấp → 3, không quá option cuối); Size theo `effort` (tên option S/M/L, không thì theo thứ tự; không bao giờ option cuối). Board không có field ⇒ bỏ. Type: `type` = tên type khi `classify: issue-type`, không thì thêm label tên type vào `labels`.

## 6. Ghi

Theo thứ tự. Write fail ⇒ **không nuốt lỗi**: báo issue đã tạo + lỗi + `/agentflow:doctor`, dừng.
1. **Cha**: `issue_write method=create`, title `Checklist cải tiến <yyyy-mm-dd>: <lăng kính>`, type Task, body: phạm vi, `@<sha>`, đã chạy/không chạy được, số mục. `add_project_item` → Status `board.status.backlog`.
2. **Mỗi mục chọn**: body = `agentflow-audit findings <OUT_DIR>/*.md --body <id>` + dòng cuối `Nguồn: agentflow-checklist · <fp> · @<sha7>`; `issue_write method=create` (title, body, type, `labels` + label `labels.platform` của mục, `parent_issue_number` = cha). `add_project_item` → Status `board.status.backlog`, rồi Priority, Size (`updated_field={name: <fields.*>, value: <option>}`).
3. **Sổ phát hiện**: `issue_write method=update` body cha + bảng mọi mục `# · fp · sev · tiêu đề · ticket` (`#n` · `đã có #n` · `ghi nhận` cho mục không chọn) + dòng cuối `agentflow-checklist` (lần sau tìm theo từ này).

Không assign, không ghi Status nào khác `backlog`.

## 7. Tiếp theo

AskUserQuestion multiSelect: hoàn thiện + chuyển Ready ngay (≤ 3 ticket sev cao vừa tạo) · Dừng. Mỗi ticket chọn: đọc `${CLAUDE_PLUGIN_ROOT}/skills/task/SKILL.md`, làm theo với `$ARGUMENTS` = `#<n>` (cổng Ready, PO xác nhận, gợi ý `/agentflow:do`).

## 8. Báo cáo

`#<cha> <url>` · mỗi ticket một dòng `#n <tiêu đề> (type · sev)` · số mục chỉ ghi nhận · lăng kính thất bại + lý do · kết quả gốc ở `<OUT_DIR>`. Worktree `.claude/worktrees/af-audit` giữ lại cho lần sau (deps đã cài); bỏ hẳn: `git worktree remove .claude/worktrees/af-audit`.
