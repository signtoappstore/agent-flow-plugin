# AgentFlow

Plugin Claude Code biến một repo GitHub thành **team agent có kỷ luật**, mỗi vai một chuyên gia:

| Vai | Chạy ở đâu | Việc |
|---|---|---|
| **PO** | `/agentflow:task`, ngay trong session của bạn (không subagent) | Expert PO cố vấn bạn viết ticket: vấn đề, bối cảnh, giá trị, người dùng, kết quả đo được, phạm vi, tiêu chí nghiệm thu kiểm được. Không code, không giải pháp kỹ thuật trong ticket |
| **SA** (Opus) | subagent, ở Ready rồi In Review | Phân tích yêu cầu, chặn ticket chưa đủ, chọn giải pháp tốt nhất và hợp tech stack của repo, **đánh giá rủi ro, lập test case cần kiểm chứng**; sau đó review PR theo thiết kế khi flow đã pass trên staging |
| **DEV** (Opus) | subagent, ở In Progress | Expert software engineer kiêm automation tester: code theo thiết kế của SA (kiến trúc, SOLID, pattern, clean code), gắn element id, viết flow automation (Maestro trước, **không viết unit/mock test**), merge lên staging; lượt **verify** (context mới) chờ deploy server/web (không chờ release mobile), chạy flow của ticket + danh sách Regression SA chốt, tự sửa tối đa 3 vòng; vẫn fail thì ghi lỗi block lên ticket |

Agent tự chạy ticket trên GitHub Projects board **tới cổng của con người**. Bạn chỉ làm ba việc: **chốt việc** (PO kéo Backlog → Ready, hoặc xác nhận ngay trong `/agentflow:task`), **QC tay** khi cần, và **merge**.

- **Một plugin, nhiều repo** — tên cột, label, nhánh, lệnh check của từng repo nằm trong `agentflow.yaml`; plugin chỉ giữ ngữ nghĩa.
- **Tối ưu token** — lệnh chỉ load khi gọi, mỗi ticket một subagent (session chính chỉ giữ 3 dòng kết quả), thiết kế của SA để DEV khỏi dò code lại và để SA review nhanh theo chính thiết kế đó, không có QC agent (DEV vốn đã build app và biết UI nên tự viết + chạy flow trong cùng một lượt), chỉ chạy flow của ticket + danh sách Regression SA chốt (có trần `run.max_regression`; diff chỉ chạm backend thì chỉ trên web), flow mới chạy 1 lần khi sửa và thêm 2 lần ở head cuối, DEV chạy flow trong lượt verify với context mới, lệnh dài chạy tách và chờ từng bước < 180 giây (harness đẩy nền lệnh dài hơn, mỗi lần poll đọc lại cả context), xem ảnh khi fail, review lặp lại chỉ soát diff mới, chờ pipeline theo nhịp giữ prompt cache, lệnh check lưu sẵn trong config, output dài vào log.
- **Code luôn từ `origin/master`** (hoặc `git.base`) — mỗi ticket một worktree **detached** tạo từ `origin/master` vừa fetch (ticket đã có nhánh trên remote: từ `origin/<branch>`), không tạo nhánh local (hook chặn DEV tạo hay gắn vào nhánh local); `CLAUDE.md`, code đọc trong worktree hoặc ở base trên remote. Không đụng checkout chính của bạn: không đổi nhánh, không stash, không sửa `.gitignore` (`.claude/worktrees/` ghi vào `.git/info/exclude`), không prune worktree của bạn, không dời nhánh local nào. Bạn đổi nhánh, sửa dở, kể cả checkout đúng nhánh của ticket lúc agent đang chạy cũng không ảnh hưởng agent; nhánh bạn mở không có `agentflow.yaml` thì agent và hook dùng bản đã commit trên origin. Xong việc vẫn push nhánh ticket, merge lên staging và mở PR draft vào base.
- **Tự học** — agent tự ghi friction vào journal; `/agentflow:learn` chưng cất thành diff nhỏ vào plugin, bạn duyệt rồi mới phát hành.

## Luồng

```
Backlog ─PO (/task)→ Ready ─SA design: giải pháp + rủi ro + test case (+agentflow)─DEV→ In Progress
   In Progress: code + element id + flow → draft PR → merge staging ─RESULT verify→ DEV verify (context mới):
                chờ deploy server/web → chạy flow của ticket + Regression của thiết kế
                fail → sửa (gắn id / sửa code) → deploy lại → chạy lại, tối đa run.max_test_rounds (3) vòng
                vẫn fail → [AF:DEV] blocked: lỗi block từng TC lên issue, +blocked, đứng nguyên cột
   pass ─→ In Review ─SA review ✅─┬─ PR còn mục QC tay → In QC +qc-manual → QC người tick + kéo card → undraft ─┐
                                    └─ không có → undraft ──────────────────────────────────────────────────────┴→ Ready to Merge ─người merge→ Done

Chế độ ask (SA)     → [AF:SA] options: người chọn phương án → [AF:SA] design có mục "0. Sẽ thực hiện" → người xác nhận → DEV
SA hỏi PO           → [AF:SA] ? +needs-info, ticket ở Ready chưa ai nhận: PO sửa bằng /agentflow:task #n rồi bỏ label
Review ❌            → In Progress +changes-requested; DEV sửa, deploy lại, chạy lại flow liên quan rồi giao review phần mới
QC người fail       → gắn qc-failed + comment → Ready; DEV tái hiện bằng flow, sửa trước việc mới
Góp ý trên PR       → In Progress, PR về draft: comment trên dòng code chưa được trả lời hoặc Request changes (ở In Review,
                      In QC, Ready to Merge), gắn changes-requested (ở Ready to Merge). DEV xét từng góp ý: hợp lý thì sửa, không
                      thì trả lời lý do trong thread; người vẫn giữ ý thì làm theo. Comment thường chỉ được đọc kèm
Pipeline fail       → DEV đọc log: do ticket thì sửa (tính vòng); do hạ tầng/ticket khác hay quá staging.timeout_min → +blocked
Bị chặn ở cột nào   → +blocked / +needs-info, ticket đứng nguyên; người trả lời rồi bỏ label
Review ❌ liên tiếp > 3 hoặc QC người fail > 2 → +blocked + [AF:SYS] escalated (round reset); người góp ý rồi bỏ blocked
```

PR có mục **Kiểm chứng lại**: *QC tay* (chặn merge — case không tự động được) và *Đề xuất kiểm chứng thêm* (regression ở vùng rủi ro SA nêu và phần diff chạm mà flow không phủ — không chặn).

Nhánh staging (`staging.branch`, bắt buộc) chỉ để build test: DEV merge dồn nhánh ticket vào đó (từ worktree tạm, hook kiểm), không reset, không force-push, không merge ngược về PR hay master. Vì vậy trên staging có thể có code chưa đạt của ticket khác; nhánh lệch nhiều thì bạn tự reset. Job release mobile (TestFlight, Firebase…) khai ở `staging.skip_checks` để DEV không chờ; flow mobile chạy trên emulator với bản build trỏ server staging (`surfaces.<key>.install`), chỉ build lại khi code mobile đổi.

**Workflow trên staging — DEV tự làm, không hỏi bạn**: sau mỗi lần push staging, DEV huỷ run cũ còn chạy trên staging, dispatch các workflow khai `when: push` trong `staging.workflows` (pipeline chỉ chạy tay), dispatch `when: need` khi cần (vd build app staging); check fail do hạ tầng/flaky thì rerun job fail, tối đa 2 lần mỗi run, rồi mới `blocked`. Mọi thao tác đi qua `agentflow-board dispatch|rerun|cancel`: ref luôn là `staging.branch`, inputs chỉ lấy từ config, workflow ngoài danh sách và run của nhánh khác bị từ chối; `gh workflow run`, `gh run rerun|cancel`, REST và MCP trực tiếp vẫn bị hook chặn. Push nhánh ticket và staging vốn không cần bạn duyệt (khi đã có allow rule, xem §Chạy không cần bạn).

```yaml
staging:
  workflows:
    - file: deploy-staging.yml
      when: push                 # push | need
      inputs: { env: staging }   # tuỳ chọn, cố định
```

**Nền tảng** (mobile, web, backend) là label `labels.platform`, một ticket gắn được nhiều label: `/agentflow:task` gợi ý theo nơi người dùng dùng, PO chốt; SA thêm khi thiết kế chạm nền tảng khác (thường là backend). Board bản cũ có field Platform: `/agentflow:init` chuyển giá trị sang label (`agentflow-board platform-migrate`) rồi xoá field khi bạn duyệt.

**Flow nào được chạy lại sau khi deploy staging**: flow của ticket (tag `af-<n>`) + mục **Regression** SA ghi trong thiết kế, tối đa `run.max_regression` (mặc định 6). SA lấy gợi ý từ `agentflow-e2e select`, mỗi flow kèm lý do: flow đổi trong diff › `e2e_map` (glob path → tag flow — cách duy nhất chắc chắn cho backend, vì flow UI không chứa path code backend) › path API trong script của flow trùng thư mục bị đổi › element id của flow nằm trong file client bị đổi. Diff chỉ chạm backend ⇒ chỉ flow web. Phần vượt trần vào "Đề xuất kiểm chứng thêm"; cả suite để CI. Ví dụ khai báo trong `agentflow.yaml`:

```yaml
e2e_map:
  "backend/services/notification/**": [inbox]     # flow có tags: [inbox] chạy lại khi service notification đổi
```

Tên cột thật của board được map trong `agentflow.yaml` → `board.status`.

### Làm rõ yêu cầu: auto · ask

Hai cổng trước khi làm: **tạo task** (`/agentflow:task`) và **implement** (trước khi DEV code). Mỗi cổng chạy một trong hai chế độ, đọc từ `clarify.task` / `clarify.implement` trong `agentflow.yaml` của repo; thiếu key thì mặc định **ask**.

| | auto | ask |
|---|---|---|
| `/agentflow:task` | Không hỏi theo từng mục: agent tự chọn phương án hợp tài liệu sản phẩm và hành vi đang chạy nhất, ghi mỗi quyết định kèm căn cứ vào section **Giả định (agent tự chọn)** của ticket. Vẫn hỏi bạn trước khi chuyển Ready | Hỏi bạn từng điểm mở, đưa các hướng sản phẩm kèm được/mất để bạn chọn, rồi in **Sẽ thực hiện** (issue nào tạo/sửa, type, số AC, field, cha/sub, liên kết) để bạn xác nhận trước khi ghi lên GitHub |
| Implement | SA tự chọn giải pháp tốt nhất và hợp stack nhất, quyết luôn điểm mơ hồ, ghi `mơ hồ → đã chọn → căn cứ` trong `[AF:SA] design` | SA đăng `[AF:SA] options` (≤ 4 điểm cần chọn, phương án đề xuất đứng đầu) → bạn chọn → SA viết thiết kế có mục **0. Sẽ thực hiện** → bạn xác nhận → DEV mới bắt đầu. `/agentflow:do` hỏi ngay trong terminal; `/agentflow:run` hỏi qua GitHub: ticket mang `needs-info`, bạn trả lời `1A 2B` (hoặc `OK` = theo mọi đề xuất) rồi bỏ label, lần sau bỏ label lần nữa để xác nhận kế hoạch |

DoR vẫn chặn ở cả hai chế độ (thiếu AC, AC mâu thuẫn, Size phải tách, bị chặn, thiếu input không suy ra được).

## Yêu cầu

| Thứ | Ghi chú |
|---|---|
| Claude Code ≥ 2.1.295 | plugin dùng skills, `bin/`, hooks `onFailure` (đã test trên 2.1.314) |
| `git`, `python3` ≥ 3.9, `jq` | `jq` cho `/agentflow:learn` và init |
| Nhánh staging + pipeline | Push vào staging phải chạy pipeline và báo check về commit (GitHub Actions hoặc CI ngoài có commit status) |
| GitHub CLI `gh` đã đăng nhập, token **full scope** | Plugin dùng token của `gh`, không lưu bản sao. Token **bắt buộc có mọi scope** của classic token (`repo`, `workflow`, `admin:org`, `project`, `delete_repo`, `admin:enterprise`, … — danh sách gốc: `FULL_SCOPES` trong `bin/agentflow-board`); thiếu scope nào thì `whoami`/`doctor` ✗. `agentflow-board whoami` in đúng lệnh cần chạy: `gh auth login -h github.com -s <mọi scope>` hoặc `gh auth refresh -h github.com -s <scope thiếu>`. GitHub không cấp đủ qua `gh` thì tạo [classic token](https://github.com/settings/tokens/new) tick mọi ô rồi `gh auth login -h github.com --with-token` |
| Maestro (khuyến nghị) | DEV viết và chạy flow để test UI mobile và web như người dùng: `curl -fsSL https://get.maestro.mobile.dev \| bash`, `maestro` phải nằm trong PATH; mobile cần emulator/simulator đang chạy. `/agentflow:doctor` báo khi thiếu |
| Figma (tuỳ chọn) | MCP chính thức, OAuth: `/mcp` → figma → Authenticate |
| Telegram (tuỳ chọn) | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

**Token GitHub là token của `gh`** (`$GH_TOKEN`, `$GITHUB_TOKEN`, rồi `gh auth token` — đúng thứ tự của `gh`), dùng chung cho script và GitHub MCP. MCP lấy nó qua `headersHelper` (`scripts/mcp-headers.py`) mỗi lần connect: đổi tài khoản hoặc thêm scope bằng `gh auth login` / `gh auth refresh` → `/mcp` → `plugin:agentflow:github` → **Reconnect**, không cần restart.

Secret còn lại của plugin (Telegram) nằm trong block `env` của **`.claude/settings.local.json`** của từng repo (gitignored — init kiểm trước). Ghi bằng tool đi kèm để value không bao giờ hiện ra (guard chặn agent Read/Edit file này):

```bash
read -s T && printf '%s\n' "$T" | agentflow-settings set-secret TELEGRAM_BOT_TOKEN   # tương tự TELEGRAM_CHAT_ID
agentflow-settings show                                                             # cây key, value bị che
agentflow-settings unset GITHUB_TOKEN                                               # xoá token cũ từ bản < 2.2
```

`env.GITHUB_TOKEN` / `env.GH_TOKEN` trong file này không còn được plugin đọc, nhưng Claude Code vẫn đưa chúng vào env của session nên chúng thắng tài khoản `gh` — `/agentflow:doctor` báo ⚠ khi còn.

App id và tài khoản test của staging **không** nằm trong `env`: agent đọc chúng trong secret folder của project (gitignored, vd `secret/staging/`), path ghi ở `staging.notes`; folder này không được nằm trong `forbidden`. Bật Telegram thì init chỉ xong khi file có cặp `TELEGRAM_*`; `/agentflow:doctor` báo ✗ khi thiếu.

Script của plugin (`agentflow-board`, `agentflow-notify`, helper của GitHub MCP) đọc thẳng `env` trong file này, nên giá trị vừa ghi có hiệu lực ngay, không cần restart Claude Code. Lệnh cần secret trong `env` chạy qua `agentflow-settings exec -- <lệnh>`: giá trị trong file đè lên env cũ của session và không hiện ra transcript.

## Cài đặt

```bash
claude plugin marketplace add signtoappstore/agent-flow-plugin     # phát triển plugin: thay bằng đường dẫn tới bản clone
cd <repo của bạn>
claude plugin install agentflow@agent-flow-plugins --scope local
claude plugin enable  agentflow@agent-flow-plugins --scope local
# mở Claude Code trong repo, rồi:
/agentflow:init
```

`--scope local` để mỗi repo tự bật plugin và giữ token riêng. Plugin khai `defaultEnabled: false` — không tự chạy ở repo chưa đồng ý.

## Lệnh

| Lệnh | Việc |
|---|---|
| `/agentflow:init` | Wizard: token + scope, link board có sẵn (map cột, thêm cột thiếu mà **không mất card**) hoặc tạo board theo preset, label, issue type, issue form + PR template, convention git + lệnh check đọc từ repo, Figma, Telegram, people, permission mode; smoke test |
| `/agentflow:task <mô tả>` | **PO**: expert PO cố vấn tới khi ticket đủ — vấn đề → giá trị và đo thành công → người dùng → phạm vi → AC → luật nghiệp vụ, trường hợp biên; nắm sản phẩm qua tài liệu thiết kế (`design.repo`, đọc đúng mục), Figma, ảnh, tìm issue trùng, **không đọc code**; mọi ý trong ticket do PO nói hoặc xác nhận, viết bằng ngôn ngữ sản phẩm, chỉ dẫn tài liệu khi cần; PO nói bằng giải pháp thì đổi thành nhu cầu. Chấm chất lượng (vấn đề, giá trị, AC kiểm được, đường lỗi, phạm vi, không giải pháp kỹ thuật, cỡ) trước khi ghi vào **Backlog**. Đạt cổng Ready (AC kiểm được, Priority, Size, label nền tảng, assignee, milestone nếu repo có) thì hỏi PO chuyển **Ready**, rồi hỏi chạy `/agentflow:do`. Việc lớn hay nhiều việc: hỏi PO chọn 1 ticket, issue cha + sub-issue (tách theo lát giá trị) hay ticket độc lập (chế độ auto: tự chọn theo cùng dấu hiệu). `#n` = hoàn thiện issue ở Backlog, hoặc ở Ready khi DEV chưa nhận (kể cả needs-info) |
| `/agentflow:do #n` | Xử lý **một** ticket qua SA design → DEV (code + flow, deploy staging, chạy flow, tự sửa) → SA review, tới cổng của người |
| `/agentflow:run` | Chạy **cả hàng đợi**: việc dở trước (feedback → QC người fail → review → rework), rồi Ready theo Priority (DEV nhận việc đã thiết kế trước khi SA thiết kế việc mới); `--only sa` để SA thiết kế trước cả hàng Ready; song song `run.parallel` ticket; dừng khi hết việc hoặc đủ `run.max_tasks`. Chạy định kỳ: `/loop 30m /agentflow:run` |
| `/agentflow:status` | Đếm theo stage, việc chờ người, bất thường. `--metrics`: cycle time, first-pass yield, số lần fail, aging + thống kê journal |
| `/agentflow:doctor` | Kiểm config, token/scope, board mapping, label, MCP, hook, Figma, Telegram — chỉ cách sửa từng lỗi |
| `/agentflow:learn [bài học]` | Gom journal + bài học → diff nhỏ vào source plugin → bạn duyệt → bump version → validate → phát hành |

## Bên trong

| Thành phần | Vai trò |
|---|---|
| `agents/sa.md` · `dev.md` | Hai subagent Opus (model đổi qua `run.models`): SA effort xhigh, DEV effort high. SA `MODE=design`: DoR + thiết kế (`[AF:SA] design`: giải pháp, rủi ro, test case `e2e`/`api`/`tay`), `MODE=review`: soát theo thiết kế + file rủi ro + flow + Kiểm chứng lại, ✅ thì giao QC người hoặc undraft. DEV code theo thiết kế, viết + chạy flow trên staging, ghi "Lệch thiết kế", bảng AC → code → TC → flow, Kiểm chứng lại vào PR |
| `references/engineering.md` | Chuẩn kỹ thuật chung của SA và DEV: kiến trúc theo tầng của repo, SOLID, pattern khi cần, KISS/YAGNI/DRY, bảo mật, hiệu năng, test, tự review |
| `bin/agentflow-style` | Soát dòng code mới: hàm thân biểu thức (`=>`), điều kiện `&&`/`||`, ternary bị formatter bẻ dòng. DEV phải sạch trước khi push, SA ❌ mỗi chỗ còn lại. Viết vừa một dòng thì vẫn được; `CLAUDE.md` của repo nói khác thì theo `CLAUDE.md` |
| `references/protocol.md` | Contract chung: stage, label, board call, state block, comment `[AF:…]`, thứ tự ghi, git, token hygiene, journal |
| `references/dispatch.md` | Orchestrator: hàng đợi, bảng hành động, model, song song, no-progress guard |
| `references/design.md` | Figma / design trong repo — chỉ load khi ticket chạm UI |
| `references/clarify.md` | Làm rõ yêu cầu auto · ask: `/agentflow:task`, orchestrator và SA design chỉ đọc khi cần (task luôn đọc; implement chỉ ở chế độ ask) |
| `references/automation.md` | Test case từ yêu cầu + rủi ro, quy ước element id theo nền tảng, cách viết flow (Maestro trước, mobile và web, thao tác như người dùng), chọn flow liên quan, chạy trên staging, phân định fail, ảnh chỉ khi cần, mục Kiểm chứng lại — DEV đọc khi có test case e2e/api |
| `skills/*` | 7 lệnh (`disable-model-invocation` — không tốn context khi không gọi) |
| `hooks/hooks.json` + `scripts/guard.py` · `shellparse.py` | Hook chặn (best-effort, xem §Chạy không cần bạn), kể cả qua lệnh bọc (`bash -c`, `env`, `timeout`, `$(…)`, `xargs`, `eval`, code Python/Node): merge/approve PR, dispatch/rerun/cancel workflow ngoài `agentflow-board` (chỉ staging, workflow khai báo; SA không được), force-push, xoá nhánh remote, xoá repo/package, push nhánh protected/base, đọc/sửa/in path `forbidden`, token trong tham số. Thêm luật theo role: SA chỉ đọc (không sửa file, không push, không đổi git); DEV chỉ ghi trong worktree `af-<n>` và worktree staging `af-<n>-staging`, không tạo/gắn nhánh local (`switch`, `checkout -b`, `worktree add -b`), push staging chỉ từ worktree staging và worktree đó chỉ push vào staging, không đưa staging vào nhánh ticket (merge, reset, restore, push `origin/staging:<nhánh>`), không `update-ref`/`read-tree`/`git branch` ghi, không `pull` ngoài worktree, không undraft |
| `scripts/result-check.py` | Hook `SubagentStop`: subagent phải kết thúc bằng khối `RESULT` |
| `bin/agentflow-board` | Setup + chẩn đoán qua GraphQL (Status option, field, view, label, issue type, doctor, metrics) + đọc check pipeline staging + gom góp ý của người trên PR (`feedback`) + milestone mở cho `/agentflow:task` (`milestones`) + workflow trên staging (`dispatch`, `rerun`, `cancel`) + chuyển field Platform sang label (`platform-migrate`) |
| `bin/agentflow-base` | Worktree ticket tính từ remote base: `worktree <n> --branch B` (tạo/cập nhật worktree ticket detached từ `origin/B` hoặc `origin/<base>` vừa fetch, việc chưa bắt đầu thì dời lên base mới, giữ phần dở, fast-forward/merge khi có người push vào nhánh, từ chối bỏ việc chưa push của nhánh khác, init submodule) · `clean` (orchestrator dọn worktree, không bao giờ xoá commit chưa push) |
| `bin/agentflow-e2e` | `select`: flow có sẵn cần chạy lại cho một thay đổi + lý do (SA lúc thiết kế, DEV khi diff lệch thiết kế) · `run`: chạy flow Maestro tách khỏi shell của agent (lặp, nhiều thiết bị, `--env-file` không lộ giá trị; `--install` build + cài app khi thiết bị chưa có đúng bản; mỗi thiết bị một ticket một lúc, lượt sau báo `queued`) · `wait`: chờ ≤ 160 giây rồi in một dòng JSON (flow fail + bước + log), `--log` cho build chạy tách |
| `bin/agentflow-journal` · `agentflow-notify` · `agentflow-settings` | Journal tự học (`~/.claude/agentflow/journal.jsonl`) · ping Telegram · sửa settings local và chạy lệnh với `env` của nó, không lộ secret |
| `scripts/mcp-headers.py` | `headersHelper` cấp token cho GitHub MCP lúc connect |
| `templates/` | Issue form, PR template, README board |
| `tests/` · `evals/` | Test không tốn token (guard, script, contract giữa prompt và code) · eval agent thật với MCP giả |

Phối hợp hoàn toàn qua GitHub: **Status** trên board (sự thật), **label** (tín hiệu), **state block ẩn** cuối issue body (`<!-- agentflow:state … -->` — round, PR, branch, sha, deploy), **comment `[AF:ROLE] event`** (audit + phân biệt agent với người vì agent dùng token của bạn).

## Chạy không cần bạn

`/agentflow:init` đề nghị thêm allow rule để loop và subagent không dừng hỏi quyền — `--user` ghi vào `~/.claude/settings.json` cho mọi repo, bỏ `--user` thì chỉ `.claude/settings.local.json` của repo này. Plugin không tự cấp quyền được: `settings.json` của plugin và `permissionMode` trong frontmatter agent đều bị bỏ qua.

```bash
agentflow-settings allow --user Bash Read Edit Write WebFetch WebSearch Skill mcp__plugin_agentflow_github mcp__plugin_agentflow_figma
```

`permissions.defaultMode: "bypassPermissions"` trong settings của project **không có tác dụng**: Claude Code (đo trên 2.1.317) bỏ qua nó và chạy ở `default`, nên mọi tool chưa có trong allow list (vd tool của GitHub MCP) đều dừng hỏi. Muốn bypass hẳn thì mở bằng `claude --permission-mode bypassPermissions`. `/agentflow:doctor` báo ⚠ khi allow list thiếu rule.

Khi đó lớp chặn là **hook guard** của plugin (luôn chạy, kể cả bypass; thiếu Python hoặc quá giờ thì chặn; guard lỗi nội bộ thì chặn nếu lệnh có từ khoá rủi ro). Guard đọc cấu trúc lệnh nhưng không thấy thứ chỉ lộ ra lúc chạy (`make deploy`, script sinh động) — best-effort, không phải ranh giới bảo mật tuyệt đối; branch protection phía GitHub vẫn là lớp chắc nhất nếu gói của bạn có, `/agentflow:doctor` báo khi base chưa bật.

## Tự học

1. Agent gặp friction (review/QC fail mà lẽ ra tự bắt được, call phải thử lại, người sửa convention, phải tự dò lệnh check…) → `agentflow-journal add …` một dòng.
2. `/agentflow:status --metrics` cho thấy chỗ đau (first-pass yield, aging).
3. `/agentflow:learn` → ≤ 5 bài học, mỗi bài một diff nhỏ vào đúng file (có trần ký tự để prompt không phình), gate theo `DESIGN-NOTES.md` §Non-goals, bạn duyệt → bump → `claude plugin validate` → `marketplace update` + `plugin update` → restart.

## Phát triển

Phát triển plugin: [`CONTRIBUTING.md`](CONTRIBUTING.md). Lý do thiết kế: [`DESIGN-NOTES.md`](DESIGN-NOTES.md). Dữ liệu đi đâu: [Privacy](PRIVACY.md).
