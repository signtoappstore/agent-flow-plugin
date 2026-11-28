---
name: distribute
description: Phát hành version mới của AgentFlow từ source trên máy này (bump → verify → commit → tag → push) rồi cài lên mọi project đang dùng plugin; project nào không chạy được bản mới (schema, config, key cũ) thì sửa agentflow.yaml cho tương thích. Chạy từ bất kỳ project nào đã bật agentflow.
argument-hint: "[patch|minor|major] [--no-publish] [--project <dir>]…"
disable-model-invocation: true
---

Một lượt: **plan → version → verify → commit → xác nhận một lần → publish → install → compat → báo cáo**. Phần máy móc đi qua `agentflow-distribute` (tự tìm source, chạy được từ mọi thư mục; `--help`). Không `--force` tag, không push project, không ghi GitHub của project.

`$ARGUMENTS`: mức bump · `--no-publish` (bỏ commit/tag/push, chỉ cài + compat) · `--project <dir>` (chỉ những project đó, lặp được, truyền tiếp cho `install`/`compat`).

## 1. Plan

`agentflow-distribute plan` (exit 2 = máy không giữ source → dừng, in đúng lỗi). `SRC` = `release.root` của `plan --json`; mọi lệnh git bên dưới là `git -C "$SRC"`.

| `release.state` | Làm |
|---|---|
| `unreleased` | giữ version, trừ khi có mức bump |
| `needs_bump` | bắt buộc bump (version đã tag ở cây khác) |
| `released` | bỏ §2–§3; `unpushed > 0` thì vẫn publish |

`marketplace_source` ≠ `directory` → project cài từ GitHub, chỉ nhận code mới sau khi push: `--no-publish` vô nghĩa, push lỗi thì dừng.

## 2. Version + verify

- Mức: `$ARGUMENTS` > tối thiểu `release.min_bump` (schema đổi ⇒ minor) > tự chọn: thêm năng lực hay project phải sửa config ⇒ minor, sửa lỗi ⇒ patch; major chỉ khi người nói.
- `agentflow-distribute bump <mức>` rồi `agentflow-distribute verify` (~3 phút). Fail → dừng, in bước fail, không sửa test cho xanh.

## 3. Commit (khi `release.dirty` khác rỗng)

`git status --porcelain` + `git diff --stat`; file không thuộc lượt (bí mật, file IDE, file tạm) → liệt kê, không add. Message theo `git log -5 --format=%s`: `<feat|fix|refactor>(agentflow): <tóm tắt tiếng Việt về hành vi đổi> (<version>)`.

## 4. Xác nhận một lần

AskUserQuestion **một** câu kèm: version cũ → mới, message, sẽ push `release.base` + tag `release.tag` lên origin (repo public), project sẽ cập nhật cùng compat hiện tại (✗ = sẽ sửa ở §6). Không đồng ý → dừng.

## 5. Publish + install

`git add <file của lượt> && git commit -m …` → `agentflow-distribute publish` → `agentflow-distribute install`.

- `publish` exit 3 (push lỗi/timeout): tag giữ local; marketplace directory → vẫn install, cuối lượt nhắc chạy lại `agentflow-distribute publish`. Exit khác → dừng.
- `install`: dòng `ok: false` → in `error`, project khác vẫn tiếp.

## 6. Compat

`agentflow-distribute compat --json` — phán bằng chính code của bản mới.

- `not_initialized` → nhắc `/agentflow:init` trong project đó. `missing` → nhắc `claude plugin uninstall <id> --scope local` trong thư mục đó.
- `incompatible` → migrate **chỉ `agentflow.yaml`** của project (`config_dirty` → hiện diff, hỏi trước):
  1. Nguồn đổi: `git diff <sha>..HEAD -- agentflow/agentflow.yaml` (`sha` của install, xem `contract_commits`); schema của project cũ hơn mốc đó → mốc `git log --format=%h -G'^schema: <N>' -- agentflow/agentflow.yaml | head -1`. Chưa rõ ngữ nghĩa → `agentflow/references/protocol.md` §1, `agentflow/DESIGN-NOTES.md`.
  2. Sửa tối thiểu, giữ value + comment: đổi tên/dời key theo diff, thêm key bắt buộc (suy từ config cũ, git và `.github/workflows/` của project, hoặc mặc định template), xoá key bị bỏ, đặt `schema`.
  3. Không suy chắc (cột board, nhánh staging, label, issue type) → AskUserQuestion, gom một lượt mỗi project, không bịa. Trống gần hết hay khác cấu trúc hẳn → không vá, nhắc `/agentflow:init` ở project đó.
  4. `agentflow-distribute compat --project <p>` hết ✗; còn → lặp 2–3 tối đa 2 lần rồi báo.
- `warn`: key "xoá được"/"không còn dùng" → sửa đúng theo message, cùng lượt. `missing_allow` → chỉ báo lệnh `agentflow-settings allow --user <rule…>`, không tự cấp quyền. Việc phía GitHub (label, cột, field) → nhắc `/agentflow:doctor` trong project.

Project đã sửa → hiện `git -C <p> diff --stat agentflow.yaml`, hỏi **một** câu có commit không: chỉ project đang ở nhánh gốc, message `chore(agentflow): tương thích agentflow v<version>`; nhánh khác để nguyên. Không push.

## 7. Báo cáo

Bảng `project | v cũ → mới | compat trước → sau | đã sửa`, tag + push, việc còn lại cho người (init, doctor, quyền, push lại). Nhắc restart Claude Code hoặc `/reload-plugins` trong từng project — kể cả session đang chạy lệnh này.
