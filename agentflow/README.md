# AgentFlow

Plugin Claude Code biến một repo GitHub thành **team agent có kỷ luật**, mỗi vai một chuyên gia:

| Vai | Chạy ở đâu | Việc |
|---|---|---|
| **PO** | `/agentflow:task`, ngay trong session của bạn (không subagent) | Expert PO cố vấn bạn viết ticket: vấn đề, bối cảnh, giá trị, người dùng, kết quả đo được, phạm vi, tiêu chí nghiệm thu kiểm được. Không code, không giải pháp kỹ thuật trong ticket |
| **SA** (Opus) | subagent, ở Ready rồi In Review | Phân tích yêu cầu, chặn ticket chưa đủ, chọn giải pháp tốt nhất và hợp tech stack của repo, **đánh giá rủi ro, lập test case cần kiểm chứng**, ghi **bản đồ code** (`path:line` cần theo/dùng lại/bị ảnh hưởng) và chia lượt cho ticket lớn; sau đó **review code trước khi lên staging**, rồi chốt phần đổi + kết quả flow sau khi flow pass |
| **DEV** (Opus) | subagent, ở In Progress | Expert software engineer kiêm automation tester: code theo thiết kế của SA (kiến trúc, SOLID, pattern, clean code), gắn element id, viết flow automation (Maestro trước, **không viết unit/mock test**) phải **đỏ trên bản chưa có thay đổi**, qua `agentflow-board precheck` rồi giao SA review code; sau SA ✅ code, lượt **verify** (context mới) merge lên staging, chờ deploy server/web (không chờ release mobile), chạy flow của ticket + danh sách Regression SA chốt, tự sửa tối đa 3 vòng; vẫn fail thì ghi lỗi block lên ticket |
| **Audit** (Opus) | subagent của `/agentflow:checklist`, một lăng kính mỗi agent: qa trước, hội đồng sau | Kiểm thử toàn sản phẩm theo từng role rồi đề xuất việc có bằng chứng: **qa** (tester: ma trận vùng × role trên staging web/mobile, phân quyền, xác minh lỗi đã sửa, bộ bằng chứng ảnh/log, độ phủ automation) · hội đồng cùng đọc bằng chứng đó: **ux** (UI/UX designer: lỗi giao diện, trải nghiệm, chỗ còn prototype chưa đạt production, mức Prototype/Beta/Production từng vùng, ý tưởng đẹp hơn) · **product** (ma sát theo role, sáng kiến) · **arch** (engineering: nguyên nhân gốc, quyền phía server, code khó bảo trì). Chỉ đọc; bạn chọn mục nào thành ticket |

Agent tự chạy ticket trên GitHub Projects board **tới cổng của con người**. Bạn chỉ làm ba việc: **chốt việc** (PO kéo Backlog → Ready, hoặc xác nhận ngay trong `/agentflow:task`), **QC tay** khi cần, và **merge**.

- **Một plugin, nhiều repo** — tên cột, label, nhánh, lệnh check của từng repo nằm trong `agentflow.yaml`; plugin chỉ giữ ngữ nghĩa.
- **Tối ưu token** — lệnh chỉ load khi gọi, mỗi ticket một subagent (session chính chỉ giữ 3 dòng kết quả), thiết kế của SA để DEV khỏi dò code lại và để SA review nhanh theo chính thiết kế đó, không có QC agent (DEV vốn đã build app và biết UI nên tự viết + chạy flow trong cùng một lượt), chỉ chạy flow của ticket + danh sách Regression SA chốt (có trần `run.max_regression`; diff chỉ chạm backend thì chỉ trên web), flow mới chạy 1 lần khi sửa và thêm 2 lần ở head cuối, DEV chạy flow trong lượt verify với context mới, lệnh dài chạy tách và chờ từng bước < 180 giây (harness đẩy nền lệnh dài hơn, mỗi lần poll đọc lại cả context), xem ảnh khi fail, review lặp lại chỉ soát diff mới, chờ pipeline theo nhịp giữ prompt cache, lệnh check lưu sẵn trong config, output dài vào log.
- **Code luôn từ `origin/master`** (hoặc `git.base`) — mỗi ticket một worktree **detached** tạo từ `origin/master` vừa fetch (ticket đã có nhánh trên remote: từ `origin/<branch>`), không tạo nhánh local (hook chặn DEV tạo hay gắn vào nhánh local); `CLAUDE.md`, code đọc trong worktree hoặc ở base trên remote. Không đụng checkout chính của bạn: không đổi nhánh, không stash, không sửa `.gitignore` (`.claude/worktrees/` ghi vào `.git/info/exclude`), không prune worktree của bạn, không dời nhánh local nào. Bạn đổi nhánh, sửa dở, kể cả checkout đúng nhánh của ticket lúc agent đang chạy cũng không ảnh hưởng agent; nhánh bạn mở không có `agentflow.yaml` thì agent và hook dùng bản đã commit trên origin. Xong việc vẫn push nhánh ticket, merge lên staging và mở PR draft vào base. Nhận lại ticket đã làm (gọi lại `/agentflow:do #n`, ticket bị trả về, lượt sau của thiết kế chia lượt): mỗi lượt DEV có code merge `origin/master` mới nhất vào nhánh trước khi code (không rebase), conflict thì DEV giải; SA review lại bỏ qua phần base kéo vào.
- **Tự học** — agent tự ghi friction vào journal; `/agentflow:learn` chưng cất thành diff nhỏ vào plugin, bạn duyệt rồi mới ghi.

## Luồng

```
Backlog ─PO (/task)→ Ready ─SA design: giải pháp + rủi ro + test case (+agentflow)─DEV→ In Progress
   In Progress: code + element id + flow (lượt 1..k nếu thiết kế chia lượt) → flow mới đỏ trên bản chưa có thay đổi
                → precheck → draft PR ─→ In Review (step: code) ─SA review code ❌→ In Progress
   In Review:   SA ✅ code (step: verify) ─→ DEV verify (context mới): merge staging → chờ deploy server/web (orchestrator
                chờ khi không build app trên máy) → chạy flow của ticket + Regression của thiết kế
                fail → sửa (gắn id / sửa code) → deploy lại → chạy lại, tối đa run.max_test_rounds (3) vòng
                vẫn fail → [AF:DEV] blocked: lỗi block từng TC lên issue, +blocked, đứng nguyên cột
                pass (step: final) ─SA chốt phần đổi + kết quả ✅─┬─ PR còn mục QC tay → In QC +qc-manual → QC người tick + kéo card → undraft ─┐
                                                                   └─ không có → undraft ──────────────────────────────────────────────────────┴→ Ready to Merge ─người merge→ Done

Chế độ ask (SA)     → [AF:SA] options: người chọn phương án → [AF:SA] design có mục "0. Sẽ thực hiện" → người xác nhận → DEV
SA hỏi PO           → [AF:SA] ? +needs-info, ticket ở Ready chưa ai nhận: PO sửa bằng /agentflow:task #n rồi bỏ label
Review ❌            → In Progress +changes-requested; DEV sửa rồi giao review phần mới (chưa lên staging nên không tốn deploy)
QC người fail       → gắn qc-failed + comment → Ready; DEV tái hiện bằng flow, sửa trước việc mới
Góp ý trên PR       → In Progress, PR về draft: comment trên dòng code chưa được trả lời hoặc Request changes (ở In Review,
                      In QC, Ready to Merge), gắn changes-requested (ở Ready to Merge). DEV xét từng góp ý: hợp lý thì sửa, không
                      thì trả lời lý do trong thread; người vẫn giữ ý thì làm theo. Comment thường chỉ được đọc kèm
Pipeline fail       → DEV đọc log: do ticket thì sửa (tính vòng); do hạ tầng/ticket khác hay dispatch không chạy gì → +blocked
Bị chặn ở cột nào   → +blocked / +needs-info, ticket đứng nguyên; người trả lời rồi bỏ label
Issue cha ở Ready   → một ticket: các sub-issue chung một nhánh, một PR (Closes cha + từng sub), một lượt test trên staging,
                      một review, một lượt QC; Status của sub theo cha. DEV code hết các sub rồi mới gom một lượt flow
                      automation. Cha ở Backlog chỉ gom việc, sub đi riêng; /agentflow:do #cha đề xuất gộp chung một PR
Review ❌ liên tiếp > 3 hoặc QC người fail > 2 → +blocked + [AF:SYS] escalated (round reset); người góp ý rồi bỏ blocked
```

PR có mục **Kiểm chứng lại**: *QC tay* (chặn merge — case không tự động được) và *Đề xuất kiểm chứng thêm* (regression ở vùng rủi ro SA nêu và phần diff chạm mà flow không phủ — không chặn).

Nhánh staging (`staging.branch`, bắt buộc) chỉ để build test: DEV merge dồn nhánh ticket vào đó (từ worktree tạm, hook kiểm), không reset, không force-push, không merge ngược về PR hay master. Vì vậy trên staging có thể có code chưa đạt của ticket khác; nhánh lệch nhiều thì bạn tự reset. Flow mobile chạy trên emulator với bản DEV build trên máy, trỏ server staging (`surfaces.<key>.install`), chỉ build lại khi code mobile đổi: DEV không bao giờ build/distribute mobile trên CI.

**Staging chỉ chạy qua dispatch — agent tự quyết theo task, không hỏi bạn**: `staging.workflows` chỉ là danh sách file workflow agent được chạy trên staging (vd `[staging.yml]`). Agent đọc ô (input boolean + mô tả trong `workflow_dispatch.inputs`) bằng `agentflow-board workflows`, rồi tự chọn bật ô nào theo task — mô tả ô rõ thì agent chọn đúng. Workflow staging không cần trigger push (doctor báo workflow nào còn chạy khi push staging).

- **DEV**, sau mỗi lần push staging: `agentflow-board dispatch` (ô cần bật thì `--on <ô>`, ô boolean khác gửi `false`). Không bật ô nào thì lệnh tự so head staging với bản deploy thành công gần nhất của workflow: thay đổi chỉ nằm ở doc, `.claude/`, `agentflow.yaml`, thư mục flow (`e2e_dir`) hay surface có `install` (app DEV build trên máy) ⇒ không dispatch, flow chạy luôn, không chờ pipeline (`deployed`) — vòng sửa chỉ đổi flow hay code mobile không tốn một lần deploy. Run mới nhất còn chạy, đỏ, bị huỷ hay của nhánh khác ⇒ vẫn dispatch; `--force` để dispatch bất kể. DEV không bật ô build app: flow mobile chạy trên bản build trên máy. Lúc giao review, DEV ghi vào state `qc_release` ô cần bật cho bản cài QC tay — chỉ khi có mục QC tay phải làm trên app mà simulator không thay được (thiết bị thật: push, mua trong app, camera, vị trí, màn khoá/widget, chạy nền, cảm biến, hiệu năng, icon; hay người soát UI app), chỉ ô của nền tảng có mục đó; QC tay chỉ ở web/API hay không có thì `—`. SA soát lựa chọn này lúc review.
- **Orchestrator**, khi SA giao ticket sang In QC: `qc_release` có ô thì dispatch bản đó cho QC người (`--qc`) rồi comment `[AF:SYS] qc-build` mention `people.qc`. QC tay là bước tuỳ chọn nên ticket không cần thì không build. Bạn vẫn tự dispatch tay được bất cứ lúc nào.
- DEV không chờ bản build QC chạy trên cùng commit; run deploy cũ hơn do agent dispatch bị huỷ khi run mới bật ít nhất chừng ấy ô; run của bạn, bản build QC, run có wipe giữ nguyên. Không có giới hạn chờ cố định: DEV chờ tới khi run kết thúc (`timeout-minutes` của job), chỉ `blocked` khi dispatch rồi mà 10 phút không có run nào; run xếp hàng sau run khác (`queued`) thì chờ tiếp.

Check fail do hạ tầng/flaky thì DEV rerun job fail, tối đa 2 lần mỗi run, rồi mới `blocked`. Mọi thao tác đi qua `agentflow-board dispatch|rerun|cancel`: ref luôn là `staging.branch`, chỉ workflow khai báo, agent chỉ đặt được ô boolean (input khác giữ mặc định của workflow hay giá trị cố định trong config); `gh workflow run`, `gh run rerun|cancel`, REST và MCP trực tiếp vẫn bị hook chặn, DEV không dùng được `--qc`. Merge commit DEV push lên staging mang `[skip ci]` khi có `staging.workflows` (vô hại khi không workflow nào chạy lúc push). Push nhánh ticket và staging vốn không cần bạn duyệt (khi đã có allow rule, xem §Chạy không cần bạn).

```yaml
staging:
  branch: staging
  url: https://staging.example.com
  notes: secret/staging/
  workflows: [staging.yml]       # input không phải boolean cần giá trị cố định: - {file: x.yml, inputs: {env: staging}}
```

**Wipe dữ liệu staging — agent tự quyết theo task**: ô xoá dữ liệu (input boolean có tên hay mô tả kiểu wipe, drop, xoá) luôn gửi `false`, trừ khi ticket cần dữ liệu sạch. SA chốt trong thiết kế (mục **Dữ liệu staging**: giữ, hoặc wipe khi migration không hợp dữ liệu cũ, seed đổi mà flow dựa vào); DEV còn wipe khi dữ liệu bẩn không phải của ticket làm flow sai và tự dọn không hết. Khi đó `agentflow-board dispatch --on wipe_data --issue <n>` ở lần deploy đầu của lượt (vòng sửa không wipe lại) và ghi lý do vào comment `[AF:DEV]`. Lệnh từ chối (exit 5) khi ticket khác của repo đang In QC (người đang test tay) hoặc đang chạy flow trên máy này; khi đó DEV deploy không wipe, bắt buộc phải wipe thì `blocked` hỏi bạn. Run có wipe không bị ticket push sau huỷ (trong 1 giờ), bản build QC cũng vậy (trong 3 giờ).

**Nền tảng** (mobile, web, backend) là label `labels.platform`, một ticket gắn được nhiều label: `/agentflow:task` gợi ý theo nơi người dùng dùng, PO chốt; SA thêm khi thiết kế chạm nền tảng khác (thường là backend). Board bản cũ có field Platform: `/agentflow:init` chuyển giá trị sang label (`agentflow-board platform-migrate`) rồi xoá field khi bạn duyệt.

**Flow nào được chạy lại sau khi deploy staging**: flow của ticket (tag `af-<n>`) + mục **Regression** SA ghi trong thiết kế, tối đa `run.max_regression` (mặc định 6). SA lấy gợi ý từ `agentflow-e2e select`, mỗi flow kèm lý do: flow đổi trong diff › `e2e_map` (glob path → tag flow — cách duy nhất chắc chắn cho backend, vì flow UI không chứa path code backend) › path API trong script của flow trùng thư mục bị đổi › element id của flow nằm trong file client bị đổi. Diff chỉ chạm backend ⇒ chỉ flow web. Phần vượt trần vào "Đề xuất kiểm chứng thêm"; agent không bao giờ chạy cả suite — chạm code client dùng chung thì SA thêm flow hành trình chính, vẫn trong trần. Ví dụ khai báo trong `agentflow.yaml`:

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

### Checklist cải tiến: `/agentflow:checklist`

Mỗi lần chạy là một vòng **kiểm thử toàn bộ sản phẩm theo từng role** cùng một hội đồng chuyên gia, và mỗi vòng để lại sản phẩm tốt hơn: lỗi thành ticket, lỗi đã sửa được xác minh lại, vùng chưa test được phủ dần.

```
/agentflow:checklist                       # hỏi lăng kính + phạm vi
/agentflow:checklist qa ux --focus "thanh toán"
/agentflow:checklist --areas all           # test mọi vùng trong một lượt (lâu, tốn token)
/agentflow:checklist arch product --max 8  # chỉ soát tĩnh
```

1. **Bản đồ toàn sản phẩm**: worktree `.claude/worktrees/af-audit` từ `origin/<base>` vừa fetch (không đụng checkout của bạn). `agentflow-audit map` kiểm kê mọi màn/route (web: Next, Expo, SvelteKit, Nuxt, React Router, Vue/Angular router; mobile: React Navigation, GoRouter/AutoRoute, Compose), mọi endpoint API (Express-like, Nest, FastAPI/Flask, Django, Go, Spring, Supabase functions) kèm gợi ý thiếu kiểm quyền, các **role** code nhắc tới, **tài khoản test của từng role** (chỉ đọc tên key `E2E_<ROLE>_EMAIL`… trong secret folder `staging.notes` và trong flow, không đọc giá trị). Kết quả là danh sách vùng (màn hoặc nhóm API).
2. **Kế hoạch lượt này** (`agentflow-audit plan`, đọc **Bản đồ phủ** của issue checklist lần trước): trước hết vùng có lỗi mà ticket đã đóng (**xác minh sửa**), rồi vùng có code đổi từ lần test trước, vùng chưa test, vùng test lâu nhất. Mặc định 15 vùng mỗi lượt (`--areas`), nên sau vài lượt là phủ đủ.
3. **Đợt 1, kiểm thử** (agent `qa`): mỗi vùng × mỗi role trên staging (web + mobile khi có thiết bị). Role được phép thì đi trọn hành trình chính, chụp từng state. Role không được phép thì mở thẳng URL/deep link và gọi API: phải bị chặn ở cả UI lẫn server (`⛔`), lọt qua là bug `cao`. Có đủ tài khoản thì thử thêm dữ liệu lộ chéo giữa hai tài khoản. Chạy lại flow tái hiện của lỗi đã đóng. Kết quả gồm bảng phủ và **bộ bằng chứng** (`evidence/index.md` + ảnh: vùng, role, state, lỗi console/mạng, thời gian chờ, số bước của từng hành trình).
4. **Đợt 2, hội chẩn**: ba chuyên gia đọc cùng bộ bằng chứng và cùng các lỗi qa vừa tìm, chạy song song:

| Lăng kính | Vai | Soát gì |
|---|---|---|
| `qa` | Tester automation | Lỗi chức năng, sai quyền, dữ liệu lộ chéo theo role; lỗi hiển thị thấy rõ; độ phủ + độ vững của flow (id chết, `optional`/`retry` che lỗi, chọn bằng chữ, chờ cứng…); flow thăm dò đã pass thì đề xuất giữ lại làm regression |
| `ux` | Expert UI/UX designer | Thứ bậc thị giác, nhịp/lưới, nhất quán component và token, trạng thái (loading/rỗng/lỗi), form, điều hướng, tiếp cận (tương phản, vùng chạm, nhãn), dark mode, dấu tiếng Việt; **mức production**: dấu vết prototype, design system, icon, asset, minh hoạ, nhận diện app (icon, splash, favicon), chữ chưa dịch hay trộn ngôn ngữ, so với hệ thiết kế trong code, chuẩn nền tảng (HIG, Material, WCAG) và app cùng lĩnh vực (`audit.benchmarks`); **sáng kiến đẹp hơn** chỉ dùng token/component sẵn có |
| `product` | Expert Product development | Ma sát của từng role trên lần đi thật (số bước, chờ, ngõ cụt), vòng giá trị, niềm tin, đo lường còn thiếu; ý tưởng ba tầm có JTBD, giả thuyết, RICE, Kano |
| `arch` (`eng`) | Expert engineering | **Nguyên nhân gốc** (`path:line`) của lỗi qa thấy, quyền chỉ kiểm ở client/thiếu kiểm chủ sở hữu, hotspot, phụ thuộc vòng, nuốt lỗi, N+1, CI thiếu check (`agentflow-audit scan`) |

   **Mức sẵn sàng production**: `agentflow-audit ready` đếm trước những gì còn làm sản phẩm giống prototype (lorem, dữ liệu giả, ảnh placeholder, nút không làm gì, lỗi hiện mã kỹ thuật, tiêu đề/file của template, màu/font/spacing viết cứng ngoài token, bộ icon trộn, emoji làm icon, ảnh nặng hay thiếu @2x/@3x/density, ảnh không dùng hay không có, app icon/splash/favicon/manifest thiếu, font thương hiệu, chữ ngoài l10n, màn thiếu state loading/rỗng/lỗi, tracking và crash reporting). ux xác nhận trên ảnh và chấm mỗi vùng vừa test: **Prototype** (dấu vết prototype người dùng thấy, luồng chính chưa nối, thiếu state lỗi/rỗng) · **Beta** (dùng được, còn mục cao/vừa) · **Production**. Mức phải khớp với các mục được dẫn ra (`- ready: prototype|beta`); product (luồng thiếu bước production) và arch (mock, cờ tạm, thiếu crash reporting) cũng gắn `ready` được.

   Chuyên gia nào thấy mục của qa chạm chuyên môn mình thì **thêm góc nhìn vào chính mục đó** (`- extends: qa:F<k>`): hướng thiết kế, tác động với người dùng và kinh doanh, nguyên nhân gốc. Một ticket vì vậy gom đủ ba góc nhìn, và có thể được nâng mức độ khi bằng chứng cho thấy nặng hơn.
5. `agentflow-audit findings` kiểm đúng dạng, nhập các góc nhìn, gộp trùng, rồi xếp theo mức độ → tái phát → số chuyên gia cùng thấy → công sức → RICE. Bạn chọn mục (chế độ `clarify.task: auto` tự lấy mục cao + vừa).
6. Ticket tạo ở **Backlog** dưới issue cha `Checklist cải tiến <ngày>`. Body issue cha có **Sức khoẻ** (mỗi lượt một dòng: % vùng đã phủ, số role đã test, số vùng đạt Production, số mục cao/vừa/thấp, tái phát, lỗi đã xác minh sửa), **Bản đồ phủ** (vùng × role: `✓` · `✗ #n` · `⛔` · `·` · `—`, cột **Mức** giữ tới lần vùng được test lại) và **Sổ phát hiện**. Lượt sau đọc lại cả ba. Muốn làm ngay: lệnh hỏi chuyển Ready qua `/agentflow:task #n`, rồi `/agentflow:do` hoặc `/agentflow:run`.

Audit chỉ đọc repo và GitHub (hook chặn ghi, push, đổi git, workflow; ghi nháp chỉ trong `af-audit` hoặc `/tmp`). Trên staging nó không thanh toán/gửi thật; dữ liệu tự tạo có tiền tố `af-audit-` và được dọn. Lượt chạy flow dùng `--issue 0` nên không lẫn với ticket, nhưng vẫn phải chờ khi DEV đang giữ thiết bị. Role thiếu tài khoản test thì lệnh chỉ đúng key cần thêm. Chi phí: bốn agent Opus, qa lâu nhất (build app, chạy ≤ 25 flow, ≤ 40 ảnh); ux đọc ≤ 40 ảnh, product ≤ 12.

## Yêu cầu

| Thứ | Ghi chú |
|---|---|
| Claude Code ≥ 2.1.295 | plugin dùng skills, `bin/`, hooks `onFailure` (đã test trên 2.1.314) |
| `git`, `python3` ≥ 3.9, `jq` | `jq` cho `/agentflow:learn` và init |
| Nhánh staging + pipeline | Deploy staging phải báo check về commit (GitHub Actions hoặc CI ngoài có commit status). Workflow khai `staging.workflows` cần trigger `workflow_dispatch`, ô bật/tắt là input boolean có mô tả rõ, và không nên còn trigger push vào staging (doctor báo). Repo deploy staging bằng CI tự chạy khi push (Vercel, CircleCI…) thì để `workflows` trống: DEV không gắn `[skip ci]` và chờ check của push |
| GitHub CLI `gh` đã đăng nhập, token **full scope** | Plugin dùng token của `gh`, không lưu bản sao. Token **bắt buộc có mọi scope** của classic token trừ `delete_repo`, `admin:enterprise` (`repo`, `workflow`, `admin:org`, `project`, … — danh sách gốc: `FULL_SCOPES` trong `bin/agentflow-board`); thiếu scope nào thì `whoami`/`doctor` ✗. `agentflow-board whoami` in đúng lệnh cần chạy: `gh auth login -h github.com -s <mọi scope>` hoặc `gh auth refresh -h github.com -s <scope thiếu>`. GitHub không cấp đủ qua `gh` thì tạo classic token theo link `whoami` in (ô tick sẵn) rồi `gh auth login -h github.com --with-token` |
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
| `/agentflow:task <mô tả>` | **PO**: expert PO cố vấn tới khi ticket đủ — vấn đề → giá trị và đo thành công → người dùng → phạm vi → AC → luật nghiệp vụ, trường hợp biên; nắm sản phẩm qua tài liệu thiết kế (`design.repo`, đọc đúng mục), Figma, ảnh, tìm issue trùng, **không đọc code**; mọi ý trong ticket do PO nói hoặc xác nhận, viết bằng ngôn ngữ sản phẩm, chỉ dẫn tài liệu khi cần; PO nói bằng giải pháp thì đổi thành nhu cầu. Chấm chất lượng (vấn đề, giá trị, AC kiểm được, đường lỗi, phạm vi, không giải pháp kỹ thuật, cỡ) trước khi ghi vào **Backlog**. Đạt cổng Ready (AC kiểm được, Priority, Size, label nền tảng, assignee, milestone nếu repo có) thì hỏi PO chuyển **Ready**, rồi hỏi chạy `/agentflow:do`. Việc lớn hay nhiều việc: hỏi PO chọn 1 ticket, issue cha + sub-issue (tách theo lát giá trị) hay ticket độc lập (chế độ auto: tự chọn theo cùng dấu hiệu). Issue cha: PO chọn làm chung một PR (cha sang Ready khi mọi sub đạt cổng) hay giao từng sub (cha ở Backlog). `#n` = hoàn thiện issue ở Backlog, hoặc ở Ready khi DEV chưa nhận (kể cả needs-info) |
| `/agentflow:do #n` | Xử lý **một** ticket qua SA design → DEV (code + flow) → SA review code → DEV (deploy staging, chạy flow, tự sửa) → SA chốt, tới cổng của người. Nhận `#n` hoặc link issue; issue cha = mọi sub-issue chung một PR, một lượt test, review, QC (cha ở Backlog: đề xuất gộp, người chọn); sub của nhóm đang chạy thì chỉ sang cha. Ticket đã làm trước đó: in **Nhận lại #n** (dừng ở đâu, thiết kế/review/flow nào còn dùng được, base đi bao xa, bước sẽ chạy) rồi chỉ chạy phần còn thiếu; conflict với base được gỡ trước review (ở QC/Ready to Merge thì hỏi); ticket Done mở lại thành lượt mới (PR mới, SA thiết kế phần còn thiếu) |
| `/agentflow:run` | Chạy **cả hàng đợi**: việc dở trước (feedback → QC người fail → review → rework), rồi Ready theo Priority (DEV nhận việc đã thiết kế trước khi SA thiết kế việc mới); `--only sa` để SA thiết kế trước cả hàng Ready; song song `run.parallel` ticket; dừng khi hết việc hoặc đủ `run.max_tasks`. Chạy định kỳ: `/loop 30m /agentflow:run` |
| `/agentflow:checklist [qa] [ux] [product] [arch]` | **Kiểm thử toàn sản phẩm theo role + hội đồng chuyên gia**: bản đồ mọi màn/API/role, qa test vùng × role trên staging (đúng quyền, bị chặn đúng quyền, xác minh lỗi đã sửa), rồi UI/UX designer (cả mức sẵn sàng production: design system, icon, asset, minh hoạ, nhận diện app), Product, Engineering cùng đọc bằng chứng và thêm góc nhìn; checklist có bằng chứng và mức độ, bạn chọn mục → ticket ở **Backlog** dưới issue checklist cha, có Sức khoẻ + Bản đồ phủ để lượt sau phủ tiếp vùng chưa test, test lại vùng vừa đổi, báo tái phát. `--focus`, `--areas N\|all`, `--max N` |
| `/agentflow:status` | Đếm theo stage, việc chờ người, bất thường. `--metrics`: cycle time, first-pass yield, số lần fail, aging, token + phút agent mỗi ticket/bước (`agentflow-metrics`) + thống kê journal |
| `/agentflow:doctor` | Kiểm config, token/scope, board mapping, label, MCP, hook, Figma, Telegram — chỉ cách sửa từng lỗi |
| `/agentflow:learn [bài học]` | Gom journal + bài học → diff nhỏ vào source plugin → bạn duyệt → bump version → validate + unit test |

## Bên trong

| Thành phần | Vai trò |
|---|---|
| `agents/sa.md` · `dev.md` | Hai subagent Opus (model đổi qua `run.models`): SA effort xhigh, DEV effort high. SA `MODE=design`: DoR + thiết kế (`[AF:SA] design`: giải pháp, rủi ro, test case `e2e`/`api`/`tay`), `MODE=review`: `step: code` soát code + flow theo thiết kế + file rủi ro + Kiểm chứng lại trước staging; `step: final` soát phần đổi sau ✅ code + kết quả flow, ✅ thì giao QC người hoặc undraft (lượt chỉ soát phần đổi chạy effort high). DEV code theo thiết kế, viết + chạy flow trên staging, ghi "Lệch thiết kế", bảng AC → code → TC → flow, Kiểm chứng lại vào PR |
| `agents/audit.md` | Subagent Opus của `/agentflow:checklist`, effort high: một lăng kính mỗi lượt (`LENS=qa\|ux\|product\|arch`), mỗi phát hiện có bằng chứng, `fp` ổn định giữa các lần chạy, `role` bị ảnh hưởng, body ticket viết sẵn; hội đồng thêm góc nhìn vào mục của qa (`extends`); kết thúc `RESULT: audit · …` |
| `references/audit-qa.md` · `audit-ux.md` · `audit-product.md` · `audit-arch.md` | Chuẩn chuyên gia của từng lăng kính, agent Audit chỉ đọc file của lăng kính mình (qa đọc thêm `automation.md`, arch đọc thêm `engineering.md`) |
| `references/engineering.md` | Chuẩn kỹ thuật chung của SA và DEV: kiến trúc theo tầng của repo, SOLID, pattern khi cần, KISS/YAGNI/DRY, bảo mật, hiệu năng, test, tự review |
| `bin/agentflow-style` | Soát dòng code mới: hàm thân biểu thức (`=>`), điều kiện `&&`/`||`, ternary bị formatter bẻ dòng. DEV phải sạch trước khi push, SA ❌ mỗi chỗ còn lại. Viết vừa một dòng thì vẫn được; `CLAUDE.md` của repo nói khác thì theo `CLAUDE.md` |
| `references/protocol.md` | Contract chung: stage, label, board call, state block, comment `[AF:…]`, thứ tự ghi, git, token hygiene, journal |
| `references/dispatch.md` | Orchestrator: hàng đợi, bảng hành động, model, song song, no-progress guard |
| `references/design.md` | Figma / design trong repo — chỉ load khi ticket chạm UI |
| `references/clarify.md` | Làm rõ yêu cầu auto · ask: `/agentflow:task`, orchestrator và SA design chỉ đọc khi cần (task luôn đọc; implement chỉ ở chế độ ask) |
| `references/automation.md` | Test case từ yêu cầu + rủi ro, quy ước element id theo nền tảng, cách viết flow (Maestro trước, mobile và web, thao tác như người dùng), chọn flow liên quan, chạy trên staging, phân định fail, ảnh chỉ khi cần, mục Kiểm chứng lại — DEV đọc khi có test case e2e/api |
| `skills/*` | 8 lệnh (`disable-model-invocation` — không tốn context khi không gọi) |
| `hooks/hooks.json` + `scripts/guard.py` · `shellparse.py` | Hook chặn (best-effort, xem §Chạy không cần bạn), kể cả qua lệnh bọc (`bash -c`, `env`, `timeout`, `$(…)`, `xargs`, `eval`, code Python/Node): merge/approve PR, dispatch/rerun/cancel workflow ngoài `agentflow-board` (chỉ staging, workflow khai báo; SA không được), force-push, xoá nhánh remote, xoá repo/package, push nhánh protected/base, đọc/sửa/in path `forbidden`, token trong tham số. Thêm luật theo role: SA chỉ đọc (không sửa file, không push, không đổi git); Audit chỉ đọc như SA, thêm: không ghi gì lên GitHub (MCP chỉ `get_*`/`list_*`/`search_*`/`*_read`, `gh` chỉ list/view, board chỉ đọc), ghi nháp chỉ trong `af-audit` hoặc ngoài repo; DEV chỉ ghi trong worktree `af-<n>` và worktree staging `af-<n>-staging`, không tạo/gắn nhánh local (`switch`, `checkout -b`, `worktree add -b`), push staging chỉ từ worktree staging và worktree đó chỉ push vào staging, không đưa staging vào nhánh ticket (merge, reset, restore, push `origin/staging:<nhánh>`), không `update-ref`/`read-tree`/`git branch` ghi, không `pull` ngoài worktree, không undraft |
| `scripts/result-check.py` | Hook `SubagentStop`: subagent phải kết thúc bằng khối `RESULT` (Audit: stage `audit`) |
| `bin/agentflow-board` | Setup + chẩn đoán qua GraphQL (Status option, field, view, label, issue type, doctor, metrics) + đọc check pipeline staging + gom góp ý của người trên PR (`feedback`) + milestone mở cho `/agentflow:task` (`milestones`) + workflow trên staging (`dispatch`, `rerun`, `cancel`) + issue cha làm chung (`group`, `group-sync`) + cổng trước review của DEV (`precheck`: draft, base, conflict, link issue, checklist AC, mục bắt buộc + PR template của repo, mọi TC e2e/api của thiết kế, dòng Đỏ trước) + chuyển field Platform sang label (`platform-migrate`) |
| `bin/agentflow-audit` | Bằng chứng rẻ, lặp lại được cho Audit: `scan` (radar kiến trúc: kích thước, file lớn, hotspot commit × dòng, cặp file đổi cùng nhau khác thư mục, vòng phụ thuộc + cạnh nên cắt, import ngược tầng, khối trùng, TODO, smell) · `flows` (kiểm kê + soát độ vững flow Maestro và spec Playwright/Cypress/Flutter, id flow dùng mà code không còn) · `map` (kiểm kê màn/route, endpoint + gợi ý thiếu kiểm quyền, role, tài khoản test theo tên key, vùng của bản đồ phủ) · `ready` (mức sẵn sàng production: dấu vết prototype, design system, icon, asset, nhận diện app, font, chữ, state, tracking, theo vùng) · `plan` (vùng nên test lượt này: xác minh sửa → vừa đổi → chưa test → lâu nhất) · `ledger` (markdown Sức khoẻ + Bản đồ phủ cho issue checklist) · `findings` (kiểm dạng + nhập góc nhìn `extends` của hội đồng + gộp + xếp file phát hiện + kiểm mức ux chấm khớp mục dẫn ra, `--body` in body ticket). Không đọc path `forbidden`, tài khoản test chỉ đọc tên key |
| `bin/agentflow-base` | Worktree ticket tính từ remote base: `worktree <n> --branch B` (tạo/cập nhật worktree ticket detached từ `origin/B` hoặc `origin/<base>` vừa fetch, việc chưa bắt đầu thì dời lên base mới, giữ phần dở, fast-forward/merge khi có người push vào nhánh, từ chối bỏ việc chưa push của nhánh khác, init submodule) ; `--sync-base` merge `origin/<base>` khi base đã đi tiếp, conflict để DEV giải) · `drift --branch B --since <sha>` (chỉ đọc ref origin: base đi bao nhiêu commit, file hai bên cùng đổi, file sẽ conflict, file base đổi từ lúc SA thiết kế) · `clean` (orchestrator dọn worktree, không bao giờ xoá commit chưa push) · `audit` (worktree `af-audit` cho `/agentflow:checklist`, đặt lại về `origin/<base>` mỗi lần, giữ deps đã cài) |
| `bin/agentflow-e2e` | `select`: flow có sẵn cần chạy lại cho một thay đổi + lý do (SA lúc thiết kế, DEV khi diff lệch thiết kế) · `run`: chạy flow Maestro tách khỏi shell của agent (lặp, nhiều thiết bị, `--env-file` không lộ giá trị; `--install` build + cài app khi thiết bị chưa có đúng bản; `--baseline` chạy flow mới trên bản chưa có thay đổi — staging hiện tại hoặc bản đang cài — để chứng minh flow đỏ trước khi xanh, tự bỏ qua khi bản đó đã có commit của ticket; mỗi thiết bị một ticket một lúc, lượt sau báo `queued`) · `wait`: chờ ≤ 160 giây rồi in một dòng JSON (flow fail + bước + log), `--log` cho build chạy tách |
| `bin/agentflow-metrics` | Token-eq (input + 0.1×cache read + 1.25×cache write + 5×output), lượt, đỉnh context, phút agent mỗi ticket và mỗi bước (role/MODE), số lần SA review — đọc transcript Claude Code trên máy, không gửi đi đâu; dùng để đo trước/sau khi đổi plugin |
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
3. `/agentflow:learn` → ≤ 5 bài học, mỗi bài một diff nhỏ vào đúng file (có trần ký tự để prompt không phình), gate theo `DESIGN-NOTES.md` §Non-goals, bạn duyệt → bump → `claude plugin validate` + unit test.

## Phát triển

Phát triển plugin: [`CONTRIBUTING.md`](CONTRIBUTING.md). Lý do thiết kế: [`DESIGN-NOTES.md`](DESIGN-NOTES.md). Dữ liệu đi đâu: [Privacy](PRIVACY.md).
