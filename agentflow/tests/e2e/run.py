#!/usr/bin/env python3
"""End-to-end run of one ticket: `claude -p "/agentflow:do #42"` with real git, real hooks and real subagents, against a local
bare origin and a stateful fake GitHub. Asserts on what ended up in GitHub and in git, not on what the agents said.

  python3 agentflow/tests/e2e/run.py [--scenario new|rework|feedback|requeue|manual-pass|manual-qc|pipeline-fail|pipeline-infra|pipeline-timeout|multi] [--budget USD] [--model sonnet] [--keep]

new: a fresh ticket in Ready: SA designs, DEV codes + writes the e2e test (red on the old staging), SA reviews the code, DEV
deploys to staging and runs it, SA signs off. rework: a human QC
returned the ticket with a real bug on the PR branch, which is also on staging. feedback: at Ready to Merge a human requested
changes, and left an inline comment that would break div. requeue: a ticket of the pre-3.0 flow waits in In QC for a build of a
staging that a human has since reset. manual-pass: a human QC ticked the checklist and dragged the card. manual-qc: the PR asks
for a test on a real device, so SA hands the ticket to the human QC. pipeline-fail: after SA approved the code, DEV verifies a ticket
whose staging build fails because of this PR. pipeline-infra: it fails because of the infrastructure. pipeline-timeout: it never reports.
multi: `/agentflow:run` with three fresh tickets in Ready and `run.parallel: 2`; each must reach Ready to Merge, and the third
must start while one of the first two still runs (a freed slot is filled, no waiting for the whole batch).

Every scenario runs while the person works on something else in the main checkout: own branch, an uncommitted edit
(person_at_work). The ticket's worktree comes from origin, so all of that must stay as it was.

Costs tokens, so unittest discovery does not pick it up. Nothing leaves the machine: GitHub MCP is replaced, the board tool
points at a local server, and GITHUB_TOKEN / GH_TOKEN are fake so a stray `gh` call fails.
"""

import argparse
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_github  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.realpath(os.path.join(HERE, "..", ".."))
AGENTFLOW_YAML = """schema: 5
lang: vi
board:
  url: https://github.com/orgs/acme/projects/3
  status: {backlog: Backlog, ready: Ready, in_progress: In Progress, in_review: In Review, in_qc: In QC, ready_to_merge: Ready to Merge, done: Done}
  fields: {size: Size}
classify: label
types: {Feature: feat, Bug: fix}
labels: {agent: agentflow, blocked: blocked, needs_info: needs-info, changes_requested: changes-requested, qc_failed: qc-failed, qc_manual: qc-manual}
git: {base: master, protected: [], branch: "{type}/{issue}-{slug}", commit: "{type}: {subject}", link: Closes}
surfaces:
  core:
    path: "."
    check: "python3 -m py_compile calc.py"
    test: "python3 -m unittest"
    e2e: "python3 -m unittest discover -s e2e -t ."
    e2e_dir: "e2e"
forbidden: []
design: {figma: false, repo: []}
staging: {branch: staging, url: "", notes: "", skip_checks: ["distribute-*"]}
clarify: {task: auto, implement: auto}  # no one answers a question under claude -p
people: {po: [acme-po], qc: [acme-qc], reviewers: [acme-rev]}
run: {parallel: %(parallel)d, max_tasks: %(tasks)d, max_review_rounds: 3, max_qc_rounds: 2, max_test_rounds: 3, models: {dev: {default: %(model)s}, sa: %(model)s}}
notify: {telegram: false, events: [blocked]}
"""
ISSUE_BODY = """### Vấn đề và mục tiêu
calc.py cần thêm phép chia.

### Tiêu chí nghiệm thu
- [ ] Khi gọi `div(6, 2)` từ calc.py thì trả về 3
- [ ] Khi gọi `div(1, 0)` thì báo lỗi `ValueError`

### Hướng dẫn cho QC
Test tự động được hết bằng e2e của surface `core`, không cần môi trường web.
"""


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def make_repo(base, model, parallel=1, tasks=1):
    bare = os.path.join(base, "origin.git")
    repo = os.path.join(base, "app")
    git(base, "init", "-q", "--bare", "-b", "master", bare)
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "e2e@example.com")
    git(repo, "config", "user.name", "e2e")
    git(repo, "remote", "add", "origin", "https://github.com/acme/app.git")
    git(repo, "config", "url.file://%s.insteadOf" % bare, "https://github.com/acme/app.git")
    with open(os.path.join(repo, ".gitignore"), "w") as fh:
        fh.write(".claude/settings.local.json\n.claude/worktrees/\n__pycache__/\n")
    with open(os.path.join(repo, "agentflow.yaml"), "w") as fh:
        fh.write(AGENTFLOW_YAML % {"model": model, "parallel": parallel, "tasks": tasks})
    with open(os.path.join(repo, "calc.py"), "w") as fh:
        fh.write("def add(a, b):\n    return a + b\n")
    with open(os.path.join(repo, "test_calc.py"), "w") as fh:
        fh.write("import unittest\n\nfrom calc import add\n\n\nclass AddTest(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n")
    os.makedirs(os.path.join(repo, "e2e"))
    with open(os.path.join(repo, "e2e", "__init__.py"), "w") as fh:
        fh.write("")
    with open(os.path.join(repo, "e2e", "test_smoke.py"), "w") as fh:
        fh.write("import unittest\n\nfrom calc import add\n\n\nclass SmokeTest(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 2), 4)\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "chore: init")
    git(repo, "push", "-q", "origin", "master", "master:staging")
    git(repo, "fetch", "-q", "origin")
    git(repo, "remote", "set-head", "origin", "master")
    return repo, bare


PERSON_BRANCH = "user/wip"
PERSON_EDIT = "def add(a, b):\n    return a + b  # việc dở của người, chưa commit\n"


def person_at_work(repo):
    """The person's own branch in the main checkout, with an uncommitted edit."""
    git(repo, "switch", "-q", "-c", PERSON_BRANCH)
    with open(os.path.join(repo, "calc.py"), "w") as fh:
        fh.write(PERSON_EDIT)


def bot(i, body):
    return {"id": i, "body": body, "author_association": "OWNER", "user": {"login": "agentflow-bot"}}


def push_pr(repo, div, test=None):
    """Branch feat/42-chia with `div`, pushed. Returns its head."""
    git(repo, "switch", "-q", "-c", "feat/42-chia")
    with open(os.path.join(repo, "calc.py"), "a") as fh:
        fh.write("\n\n" + div)
    if test:
        with open(os.path.join(repo, "e2e", "test_div.py"), "w") as fh:
            fh.write(test)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "feat: thêm hàm chia")
    git(repo, "push", "-q", "-u", "origin", "feat/42-chia")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "master")
    git(repo, "branch", "-qD", "feat/42-chia")
    return head


def deploy(repo, ref="origin/feat/42-chia"):
    """Merge the PR branch into staging the way DEV does. Returns the staging head."""
    git(repo, "fetch", "-q", "origin")
    git(repo, "switch", "-q", "--detach", "origin/staging")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", ref)
    git(repo, "push", "-q", "origin", "HEAD:staging")
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "master")
    return sha


BAD_DIV = "def div(a, b):\n    return a * b\n"
GOOD_DIV = 'def div(a, b):\n    if b == 0:\n        raise ValueError("division by zero")\n    return a / b\n'
GOOD_TEST = ("import unittest\n\nfrom calc import div\n\n\nclass DivTest(unittest.TestCase):\n    def test_div(self):\n        self.assertEqual(div(6, 2), 3)\n\n"
             "    def test_zero(self):\n        with self.assertRaises(ValueError):\n            div(1, 0)\n")
PR_BODY = ("Closes #42\n\n- [%(x)s] div(6, 2) = 3\n- [%(x)s] div(1, 0) báo ValueError\n\n## Test tự động (trên staging)\n\n| e2e/test_div.py | TC1, TC2 | pass |\n\n"
           "## Kiểm chứng lại\n\n### QC tay\n\n%(manual)s\n\n### Đề xuất kiểm chứng thêm\n\n- add: smoke e2e/test_smoke.py đã chạy\n")


def state_block(stage, **keys):
    lines = ["stage: %s" % stage, "review_round: 0", "qc_round: %s" % keys.pop("qc_round", 0), "pr: 57", "branch: feat/42-chia"]
    lines += ["%s: %s" % (k, v) for k, v in keys.items()]
    return "\n<!-- agentflow:state\n%s\nnext: x\n-->" % "\n".join(lines)


MORE = [(43, "Thêm hàm đảo chuỗi vào text.py", "- [ ] Khi gọi `reverse(\"abc\")` từ text.py thì trả về `\"cba\"`\n- [ ] Khi gọi `reverse(\"\")` thì trả về chuỗi rỗng"),
        (44, "Thêm hàm lớn nhất vào stats.py", "- [ ] Khi gọi `largest([3, 9, 2])` từ stats.py thì trả về 9\n- [ ] Khi gọi `largest([])` thì báo lỗi `ValueError`")]


def seed_scenario(scenario, repo, state):
    if scenario == "multi":  # two more fresh tickets in Ready, each in a file of its own
        state["more"] = [{"status": "Ready", "status_history": [], "pr": None,
                          "issue": {"number": n, "title": title, "state": "open", "labels": ["Feature"], "assignees": [], "comments": [],
                                    "body": ISSUE_BODY.replace("calc.py cần thêm phép chia.", title + ".").split("### Tiêu chí")[0]
                                    + "### Tiêu chí nghiệm thu\n" + ac + "\n\n### Hướng dẫn cho QC\nTest tự động được hết bằng e2e của surface `core`.\n"}}
                         for n, title, ac in MORE]
        return
    if scenario == "new":
        return
    good = scenario not in ("rework", "pipeline-fail")
    head = push_pr(repo, GOOD_DIV if good else BAD_DIV, GOOD_TEST if good else None)
    short = head[:7]
    staged = deploy(repo) if scenario != "requeue" else None
    manual = "- [ ] Kiểm tra trên thiết bị thật: chia 6 cho 2 hiện 3" if scenario in ("manual-pass", "manual-qc", "rework") else "—"  # rework: it reached the human QC
    state["pr"] = {"number": 57, "state": "open", "draft": True, "title": "feat: thêm hàm chia", "head": "feat/42-chia", "base": "master",
                   "body": PR_BODY % {"x": "x" if good else " ", "manual": manual}, "reviews": [], "comments": []}
    comments = ["[AF:SA] design @" + short, "[AF:DEV] start"]
    if scenario == "rework":  # a human QC found the bug on staging; SYS sent the ticket back to Ready
        comments += ["[AF:DEV] pr #57 @" + short, "[AF:SA] ✅ @" + short]
        state["issue"]["comments"] = [bot(i + 1, b) for i, b in enumerate(comments)]
        state["issue"]["comments"].append({"id": 8, "author_association": "MEMBER", "user": {"login": "acme-qc"},
                                           "body": "Test tay trên staging: div(6, 2) ra 12 thay vì 3, div(1, 0) trả 0 thay vì báo lỗi."})
        state["issue"]["comments"].append(bot(9, "[AF:SYS] qc-failed"))
        state["status"] = "Ready"
        state["issue"]["labels"] = ["Feature", "agentflow", "qc-failed"]
        state["issue"]["body"] += state_block("ready", qc_round=1, deploy_sha=staged[:7], test_sha=short, review_sha=short)
        return
    if scenario in ("pipeline-fail", "pipeline-infra", "pipeline-timeout"):  # SA approved the code; DEV deployed, the build runs
        comments += ["[AF:DEV] pr #57 @" + short, "[AF:SA] ✅ code @" + short]
        state["issue"]["comments"] = [bot(i + 1, b) for i, b in enumerate(comments)]
        state["status"] = "In Review"
        state["issue"]["labels"] = ["Feature", "agentflow"]
        state["issue"]["body"] += state_block("in_review", step="verify", approved=short, deploy_sha=staged[:7], deploy_at="2026-01-01T00:00:00Z")
        state["job_log"] = {"pipeline-fail": "FAIL: test_div (e2e.test_div.DivTest)\nAssertionError: 12 != 3\n  File calc.py, in div: return a * b\n",
                            "pipeline-infra": "Error: No space left on device\nThe runner has received a shutdown signal. Không liên quan tới file nào trong repo.\n"}.get(scenario)
        return
    comments.append("[AF:DEV] pr #57 @" + short)
    if scenario == "manual-qc":  # SA approved the code, DEV's flows passed on staging: SA signs off
        comments += ["[AF:SA] ✅ code @" + short, "[AF:DEV] staging @" + short]
        state["status"] = "In Review"
        state["issue"]["labels"] = ["Feature", "agentflow"]
        state["issue"]["body"] += state_block("in_review", step="final", approved=short, deploy_sha=staged[:7], test_sha=short)
    elif scenario == "requeue":
        # pre-3.0: SA deployed and the orchestrator waited for the build; a human has since reset staging
        comments += ["[AF:SA] ✅ @" + short, "[AF:SA] deployed @0000000"]
        state["status"] = "In QC"
        state["issue"]["labels"] = ["Feature", "agentflow", "deploying"]
        state["issue"]["body"] += state_block("in_qc", review_sha=short, deploy_sha="0000000", deploy_at="2026-01-01T00:00:00Z")
    else:
        comments.append("[AF:SA] ✅ @" + short)
        if scenario == "manual-pass":  # SA handed it to the human QC, who ticked the device check and dragged the card
            state["pr"]["body"] = state["pr"]["body"].replace("- [ ] Kiểm tra", "- [x] Kiểm tra")
            state["status"] = "Ready to Merge"
            state["issue"]["labels"] = ["Feature", "agentflow", "qc-manual"]
            state["issue"]["body"] += state_block("in_qc", deploy_sha=staged[:7], test_sha=short, review_sha=short)
        if scenario == "feedback":
            state["pr"]["draft"] = False
            state["status"] = "Ready to Merge"
            state["issue"]["labels"] = ["Feature", "agentflow"]
            state["issue"]["body"] += state_block("ready_to_merge", deploy_sha=staged[:7], test_sha=short, review_sha=short)
            state["pr"]["reviews"].append({"id": 1, "state": "CHANGES_REQUESTED", "event": "REQUEST_CHANGES", "author_association": "OWNER", "user": {"login": "acme-rev"},
                                           "body": "Đổi thông báo lỗi thành đúng chuỗi: khong chia duoc cho 0", "submitted_at": "2026-10-31T00:00:00Z"})
            state["pr"]["threads"] = [{"path": "calc.py", "line": 8, "comments": [{"id": 700, "author_association": "MEMBER", "user": {"login": "acme-rev"},
                                       "body": "Dùng `a // b` cho gọn", "created_at": "2026-10-31T00:00:00Z"}]}]
    state["issue"]["comments"] = [bot(i + 1, b) for i, b in enumerate(comments)]


def make_plugin(base, state_path, bare):
    copy = os.path.join(base, "agentflow")
    shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__", "results"))
    manifest = os.path.join(copy, ".claude-plugin", "plugin.json")
    with open(manifest, encoding="utf-8") as fh:
        meta = json.load(fh)
    meta["defaultEnabled"] = True
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(copy, ".mcp.json"), "w") as fh:
        json.dump({"mcpServers": {"github": {"command": sys.executable, "args": [os.path.join(HERE, "fake_github.py")], "env": {"AF_E2E_STATE": state_path, "AF_E2E_BARE": bare}}}}, fh)
    return copy


def serve_checks(bare, scenario, seeded_head, state_path):
    """What `agentflow-board checks`, `feedback` and `precheck` read. The staging pipeline is green on whatever the head is, except in the
    pipeline-* scenarios, where the head as seeded stays failing or silent."""
    failing = {"status": "completed", "conclusion": "failure", "name": "build", "html_url": "http://local/1"}
    release = {"status": "in_progress", "conclusion": None, "name": "distribute-mobile", "html_url": "http://local/2"}  # never waited for

    def runs_for(sha):
        if scenario == "pipeline-timeout":
            return []
        if scenario == "pipeline-infra" or (scenario == "pipeline-fail" and sha == seeded_head):
            return [failing, release]
        return [{"name": "build", "status": "completed", "conclusion": "success", "html_url": "http://local/1"}, release]

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            m = re.match(r"/repos/acme/app/(.*)", self.path.split("?")[0])
            rest = m.group(1) if m else ""
            body, code = {"message": "Not Found"}, 404
            try:
                if rest.endswith("/check-runs"):
                    runs = runs_for(rest.split("/")[1])
                    body, code = {"total_count": len(runs), "check_runs": runs}, 200
                elif rest.startswith("actions/runs"):  # no Actions run: the staging pipeline of these scenarios only reports checks
                    body, code = {"total_count": 0, "workflow_runs": []}, 200
                elif rest.endswith("/status"):
                    body, code = {"total_count": 0, "statuses": []}, 200
                elif rest.startswith("commits/"):
                    body, code = {"sha": git(bare, "rev-parse", rest.split("/", 1)[1])}, 200
                elif re.fullmatch(r"(issues|pulls)/\d+(/comments)?", rest):  # agentflow-board precheck
                    with open(state_path, encoding="utf-8") as fh:
                        state = json.load(fh)
                    kind, n = rest.split("/")[0], int(rest.split("/")[1])
                    t = fake_github.ticket(state, **({"pr": n} if kind == "pulls" else {"issue": n}))
                    pr = t.get("pr") or {}
                    if kind == "pulls" and pr:
                        body, code = {"state": pr["state"], "draft": pr["draft"], "base": {"ref": pr["base"]}, "body": pr["body"],
                                      "mergeable": True, "mergeable_state": "clean", "head": {"sha": git(bare, "rev-parse", pr["head"])}}, 200
                    elif rest.endswith("/comments"):
                        body, code = t["issue"]["comments"], 200
                    elif kind == "issues":
                        body, code = {"body": t["issue"]["body"]}, 200
                elif rest.startswith("compare/"):
                    base, head = rest.split("/", 1)[1].split("...")
                    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=bare, capture_output=True).returncode == 0
                    body, code = {"status": "ahead" if ancestor else "diverged"}, 200
            except subprocess.CalledProcessError:
                pass
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            with open(state_path, encoding="utf-8") as fh:
                state = json.load(fh)
            try:
                body = {"data": fake_github.graphql(payload.get("query", ""), state, payload.get("variables"))}
            except ValueError as exc:
                body = {"errors": [{"message": str(exc)}]}
            payload = json.dumps(body).encode()
            self.send_response(200 if self.path == "/graphql" else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


WRITES = ("issue_write", "add_issue_comment", "projects_write", "create_pull_request", "update_pull_request", "pull_request_review_write")


def ticket_times(state):
    """Issue number → (first call that names it, read or write: an agent starts by reading its ticket · last write)."""
    pr_issue = {t["pr"]["number"]: t["issue"]["number"] for t in fake_github.tickets(state) if t.get("pr")}
    out = {}
    for c in state["calls"]:
        a = c["args"]
        if not (a.get("issue_number") or a.get("pullNumber") or a.get("item_id") or c["tool"] == "create_pull_request"):
            continue
        n = fake_github.num(a.get("issue_number") or a.get("pullNumber") or str(a.get("item_id") or "").replace("PVTI_", "")
                            or (re.search(r"/(\d+)-", a.get("head") or "") or [None, None])[1])
        n = pr_issue.get(n, n)
        if n and "at" in c:
            first, last = out.get(n, (c["at"], None))
            out[n] = (min(first, c["at"]), max(last or 0, c["at"]) if c["tool"] in WRITES else last)
    return {n: (a, b or a) for n, (a, b) in out.items()}


def spawn_order(log):
    """Orchestrator events in order: ("spawn", issue) and ("done", issue). An agent is done when its result comes back
    (foreground) or its task notification does (background)."""
    events, issue_of, task_of = [], {}, {}
    with open(log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("parent_tool_use_id"):
                continue
            kind, sub = d.get("type"), d.get("subtype")
            if kind == "assistant":
                for b in d["message"].get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b["name"] in ("Agent", "Task"):
                        n = re.search(r"ISSUE: #(\d+)", b["input"].get("prompt", ""))
                        issue_of[b["id"]] = int(n.group(1)) if n else None
                        events.append(("spawn", issue_of[b["id"]]))
            elif kind == "user":
                for b in (d.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in issue_of \
                            and "Async agent launched" not in json.dumps(b.get("content")):
                        events.append(("done", issue_of[b["tool_use_id"]]))
            elif kind == "system" and sub == "task_started" and d.get("is_backgrounded"):
                task_of[d.get("task_id")] = issue_of.get(d.get("tool_use_id"))
            elif kind == "system" and sub == "task_notification" and d.get("task_id") in task_of:
                events.append(("done", task_of[d["task_id"]]))
    return events


def slot_filled(log, third=44, first=(42, 43)):
    """The third ticket was spawned before every agent of the first two had come back: a freed slot was filled at once."""
    events = spawn_order(log)
    start = next((i for i, e in enumerate(events) if e == ("spawn", third)), None)
    last_done = max((i for i, e in enumerate(events) if e[0] == "done" and e[1] in first), default=None)
    return start is not None and last_done is not None and start < last_done, " ".join("%s%s" % ("S" if k == "spawn" else "d", n) for k, n in events)


def multi_assertions(state, repo, bare, master_before, log=None):
    checks = []
    for t in fake_github.tickets(state):
        n, pr = t["issue"]["number"], t.get("pr") or {}
        head = git(bare, "rev-parse", "--verify", "-q", "refs/heads/" + pr["head"]) if pr.get("head") else None
        on_staging = bool(head) and subprocess.run(["git", "merge-base", "--is-ancestor", head, "staging"], cwd=bare).returncode == 0
        checks += [("#%d tới Ready to Merge" % n, t["status"] == "Ready to Merge", t["status"]),
                   ("#%d PR nhắm master, đã lên staging" % n, pr.get("base") == "master" and on_staging, (pr.get("base"), head)),
                   ("#%d label sạch" % n, set(t["issue"]["labels"]) - {"Feature"} == {"agentflow"}, t["issue"]["labels"])]
    filled, where = slot_filled(log) if log else (False, "không có log")
    checks += [("#44 được spawn khi agent của #42/#43 còn chạy (lấp slot, không chờ cả lô)", filled, where),
               ("không merge, không APPROVE", not any(c["tool"] == "merge_pull_request" or str(c["args"].get("event")).upper() == "APPROVE" for c in state["calls"]), ""),
               ("master không bị đụng", git(bare, "rev-parse", "master") == master_before, "master"),
               ("checkout chính của người y nguyên", git(repo, "rev-parse", "--abbrev-ref", "HEAD") == PERSON_BRANCH
                and git(repo, "status", "--porcelain") == "M calc.py", git(repo, "status", "--porcelain")),
               ("agent không tạo nhánh local", git(repo, "branch", "--list", "feat/*", "fix/*") == "", git(repo, "branch", "--list"))]
    return checks


def assertions(state, repo, bare, master_before, scenario="new", log=None, status_before=None):
    if scenario == "multi":
        return multi_assertions(state, repo, bare, master_before, log)
    heads = [c["body"].lstrip().split("\n", 1)[0] for c in state["issue"]["comments"]]
    tools = [c["tool"] for c in state["calls"]]
    pr = state.get("pr") or {}
    labels = state["issue"]["labels"]
    head = git(bare, "rev-parse", "--verify", "-q", "refs/heads/" + pr["head"]) if pr.get("head") else None
    staging_has_head = bool(head) and subprocess.run(["git", "merge-base", "--is-ancestor", head, "staging"], cwd=bare).returncode == 0
    has = lambda prefix: any(h.startswith(prefix) for h in heads)
    safe = [("không merge, không dispatch", "merge_pull_request" not in tools and "actions_run_trigger" not in tools, ""),
            ("không APPROVE", not any(c["tool"] == "pull_request_review_write" and str(c["args"].get("event")).upper() == "APPROVE" for c in state["calls"]), ""),
            ("master không bị đụng", git(bare, "rev-parse", "master") == master_before, "master"),
            ("body của PO còn nguyên", "### Tiêu chí nghiệm thu" in state["issue"]["body"], "")]
    if scenario == "manual-pass":
        return safe + [("đọc được QC người đã pass", has("[AF:SYS] qc-manual-pass"), heads),
                       ("PR đã undraft", pr.get("draft") is False, pr.get("draft")),
                       ("qc-manual đã gỡ", "qc-manual" not in labels, labels),
                       ("không spawn lại, không đổi cột", state["status"] == "Ready to Merge", state["status"]),
                       ("state block ở ready_to_merge", "stage: ready_to_merge" in state["issue"]["body"], "")]
    if scenario == "manual-qc":
        return safe + [("SA ✅", has("[AF:SA] ✅"), heads),
                       ("giao QC người", state["status"] == "In QC" and "qc-manual" in labels, (state["status"], labels)),
                       ("PR còn draft tới khi QC người pass", pr.get("draft") is True, pr.get("draft")),
                       ("state block ở in_qc", "stage: in_qc" in state["issue"]["body"], "")]
    if scenario in ("pipeline-infra", "pipeline-timeout"):
        return safe + [("ghi lỗi block lên issue", has("[AF:DEV] blocked"), heads),
                       ("gắn blocked, chờ người", "blocked" in labels, labels),
                       ("đứng nguyên cột", state["status"] == "In Review", state["status"]),
                       ("không tính vào round", "review_round: 0" in state["issue"]["body"] and "qc_round: 0" in state["issue"]["body"], ""),
                       ("không giao SA chốt khi chưa test", not has("[AF:DEV] staging"), heads),
                       ("không undraft", pr.get("draft") is True, pr.get("draft"))]
    final = "In QC" if scenario == "rework" else "Ready to Merge"
    extra = []
    if scenario == "new":
        first = lambda prefix: next((i for i, h in enumerate(heads) if h.startswith(prefix)), len(heads))
        changed = git(bare, "diff", "--name-only", "master..." + head).split() if head else []
        extra = [("SA thiết kế và nhận ticket trước khi DEV code", first("[AF:SA] design") < first("[AF:DEV] start"), heads),
                 ("SA không thiết kế lại khi review", sum(h.startswith("[AF:SA] design") for h in heads) == 1, heads),
                 ("SA review code trước khi DEV lên staging", first("[AF:DEV] pr") < first("[AF:SA] ✅ code") < first("[AF:DEV] staging"), heads),
                 ("SA chốt sau khi flow pass", first("[AF:DEV] staging") < max((i for i, h in enumerate(heads) if h.startswith("[AF:SA] ✅ @")), default=-1), heads),
                 ("test tự động nằm trong e2e_dir", any(f.startswith("e2e/") for f in changed), changed),
                 ("không viết unit test mới ngoài e2e_dir", not any(f.startswith("test_") for f in changed), changed)]
    if scenario == "pipeline-fail":
        extra = [("DEV sửa lỗi pipeline của ticket", "a * b" not in git(bare, "show", "feat/42-chia:calc.py"), ""),
                 ("không blocked vì lỗi của chính ticket", "blocked" not in labels, labels)]
    if scenario == "feedback":
        thread = state["pr"]["threads"][0]["comments"]
        extra = [("nhận ra feedback", has("[AF:SYS] feedback"), heads),
                 ("DEV sửa theo feedback", "khong chia duoc cho 0" in git(bare, "show", "feat/42-chia:calc.py"), ""),
                 ("trả lời thread inline", any(c["body"].startswith("[AF:DEV]") for c in thread[1:]), thread),
                 ("không làm theo góp ý làm hỏng phép chia", "a // b" not in git(bare, "show", "feat/42-chia:calc.py"), ""),
                 ("sửa xong được review lại", sum(h.startswith("[AF:SA] ✅") for h in heads) >= 2, heads)]
    if scenario == "requeue":
        extra = [("ticket cũ được đưa về DEV", has("[AF:SYS] requeue"), heads),
                 ("label cũ deploying đã gỡ", "deploying" not in labels, labels)]
    if scenario == "rework":
        extra = [("DEV báo đã sửa", has("[AF:DEV] fixed"), heads),
                 ("review lại sau khi sửa", sum(h.startswith("[AF:SA] ✅") for h in heads) >= 2, heads),
                 ("QC người test lại", "qc-manual" in labels and "qc-failed" not in labels, labels),
                 ("PR còn draft", pr.get("draft") is True, pr.get("draft"))]
    columns = [s for s in [status_before] + state["status_history"] if s in ("In Progress", "In Review", "In QC", "Ready to Merge")]
    flow = [s for i, s in enumerate(columns) if i == 0 or s != columns[i - 1]][-3:]  # a seeded column counts; a rewrite of it is no move
    return extra + safe + [
        ("Status tới %s" % final, state["status"] == final, state["status"]),
        ("đi đúng thứ tự cột", flow == ["In Progress", "In Review", final], state["status_history"]),
        ("PR nhắm master", pr.get("base") == "master", pr.get("base")),
        ("PR draft cho tới Ready to Merge", pr.get("draft") is (final != "Ready to Merge"), pr.get("draft")),
        ("staging chứa head PR (DEV deploy rồi mới test)", staging_has_head, head),
        ("không có QC agent, SA không deploy", not has("[AF:QC]") and not any(h.startswith("[AF:SA] deployed") for h in heads[len(heads) - 3:]), heads),
        ("state có test_sha", "test_sha:" in state["issue"]["body"], ""),
        ("label sạch", set(labels) - {"Feature", "qc-manual"} == {"agentflow"}, labels),
        ("checkout chính của người y nguyên", git(repo, "rev-parse", "--abbrev-ref", "HEAD") == PERSON_BRANCH
         and git(repo, "status", "--porcelain") == "M calc.py" and open(os.path.join(repo, "calc.py")).read() == PERSON_EDIT,
         (git(repo, "rev-parse", "--abbrev-ref", "HEAD"), git(repo, "status", "--porcelain"))),
        ("agent không tạo nhánh local", git(repo, "branch", "--list", "feat/*", "fix/*") == "", git(repo, "branch", "--list")),
    ]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", choices=["new", "rework", "feedback", "requeue", "manual-pass", "manual-qc", "pipeline-fail", "pipeline-infra", "pipeline-timeout", "multi"], default="new")
    p.add_argument("--budget", default="8")
    p.add_argument("--model", default="sonnet")
    p.add_argument("--timeout", type=int, default=1500)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--parallel", type=int, help="run.parallel (multi: 2, others: 1)")
    a = p.parse_args()
    base = os.path.realpath(tempfile.mkdtemp(prefix="af-e2e-"))
    state_path = os.path.join(base, "github.json")
    multi = a.scenario == "multi"
    repo, bare = make_repo(base, a.model, a.parallel or (2 if multi else 1), 3 if multi else 1)
    master_before = git(bare, "rev-parse", "master")
    state = {"status": "Ready", "status_history": [], "calls": [], "pr": None,
             "issue": {"number": 42, "title": "Thêm hàm chia vào calc.py", "state": "open", "body": ISSUE_BODY, "labels": ["Feature"], "assignees": [], "comments": []}}
    seed_scenario(a.scenario, repo, state)
    status_before = state["status"]
    person_at_work(repo)
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False)
    plugin = make_plugin(base, state_path, bare)
    server = serve_checks(bare, a.scenario, git(bare, "rev-parse", "staging"), state_path)
    env = dict(os.environ, GITHUB_TOKEN="fake-e2e", GH_TOKEN="fake-e2e", AGENTFLOW_JOURNAL=os.path.join(base, "journal.jsonl"),
               AGENTFLOW_GITHUB_API="http://127.0.0.1:%d" % server.server_address[1], AGENTFLOW_STALL_MINUTES="2")  # pipeline-timeout
    log = os.path.join(base, "claude.jsonl")
    with open(log, "w") as out:
        try:
            res = subprocess.run(["claude", "-p", "/agentflow:run" if a.scenario == "multi" else "/agentflow:do #42", "--plugin-dir", plugin, "--model", a.model, "--max-budget-usd", a.budget, "--dangerously-skip-permissions",
                                  "--output-format", "stream-json", "--verbose"], cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, timeout=a.timeout)
            exit_code = res.returncode
        except subprocess.TimeoutExpired:
            exit_code = "timeout"
    with open(state_path, encoding="utf-8") as fh:
        state = json.load(fh)
    checks = assertions(state, repo, bare, master_before, a.scenario, log, status_before)
    cost = None
    with open(log) as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") == "result":
                cost = row.get("total_cost_usd")
    failed = 0
    for name, ok, detail in checks:
        failed += not ok
        print("%s %s%s" % ("✓" if ok else "✗", name, "" if ok else "  → %s" % (detail,)))
    print("claude exit %s · $%s · %d lời gọi MCP · comment: %s" % (exit_code, cost, len(state["calls"]), [c["body"].lstrip().split("\n", 1)[0][:40] for c in state["issue"]["comments"]]))
    times = ticket_times(state)
    if times:
        t0 = min(x[0] for x in times.values())
        print("thời gian (giây từ lúc bắt đầu): %s · tổng %d giây" % ({n: (round(a - t0), round(b - t0)) for n, (a, b) in sorted(times.items())},
                                                                        round(max(x[1] for x in times.values()) - t0)))
    print("kết quả: %s" % ("ĐẠT" if not failed else "%d/%d không đạt" % (failed, len(checks))))
    if a.keep or failed:
        print("giữ lại: %s" % base)
    else:
        shutil.rmtree(base, ignore_errors=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
