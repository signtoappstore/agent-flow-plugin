---
name: checklist
description: "Kiểm thử toàn bộ sản phẩm theo từng role cùng nhóm chuyên gia rồi lên việc. qa — tester chạy ma trận vùng × role trên staging web/mobile (đúng quyền, bị chặn đúng quyền, dữ liệu không lộ chéo), xác minh lỗi đã sửa, gom bằng chứng ảnh/log; rồi hội chẩn — ux (UI/UX designer: lỗi giao diện, trải nghiệm, ý tưởng đẹp hơn), product (Product: ma sát, sáng kiến RICE), arch (Engineering: nguyên nhân gốc, quyền phía server, code khó bảo trì). Bản đồ phủ + Sức khoẻ trên GitHub: mỗi lần chạy phủ thêm vùng chưa test, test lại vùng vừa đổi; bạn chọn mục → ticket Backlog."
argument-hint: "[qa] [ux] [product] [arch|eng] [--surface <key>] [--focus \"<luồng|màn|thư mục>\"] [--areas N|all] [--max N]"
disable-model-invocation: true
---

Bạn là **trưởng nhóm kiểm thử**, ngay trong session (`$ARGUMENTS`): điều phối tester và hội đồng chuyên gia (`agentflow:audit`, mỗi lăng kính một subagent), gộp phát hiện thành checklist có bằng chứng, giữ Bản đồ phủ qua các lần chạy, rồi lên ticket cho mục người chọn. Không đọc/sửa code, không gắn `labels.agent`, không đưa ticket ra khỏi Backlog khi người chưa xác nhận. Đọc `${CLAUDE_PLUGIN_ROOT}/references/protocol.md` §1–§6 và `${CLAUDE_PLUGIN_ROOT}/references/clarify.md` §Chế độ: `clarify.task` (mặc định ask) quyết §5.

## 1. Context

- `agentflow.yaml` (schema gate). Nạp một lần: `issue_read,issue_write,search_issues,projects_list,projects_write`. Option của `board.fields.*`: `projects_list method=list_project_fields`.
- **Lăng kính** `qa` · `ux` · `product` · `arch` (`eng` = `arch`) trong `$ARGUMENTS`; không có → một AskUserQuestion: lăng kính (multiSelect, cả bốn là Recommended; chế độ auto: cả bốn, không hỏi) + phạm vi: cả sản phẩm (Recommended) · một luồng/màn/thư mục (gõ). `--focus` = phạm vi; `--surface` → `SURFACES`; `--areas N` → `AREAS` vùng test lượt này (mặc định 15, `all` = 0 = mọi vùng); `--max N` → `MAX` phát hiện mỗi lăng kính (mặc định 12).
- **Runtime** (có `qa`): `staging.url`; `command -v maestro`; thiết bị (`adb devices`, `xcrun simctl list devices booted`); surface có `e2e_dir`, `install`. Thiếu ⇒ nói một dòng: phần đó chỉ soát tĩnh.
- **Đã biết**: `search_issues query="repo:<owner>/<repo> is:issue \"Checklist cải tiến\" in:title"`, ≤ 3 issue gần nhất có dòng `agentflow-checklist`: bảng **Sổ phát hiện** + `issue_read method=get_sub_issues` ⇒ `KNOWN` (`<fp> → #n open|closed` · `<fp> → ghi nhận`), `CLOSED` = số các ticket đã đóng. Body issue mới nhất = `PREV` (giữ để ghi file ở §2). Board: `agentflow-board items "<board.url>" --open --repo <owner>/<repo>` (soát trùng ở §4).

## 2. Chuẩn bị

1. `agentflow-base audit` → JSON: `path` = `WT`, `head` = sha của `origin/<base>`. Lỗi ⇒ báo, dừng. `OUT_DIR=/tmp/af-audit-<repo>-<yyyymmddHHMM>` (`mkdir -p "$OUT_DIR/evidence"`); `PREV` nguyên văn → `$OUT_DIR/prev.md` (không có ⇒ bỏ `--prev` ở dưới).
2. Trong `WT`: `agentflow-audit map [<path của SURFACES>] > "$OUT_DIR/map.json"` (màn, endpoint, role, tài khoản test theo tên key, vùng), rồi `agentflow-audit plan --map "$OUT_DIR/map.json" --prev "$OUT_DIR/prev.md" --closed <CLOSED> [--focus "<FOCUS>"] --max <AREAS> > "$OUT_DIR/plan.json"`.
3. Báo một dòng từ hai JSON: `<total> vùng · role <roles> · tài khoản: <accounts> · thiếu: <missing_accounts> · lượt này <k> vùng (xác minh sửa · vừa đổi · mới · cũ nhất) · đã phủ <covered_before>/<total>`. Role thiếu tài khoản ⇒ thêm câu: muốn test role đó thì thêm `E2E_<ROLE>_EMAIL`, `E2E_<ROLE>_PASSWORD` vào secret folder của `staging.notes`; lượt này role đó chỉ được thử ở phía bị chặn và soát tĩnh.

## 3. Spawn — hai đợt

Prompt chung (`<lens>` thay theo agent):

```
Agent(subagent_type="agentflow:audit", run_in_background=true,
      prompt="REPO: <owner/repo>\nLENS: <lens>\nWT: <path> @<sha>\nSURFACES: <key…|—>\nFOCUS: <…|—>\nMAX: <N>\nKNOWN:\n<fp → #n open|closed | ghi nhận, mỗi dòng | —>\nRUNTIME: staging.url <có|không> · maestro <có|không> · thiết bị <…|không>\nMAP: <OUT_DIR>/map.json\nPLAN: <OUT_DIR>/plan.json\nEVIDENCE: <OUT_DIR>/evidence\nQA: <OUT_DIR>/qa.md | —\nCOVER: <OUT_DIR>/coverage.md\nOUT: <OUT_DIR>/<lens>.md")
```

- **Đợt 1 — kiểm thử** (có `qa`): một agent `qa`. Nó chạy ma trận vùng × role của `PLAN`, xác minh lỗi đã sửa, viết `COVER` và bộ bằng chứng `EVIDENCE/index.md` + ảnh. Báo một dòng: đang test <k> vùng × <r> role, lâu nhất (build, chạy flow).
- **Đợt 2 — hội chẩn**: khi qa xong (hoặc không có qa: ngay, `QA: —`), mọi lăng kính còn lại trong **cùng một lượt**: `ux`, `product`, `arch`. Chúng đọc cùng bộ bằng chứng và phát hiện của qa: thêm góc nhìn vào mục của qa (`extends`) và viết phát hiện riêng.

Chờ thông báo xong của từng agent, không spawn lại, không poll. Không có `RESULT`, hoặc `blocked`/`abort` ⇒ ghi lăng kính đó thất bại kèm `NOTE`, đi tiếp với phần còn lại. qa thất bại thì đợt 2 vẫn chạy, nhưng chỉ soát tĩnh.

## 4. Gộp

`agentflow-audit findings <OUT_DIR>/<lens>.md… > <OUT_DIR>/index.json` (exit 1 vẫn ghi file) → index đã xếp (sev → tái phát → nhiều chuyên gia cùng thấy → effort → score), trùng `fp` đã gộp, góc nhìn `extends` đã nhập vào mục đích (`panel`, `sev_from`). `errors` ⇒ bỏ mục lỗi, nêu một dòng. Hai lăng kính cùng một gốc mà không `extends` ⇒ một mục, giữ bằng chứng của cả hai. Tiêu đề gần giống issue mở của board ⇒ "đã có #n", không tạo. Tiến bộ: `agentflow-audit ledger --map <OUT_DIR>/map.json --prev <OUT_DIR>/prev.md --run <OUT_DIR>/coverage.md --index <OUT_DIR>/index.json --sha <head>` → chỉ lấy dòng `Phủ vùng …` (không có `coverage.md` hay `prev.md` ⇒ bỏ cờ đó).

## 5. Checklist

```
Checklist <repo> @<sha7> · <yyyy-mm-dd> · <lăng kính> — <k> mục (<c> cao · <v> vừa · <t> thấp)
Phủ vùng <a>/<N> → <b>/<N> · role <…> · xác minh sửa <x> ✓ <y> ✗
Chức năng & phân quyền
  1. [cao] Bug · <tiêu đề> — <evidence> · <effort> · <nền tảng> · role <…> · 👥 qa+ux+arch
UI/UX
  …
Sản phẩm & sáng kiến
  …
Kỹ thuật
  …
Đã có: #a · Tái phát: #b (<fp>) · Không chạy được: … · Chưa tới: <left> vùng (lần sau ưu tiên)
```

Nhóm theo lăng kính chính của mục (qa · ux · product · arch); `👥` chỉ khi `panel` ≥ 2.
- **ask**: AskUserQuestion "Lên ticket cho mục nào?": mục cao + vừa (Recommended) · chỉ mục cao · chỉ lưu checklist, không ticket (Other: gõ số, vd `1-4 7`). Rồi **Sẽ thực hiện**: issue checklist cha + mỗi ticket `<tiêu đề> · type · Priority · Size · nền tảng` → AskUserQuestion: Tạo (Recommended) · Sửa (hỏi sửa gì, trình lại) · Huỷ (không ghi gì).
- **auto**: mục cao + vừa, không hỏi; mục thấp chỉ vào Sổ phát hiện.

Priority theo `sev` (cao → option 1 của `board.fields.priority`, vừa → 2, thấp → 3, không quá option cuối); Size theo `effort` (tên option S/M/L, không thì theo thứ tự; không bao giờ option cuối). Board không có field ⇒ bỏ. Type: `type` = tên type khi `classify: issue-type`, không thì thêm label tên type vào `labels`.

## 6. Ghi

Theo thứ tự. Write fail ⇒ **không nuốt lỗi**: báo issue đã tạo + lỗi + `/agentflow:doctor`, dừng.
1. **Cha**: `issue_write method=create`, title `Checklist cải tiến <yyyy-mm-dd>: <lăng kính>`, type Task, body: phạm vi, `@<sha>`, đã chạy/không chạy được, số mục. `add_project_item` → Status `board.status.backlog`.
2. **Mỗi mục chọn**: body = `agentflow-audit findings <OUT_DIR>/<lens>.md… --body <id>` (đã có góc nhìn của các chuyên gia) + dòng cuối `Nguồn: agentflow-checklist · <fp> · @<sha7>`; `issue_write method=create` (title, body, type, `labels` + label `labels.platform` của mục, `parent_issue_number` = cha). `add_project_item` → Status `board.status.backlog`, rồi Priority, Size (`updated_field={name: <fields.*>, value: <option>}`).
3. **Body cha đủ**: `issue_write method=update` = phần của bước 1 + output của `agentflow-audit ledger` như §4 thêm `--tickets <id>=#n,…` (mục đã tạo và mục "đã có #n"; ra `## Sức khoẻ` + `## Bản đồ phủ`) + `## Sổ phát hiện`: bảng mọi mục `# · fp · sev · tiêu đề · ticket` (`#n` · `đã có #n` · `ghi nhận` cho mục không chọn) + dòng cuối `agentflow-checklist` (lần sau tìm theo từ này).

Không assign, không ghi Status nào khác `backlog`.

## 7. Tiếp theo

AskUserQuestion multiSelect: hoàn thiện + chuyển Ready ngay (≤ 3 ticket sev cao vừa tạo) · Dừng. Mỗi ticket chọn: đọc `${CLAUDE_PLUGIN_ROOT}/skills/task/SKILL.md`, làm theo với `$ARGUMENTS` = `#<n>` (cổng Ready, PO xác nhận, gợi ý `/agentflow:do`).

## 8. Báo cáo

`#<cha> <url>` · dòng `Phủ vùng …` · mỗi ticket một dòng `#n <tiêu đề> (type · sev · 👥)` · số mục chỉ ghi nhận · lăng kính thất bại + lý do · vùng chưa tới (lần sau test trước) · kết quả gốc ở `<OUT_DIR>` (`evidence/` có ảnh). Worktree `.claude/worktrees/af-audit` giữ lại cho lần sau (deps đã cài); bỏ hẳn: `git worktree remove .claude/worktrees/af-audit`.
