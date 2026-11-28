# Phát triển AgentFlow

Trên máy dev, marketplace `agent-flow-plugins` là **directory source** trỏ vào bản clone: Claude Code đọc thẳng working tree, nhưng lúc `install`/`update` nó **copy snapshot** vào `~/.claude/plugins/cache/agent-flow-plugins/agentflow/<version>/` — khoá theo `version`. Sửa source không tự lan sang bản đang chạy.

## Vòng phát hành: `/agentflow:distribute`

Gọi `/agentflow:distribute [patch|minor|major]` từ bất kỳ project nào đã bật agentflow. Lệnh chỉ chạy được trên máy có marketplace dạng directory trỏ vào bản clone này. Script `bin/agentflow-distribute` tự tìm source; nếu đang chạy bản nằm trong cache thì nó chuyển sang chạy bản của source. Một lượt gồm:

1. `plan`: trạng thái release (version đã có tag chưa, schema đổi so với tag cuối ⇒ bump ≥ minor) và mọi project đang cài trong `~/.claude/plugins/installed_plugins.json`, mỗi project kèm compat offline.
2. `bump`, `verify` (validate + unit test), commit, rồi hỏi xác nhận **một lần** trước `publish` (`claude plugin tag` + `git push --atomic` nhánh `master` và tag).
3. `install`: `marketplace update`, rồi `plugin update --scope <scope>` chạy trong từng project, kiểm lại version. Version đã cài từ một cây khác thì bị từ chối: cache khoá theo version, phải bump trước.
4. `compat`: dùng chính `SCHEMA`, `validate_config` và `AGENT_ALLOW` của bản mới để phán. Project ✗ thì agent migrate `agentflow.yaml` của project (diff template từ commit đã cài tới HEAD; value không suy chắc được thì hỏi người) cho tới khi hết ✗, rồi hỏi có commit vào project không. Không push project, không đụng GitHub của project.

Push lỗi (mạng máy này hay chặn) thì tag vẫn giữ local, vẫn cài được vì marketplace dạng directory; chạy lại `agentflow-distribute publish` sau. Gọi lẻ từng bước: `agentflow/bin/agentflow-distribute --help`. Sau đó restart Claude Code hoặc `/reload-plugins` trong từng project. `/agentflow:learn` dùng cùng `install` + `compat`, không commit, không push.

Không bump version thì `update` báo *already at latest* và không refresh. Lặp nhanh khi dev: `uninstall` rồi `install` lại.

## Test trước khi phát hành

```bash
python3 -I -m unittest discover -s agentflow/tests             # script + contract, không cần mạng, không tốn token
claude plugin validate ./agentflow
python3 -I agentflow/bin/agentflow-board doctor --root <repo đã init>   # kiểm với GitHub thật, token của gh
agentflow/evals/run.sh --runs 1 --max-cost-usd 5               # hành vi của agent, tốn token — xem evals/README.md
```

| Tầng | File | Kiểm gì |
|---|---|---|
| Guard | `tests/test_guard.py`, `tests/test_shellparse.py` | Bảng lệnh chặn/cho qua, role, hook thật |
| Script | `tests/test_afconfig.py`, `test_board.py`, `test_tools.py` | Parser YAML (đối chiếu PyYAML nếu có), forbidden, API giả, không lộ secret, radar + lint flow + dạng phát hiện của `agentflow-audit` |
| Contract | `tests/test_contract.py` | Trần ký tự của prompt, tham chiếu `§`, path `${CLAUDE_PLUGIN_ROOT}`, lệnh `agentflow-board`, frontmatter, stage/label/`[AF:…]` khớp giữa file |
| E2E | `tests/e2e/run.py` | Nguyên `/agentflow:do` với git thật, hook thật, GitHub giả có trạng thái (schema ghi từ server thật): assert trên kết quả ở GitHub và git. Tốn token |
| Phát hành | `tests/test_distribute.py` | tìm source, bản cache chuyển sang bản source, `plan`/`compat` phán đúng project cũ, `bump` giữ nguyên `plugin.json`, `publish` từ chối cây bẩn/nhánh khác/version đã tag, push nhánh + tag, `install` chạy trong từng project và bắt version lệch |
| Eval | `evals/` | Agent thật + MCP giả: DoR của SA, review ❌, escalate, hook thật chặn force-push và đọc secret |

Sửa guard hoặc script → thêm case cho mỗi lỗ hổng/chặn nhầm vừa sửa. Sửa prompt của agent → chạy eval của agent đó (`--case`). Repo không dùng CI: chạy tầng không tốn token trên máy trước khi push.

## Quy ước

- Prompt runtime (`agents/`, `references/`, `skills/`) là **chi phí token mỗi lần chạy**: mệnh lệnh ngắn, một fact một chỗ, lý do để ở `DESIGN-NOTES.md`. Trần ký tự của từng file nằm ở `tests/test_contract.py` (`BUDGETS`), không nâng trần khi chưa xoá được gì.
- Script: Python 3 stdlib, không dependency. Không bao giờ in token; header bí mật đưa qua stdin (`curl -K -`).
- Đổi key `agentflow.yaml`, ngữ nghĩa stage, dòng đầu `[AF:…]` hay key state block = **schema change**: tăng `schema` (template + `scripts/afconfig.py` + `references/protocol.md`), bump minor/major. Ngoại lệ: thay đổi mà config, ticket và comment của bản cũ vẫn được đọc đúng (key tuỳ chọn có fallback, tên cũ được đọc như tên mới) thì giữ `schema`, bump version, ghi lý do ở `DESIGN-NOTES.md` — tăng `schema` buộc mọi repo chạy lại `/agentflow:init`.

## Phân phối cho team

`master` có branch protection chặn force-push và xoá nhánh. Mỗi release đi qua `/agentflow:distribute` (tạo tag `agentflow--v<version>`). Teammate: `claude plugin marketplace add signtoappstore/agent-flow-plugin` một lần, sau đó `marketplace update` + `plugin update` + restart. Máy không giữ source thì `/agentflow:learn` dừng và đề nghị gửi bài học qua issue/PR.
