#!/usr/bin/env python3
"""Contract between prompts, config and code. Prompts are the program here: a wrong section number, a renamed label or a
missing subcommand fails at run time in front of a user, unless it fails here first."""

import ast
import glob
import json
import os
import re
import stat
import sys
import unittest

ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import afconfig  # noqa: E402

# Runtime prompts cost tokens on every run. Limits are characters, since one line can hold hundreds of them.
# Do not raise a limit to fit a change: remove something first (CONTRIBUTING.md §Quy ước).
# 3.0 folded the QC agent into DEV: dev.md and automation.md grew, protocol.md and dispatch.md shrank, qc.md is gone.
# 3.5 (SA regression list, DEV verify spawn, detached runs under the 180 s harness cut) added ~1.4k across five files: a
# few hundred tokens a spawn against ~20M tokens of late, full-context test turns per ticket (DESIGN-NOTES.md).
# 3.6 (clarify auto · ask) keeps the mechanics in references/clarify.md, read only by /task, an ask-mode orchestrator and an
# ask-mode SA design: ~0.3k a spawn for the CLARIFY input, the ambiguity rule and the new heads/state key/RESULT value.
# 3.7 (platform labels, DEV dispatch/rerun/cancel on staging) adds ~0.5k to a DEV spawn and ~0.2k to SA: one rerun saves a
# blocked ticket and a human round trip. init/task/board-setup grow by the migration and label steps, read once per repo/ticket.
# 3.8 (a ticket's worktree comes from origin/<base>, never from the main checkout the person keeps switching) moves the worktree
# mechanics into bin/agentflow-base: a DEV spawn costs about the same, the protocol grows by the rule DEV and SA follow.
# 3.8 also adds ~0.25k to a DEV spawn (automation.md): one device per ticket at a time (`run --install`, `queued`) and a rerun
# when another ticket redeployed staging mid-run. Without them parallel DEVs install over each other's build and turn a
# sibling's redeploy into a fix round or a `blocked` ticket. init grows by the info/exclude step, read once per repo.
# engineering.md +0.13k (SA and DEV): the most frequent real review ❌ in the journal (5 of 26, incl. the 4-round #55)
# is a state change that missed another entry/exit path of the flow.
# dispatch.md +0.1k: slots fill only when agents run in the background (a foreground spawn holds the orchestrator until it
# ends). tests/e2e/run.py --scenario multi, 2 runs on 2026-11-24: Claude Code backgrounded 10/11 and 9/9 spawns by itself and
# #44 was spawned as soon as #43 came back while #42 still ran; the flag keeps it so where the default differs.
# 3.9 (/agentflow:checklist) adds files no ticket spawn reads: the command, the audit agent and one reference per lens,
# read only when a person asks for an audit. SA and DEV spawns cost the same as before.
BUDGETS = {
    "agents/sa.md": 10100, "agents/dev.md": 13000,
    "references/protocol.md": 13000, "references/dispatch.md": 9100, "references/design.md": 2600, "references/automation.md": 7100,
    "references/engineering.md": 3000, "references/clarify.md": 6650,
    "skills/init/SKILL.md": 11200, "skills/learn/SKILL.md": 5500, "skills/do/SKILL.md": 2800, "skills/doctor/SKILL.md": 2000,
    "skills/run/SKILL.md": 2400, "skills/status/SKILL.md": 2850, "skills/task/SKILL.md": 9850, "skills/init/references/board-setup.md": 5550,
    "agents/audit.md": 4400, "references/audit-qa.md": 4800, "references/audit-arch.md": 3750, "references/audit-product.md": 2850,
    "skills/checklist/SKILL.md": 6050,
}
# What a spawn reads before it looks at the ticket: its prompt, the protocol and the references it always reads.
# 2.x DEV paid 9.3k + 12.1k + 8.3k (it read the reviewer prompt to self-review); the shared engineering.md replaced that.
# 3.0 happy path: SA design + DEV + SA review ≈ 24k + 33.4k + 24k, where the QC plan + verify spawns cost 2 × 27.7k more.
# The auditor reads one lens a spawn: qa (its reference + automation.md) is the costliest.
SPAWN_READS = {"sa": ["references/engineering.md"], "dev": ["references/engineering.md", "references/automation.md"],
               "audit": ["references/audit-qa.md", "references/automation.md"]}
PER_SPAWN_LIMIT = {"sa": 26050, "dev": 35750, "audit": 29150}
DESCRIPTION_LIMIT = 700


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def frontmatter(rel):
    text = read(rel)
    assert text.startswith("---\n"), rel
    return afconfig.parse_yaml(text.split("---\n", 2)[1])


def prompts():
    out = []
    for pattern in ("agents/*.md", "references/*.md", "skills/*/SKILL.md", "skills/*/references/*.md"):
        out += glob.glob(os.path.join(ROOT, pattern))
    return sorted(os.path.relpath(p, ROOT) for p in out)


def all_docs():
    return prompts() + ["README.md", "CONTRIBUTING.md", "DESIGN-NOTES.md", "PRIVACY.md", "templates/board-readme.md"]


def code_files():
    return [p for p in glob.glob(os.path.join(ROOT, "bin", "*")) + glob.glob(os.path.join(ROOT, "scripts", "*.py")) if os.path.isfile(p)]


def headings(rel):
    return set(re.findall(r"^## (\d+[a-z]?)\.", read(rel), re.M))


TEMPLATE = afconfig.parse_yaml(read("agentflow.yaml"))
AGENTS = ["sa", "dev", "audit"]
SKILLS = ["checklist", "do", "doctor", "init", "learn", "run", "status", "task"]
LENSES = ["qa", "arch", "product"]


class Budget(unittest.TestCase):
    def test_every_prompt_has_a_budget(self):
        self.assertEqual(set(prompts()), set(BUDGETS))

    def test_within_budget(self):
        for rel, limit in BUDGETS.items():
            with self.subTest(rel):
                self.assertLessEqual(len(read(rel)), limit)

    def test_per_spawn_cost(self):
        protocol = len(read("references/protocol.md"))
        for agent in AGENTS:
            with self.subTest(agent):
                for ref in SPAWN_READS[agent]:
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}/%s" % ref, read("agents/%s.md" % agent))
                cost = len(read("agents/%s.md" % agent)) + protocol + sum(len(read(r)) for r in SPAWN_READS[agent])
                self.assertLessEqual(cost, PER_SPAWN_LIMIT[agent])

    def test_skill_files_under_the_platform_limit(self):
        for rel in prompts():
            self.assertLess(read(rel).count("\n"), 500, rel)


class Frontmatter(unittest.TestCase):
    def test_agents(self):
        for name in AGENTS:
            rel = "agents/%s.md" % name
            meta = frontmatter(rel)
            with self.subTest(name):
                self.assertEqual(meta["name"], name)
                self.assertLessEqual(len(meta["description"]), DESCRIPTION_LIMIT)
                self.assertIn(meta["model"], ("opus", "sonnet", "haiku", "fable", "inherit"))
                self.assertIsInstance(meta["maxTurns"], int)
                for ignored in ("hooks", "mcpServers", "permissionMode"):  # plugin agents ignore these: they would give false comfort
                    self.assertNotIn(ignored, meta)

    def test_agents_can_reach_what_their_prompt_uses(self):
        for name in AGENTS:
            tools = [t.strip() for t in frontmatter("agents/%s.md" % name)["tools"].split(",")]
            with self.subTest(name):
                self.assertIn("ToolSearch", tools)  # MCP tools are deferred
                self.assertIn("mcp__plugin_agentflow_github__*", tools)
                self.assertIn("Bash", tools)
                self.assertNotIn("Agent", tools)

    def test_least_privilege(self):
        tools = {n: frontmatter("agents/%s.md" % n)["tools"] for n in AGENTS}
        self.assertNotRegex(tools["sa"], r"\b(Write|Edit)\b")  # SA reads and reviews; DEV deploys and resolves staging conflicts
        self.assertRegex(tools["dev"], r"\bEdit\b")
        self.assertNotRegex(tools["audit"], r"\bEdit\b")  # writes its findings file and scratch flows whole; the guard keeps it out of the repo
        for name in AGENTS:
            self.assertNotIn("mcp__claude-in-chrome__*", tools[name])

    def test_mcp_prefix_matches_the_manifest(self):
        servers = json.loads(read(".mcp.json"))["mcpServers"]
        for name in AGENTS:
            for server in re.findall(r"mcp__plugin_agentflow_(\w+?)__", read("agents/%s.md" % name)):
                self.assertIn(server, servers)

    def test_skills(self):
        self.assertEqual(sorted(os.listdir(os.path.join(ROOT, "skills"))), SKILLS)
        for name in SKILLS:
            meta = frontmatter("skills/%s/SKILL.md" % name)
            with self.subTest(name):
                self.assertEqual(meta["name"], name)
                self.assertIs(meta["disable-model-invocation"], True)
                self.assertLessEqual(len(meta["description"]), DESCRIPTION_LIMIT)

    def test_read_only_skills_preapprove_only_read_commands(self):
        for name in ("status", "doctor"):
            allowed = frontmatter("skills/%s/SKILL.md" % name)["allowed-tools"]
            self.assertNotRegex(allowed, r"status-apply|create|labels|ensure-field|set-secret|Write|Edit")


class Manifest(unittest.TestCase):
    def test_plugin_json(self):
        meta = json.loads(read(".claude-plugin/plugin.json"))
        self.assertRegex(meta["version"], r"^\d+\.\d+\.\d+$")
        self.assertIs(meta["defaultEnabled"], False)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, meta["privacyPolicyUrl"].rsplit("/agentflow/", 1)[1])))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "LICENSE")))

    def test_marketplace_points_here(self):
        market = json.loads(read("../.claude-plugin/marketplace.json"))
        self.assertEqual([(p["name"], p["source"]) for p in market["plugins"]], [("agentflow", "./agentflow")])

    def test_hooks(self):
        hooks = json.loads(read("hooks/hooks.json"))["hooks"]
        pre = hooks["PreToolUse"][0]
        command = pre["hooks"][0]
        self.assertEqual(command["onFailure"], "block")  # a broken guard must not mean no guard
        self.assertIn("-I", command["command"])
        for tool in ("Bash", "Monitor", "Edit", "Write", "NotebookEdit", "Read", "Grep"):
            self.assertRegex(tool, "^(%s)$" % pre["matcher"])
        self.assertRegex("mcp__plugin_agentflow_github__merge_pull_request", "^(%s)$" % pre["matcher"])
        self.assertRegex("agentflow:dev", hooks["SubagentStop"][0]["matcher"])

    def test_every_script_a_hook_or_mcp_config_runs_exists(self):
        for rel in ("hooks/hooks.json", ".mcp.json"):
            for path in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", read(rel)):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)

    def test_bin_is_executable_python_3_9(self):
        for path in code_files():
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            ast.parse(source, filename=path, feature_version=(3, 9))
            if "/bin/" in path:
                self.assertTrue(os.stat(path).st_mode & stat.S_IXUSR, path)
                self.assertTrue(source.startswith("#!/usr/bin/env python3"), path)

    def test_stdlib_only(self):
        allowed = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
        for path in code_files():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in tree.body:  # top-level only: yaml and certifi are optional, imported inside functions
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
                for name in names:
                    root = name.split(".")[0]
                    if allowed is not None and root not in ("afconfig", "shellparse"):
                        self.assertIn(root, allowed, path)


class References(unittest.TestCase):
    def test_plugin_root_paths_exist(self):
        for rel in prompts():
            for path in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+[\w/])", read(rel)):
                with self.subTest("%s → %s" % (rel, path)):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, path)))

    def test_cross_file_sections_exist(self):
        targets = {"protocol": "references/protocol.md", "dispatch": "references/dispatch.md"}
        for rel in all_docs():
            for doc, section in re.findall(r"\b(protocol|dispatch)(?:\.md)? §(\d+[a-z]?)", read(rel)):
                with self.subTest("%s → %s §%s" % (rel, doc, section)):
                    self.assertIn(section, headings(targets[doc]))

    def test_own_sections_exist(self):
        for rel in ["agents/%s.md" % a for a in AGENTS] + ["references/protocol.md", "references/dispatch.md"]:
            text = re.sub(r"\b(protocol|dispatch)(\.md)? §\d+[a-z]?(–§?\d+)?", "", read(rel))
            text = re.sub(r"§[A-ZĐ][\wÀ-ỹ-]*", "", text)
            have = headings(rel)
            for section in re.findall(r"§(\d+[a-z]?)", text):
                with self.subTest("%s §%s" % (rel, section)):
                    self.assertIn(section, have)

    def test_learn_gate_section_exists(self):
        self.assertIn("## Non-goals", read("DESIGN-NOTES.md"))
        self.assertIn("§Non-goals", read("skills/learn/SKILL.md"))

    def test_board_subcommands_exist(self):
        source = read("bin/agentflow-board")
        have = set(re.findall(r'add_parser\("([\w-]+)"\)', source)) | set(re.findall(r'"([\w-]+)":\s*cmd_', source))
        for rel in all_docs():
            for sub in re.findall(r"agentflow-board ([a-z][a-z-]+)", read(rel)):
                with self.subTest("%s: %s" % (rel, sub)):
                    self.assertIn(sub, have)

    def test_board_flags_exist(self):
        source = read("bin/agentflow-board")
        for rel in prompts():
            for line in read(rel).splitlines():
                if "agentflow-board " not in line:
                    continue
                for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", line.split("agentflow-board ", 1)[1]):
                    if flag == "--help":
                        continue
                    with self.subTest("%s: %s" % (rel, flag)):
                        self.assertIn('"%s"' % flag, source)

    def test_e2e_subcommands_and_flags_exist(self):
        source = read("bin/agentflow-e2e")
        subs = set(re.findall(r'add_parser\("([\w-]+)"', source))
        for rel in all_docs():
            for line in read(rel).splitlines():
                for rest in line.split("agentflow-e2e ")[1:]:
                    sub = re.match(r"[a-z]+", rest)
                    if not sub or sub.group(0) not in ("select", "run", "wait"):
                        continue
                    with self.subTest("%s: %s" % (rel, rest[:40])):
                        self.assertIn(sub.group(0), subs)
                        for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", rest.split("`", 1)[0]):
                            self.assertIn('"%s"' % flag, source)

    def test_base_subcommands_and_flags_exist(self):
        source = read("bin/agentflow-base")
        subs = set(re.findall(r'add_parser\("([\w-]+)"', source))
        for rel in all_docs():
            for line in read(rel).splitlines():
                for rest in line.split("agentflow-base ")[1:]:
                    sub = re.match(r"[a-z]+", rest)
                    if not sub:
                        continue
                    with self.subTest("%s: %s" % (rel, rest[:40])):
                        self.assertIn(sub.group(0), subs)
                        for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", rest.split("`", 1)[0]):
                            self.assertIn('"%s"' % flag, source)

    def test_audit_subcommands_and_flags_exist(self):
        source = read("bin/agentflow-audit")
        subs = set(re.findall(r'add_parser\("([\w-]+)"', source))
        for rel in all_docs():
            for line in read(rel).splitlines():
                for rest in line.split("agentflow-audit ")[1:]:
                    sub = re.match(r"[a-z]+", rest)
                    if not sub:
                        continue
                    with self.subTest("%s: %s" % (rel, rest[:40])):
                        self.assertIn(sub.group(0), subs)
                        for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", rest.split("`", 1)[0]):
                            self.assertIn('"%s"' % flag, source)

    def test_every_lens_has_its_reference(self):
        agent, command = read("agents/audit.md"), read("skills/checklist/SKILL.md")
        for lens in LENSES:
            with self.subTest(lens):
                self.assertIn("${CLAUDE_PLUGIN_ROOT}/references/audit-%s.md" % lens, agent)
                self.assertIn("`%s`" % lens, command)
        findings = read("bin/agentflow-audit")
        self.assertIn("(%s)" % "|".join(LENSES), findings)  # lens of a finding's fp and of the file's first line

    def test_tool_subcommands_exist(self):
        settings, journal = read("bin/agentflow-settings"), read("bin/agentflow-journal")
        for rel in all_docs():
            text = read(rel)
            for sub in re.findall(r"agentflow-settings ([a-z-]+)", text):
                self.assertIn('"%s"' % sub, settings, rel)
            for sub in re.findall(r"agentflow-journal ([a-z]+)", text):
                self.assertIn('"%s"' % sub, journal, rel)

    def test_config_keys_exist(self):
        sections = ("git", "staging", "run", "notify", "design", "labels", "people", "board", "clarify")
        for rel in prompts():
            text = re.sub(r"`[^`]*\.(md|py|json|yaml|yml)\b[^`]*`", "", read(rel))
            for section, key in re.findall(r"(?<![\w./-])(%s)\.([a-z_]+)(?![\w-]*\.(?:md|py|json|com))\b" % "|".join(sections), text):
                if key in ("md", "py", "json", "yaml"):
                    continue
                with self.subTest("%s: %s.%s" % (rel, section, key)):
                    self.assertIn(key, TEMPLATE[section] or {})

    def test_board_status_and_field_keys_exist(self):
        for rel in prompts():
            text = read(rel)
            for stage in re.findall(r"board\.status\.([a-z_]+)", text):
                self.assertIn(stage, afconfig.STAGES, rel)
            for key in re.findall(r"\bfields\.([a-z]+)", text):
                self.assertIn(key, TEMPLATE["board"]["fields"], rel)


class StateMachine(unittest.TestCase):
    """Rules whose loss leaves a ticket stuck or unverified. Each was a real defect or sits next to one: E2E covers the happy
    path and rework, this keeps the branches that are too costly to run from being edited away."""

    RULES = [
        ("references/dispatch.md", r"\*feedback\*:.*gỡ `qc_manual`", "feedback phải gỡ qc_manual, không thì ticket quay về chờ người"),
        ("references/dispatch.md", r"\*qc-failed\*:.*không spawn DEV", "escalate thì không spawn"),
        ("references/dispatch.md", r"PR đã đóng mà không merge.*`blocked`", "PR đóng không merge phải có lối ra"),
        ("references/dispatch.md", r"is:issue repo:<owner>/<repo>", "hàng đợi lọc đúng repo"),
        ("references/dispatch.md", r"Không có `RESULT`.*`blocked`", "agent chết giữa chừng"),
        ("references/protocol.md", r"\*\*Trước bước 1\*\*", "so Status trước khi ghi"),
        ("references/protocol.md", r"Status write — cuối cùng, commit point", "Status ghi cuối cùng"),
        ("references/dispatch.md", r"\*done\*: Status → `done`", "PR đã merge thì ticket tới done"),
        ("references/dispatch.md", r"\*qc-manual-pass\*:.*`update_pull_request draft=false`", "QC người pass thì undraft"),
        ("references/dispatch.md", r"\*feedback\*:.*`update_pull_request draft=true`", "feedback đưa PR về draft"),
        ("references/protocol.md", r"`review_round > run.max_review_rounds`.*\*\*escalate\*\*", "hết lượt review thì escalate"),
        ("references/protocol.md", r"round đã tính, không tăng lần nữa", "chạy lại sau crash không tăng round"),
        ("references/protocol.md", r"`author_association`.*untrusted", "không tin comment của người ngoài"),
        ("references/protocol.md", r"perPage=100", "phân trang comment"),
        ("references/protocol.md", r"không bao giờ merge staging vào nhánh ticket", "staging không chảy ngược vào PR"),
        ("agents/sa.md", r"gỡ `changes_requested`, `qc_failed`", "SA ✅ gỡ label rework, kể cả của QC người"),
        ("agents/dev.md", r"\*\*`draft=true`\*\*", "PR luôn draft"),
        ("agents/dev.md", r"WT bẩn", "resume sau crash"),
        ("skills/do/SKILL.md", r"áp bảng dispatch §3", "/do đi qua cùng bảng hành động"),
        ("references/dispatch.md", r"agentflow-board feedback <owner/repo> --summary", "hàng đợi soát góp ý trên PR"),
        ("references/dispatch.md", r"`in_qc` · `in_review` \| `A` \+ `pending` > 0 \| SYS \*feedback\*", "góp ý ở In Review / In QC cũng về DEV"),
        ("agents/dev.md", r"agentflow-board feedback <REPO> --issue <n>", "DEV đọc góp ý ở mọi MODE"),
        ("agents/dev.md", r"Mọi thread `pending`: `add_reply_to_pull_request_comment`", "mọi thread chờ đều được trả lời, không thì quay vòng"),
        ("agents/dev.md", r"`fb` \(của feedback", "DEV ghi fb sau khi xử lý"),
        ("agents/dev.md", r"agentflow-style origin/<base>`", "DEV soát biểu thức bị bẻ dòng"),
        ("agents/sa.md", r"agentflow-style origin/<base> origin/<branch>", "SA soát biểu thức bị bẻ dòng"),
        ("references/automation.md", r"\*\*Maestro trước\*\*", "Maestro là lựa chọn đầu cho mobile và web"),
        ("references/automation.md", r"Không dùng `assertWithAI`", "không gửi ảnh staging ra AI ngoài"),
        ("agents/dev.md", r"\*\*Tự review trước khi push\*\*", "DEV tự review, tìm nơi gọi"),
        ("agents/dev.md", r"bảng AC \(AC → file chính → TC → flow\)", "PR có bảng AC cho SA"),
        ("agents/sa.md", r"`BEHIND` .*không phải lỗi", "chậm base không trả PR về DEV"),
        ("agents/sa.md", r"\*\*luôn\*\* cả file rủi ro", "SA đọc file rủi ro dù không gắn AC"),
        ("agents/sa.md", r"đường gây lỗi", "mục bug phải có đường gây lỗi"),
        ("references/dispatch.md", r"agentflow-board preflight`, chạy lại ngay trước mỗi lượt spawn", "mạng chặn push thì dừng trước khi tốn token"),
        ("references/dispatch.md", r"`SendMessage`.*\*\*một lần\*\*", "agent chạm maxTurns được làm nốt một lần trước khi blocked"),
        ("references/protocol.md", r"Không `run_in_background`, không poll bằng `sleep`/`until`", "lệnh nền làm agent chạy tiếp sau khi orchestrator đã kết luận; poll đọc lại cả context"),
        ("agents/dev.md", r"Commit đầu tiên ⇒ push \+ mở draft PR ngay", "DEV push checkpoint sớm"),
        ("agents/sa.md", r"Size \(trống thì tự ước lượng", "ticket thiếu Size vẫn qua DoR có kiểm"),
        ("agents/sa.md", r"\*\*DoR\*\*", "SA chặn ticket chưa đủ trước khi thiết kế"),
        ("agents/sa.md", r"`\[AF:SA\] design @", "SA viết thiết kế cho DEV"),
        ("agents/sa.md", r"gắn `labels.agent`; Status giữ `ready`", "SA nhận ticket sau khi thiết kế"),
        ("agents/sa.md", r"\*\*không\*\* gắn `labels.agent`", "SA hỏi PO thì chưa nhận ticket, /task sửa được"),
        ("agents/sa.md", r"\*\*Đúng thiết kế\*\*", "SA review đối chiếu thiết kế"),
        ("agents/sa.md", r"Code đọc ở `origin/<base>`", "SA thiết kế theo base, không theo checkout đang mở"),
        ("agents/dev.md", r"chưa có `\[AF:SA\] design` ⇒ không code", "DEV không code khi chưa có thiết kế"),
        ("agents/dev.md", r"\"Lệch thiết kế\"", "DEV ghi chỗ lệch thiết kế cho SA"),
        ("references/dispatch.md", r"không `A`, không assign người khác \| SA `MODE=design`", "SA thiết kế ticket Ready chưa ai nhận"),
        ("references/dispatch.md", r"`A` \+ state thiếu `design`.*SA `MODE=design`", "ticket cũ ở Ready không tốn một lượt DEV chỉ để abort"),
        ("references/dispatch.md", r"SA design giữ `ready` là đúng", "no-progress guard không chặn nhầm SA design"),
        ("skills/task/SKILL.md", r"\*\*Không đọc code\*\*", "PO không đưa kỹ thuật vào ticket"),
        ("skills/task/SKILL.md", r"gỡ luôn `labels.agent` để SA thiết kế lại", "AC đổi sau thiết kế thì SA thiết kế lại"),
        ("skills/run/SKILL.md", r"dòng khớp \*\*đầu tiên\*\*", "--only không rơi xuống dòng sau của bảng"),
        # 3.0: SA thiết kế (rủi ro + test case) → DEV code + automation + staging → SA review → QC người khi cần
        ("agents/sa.md", r"\*\*Rủi ro\*\*", "SA đánh giá rủi ro lúc thiết kế"),
        ("agents/sa.md", r"\*\*Test case\*\* \(bảng", "SA lập test case cần kiểm chứng"),
        ("agents/sa.md", r"Head ≠ `test_sha` ⇒ \*\*không review\*\*: ❌", "SA không review head chưa chạy flow trên staging"),
        ("agents/sa.md", r"escalate: `· escalated`", "escalate thì dừng chain, không spawn DEV ngay"),
        ("agents/dev.md", r"Chạy khi head PR ≠ `test_sha`", "không ghi test_sha cho head chưa chạy flow"),
        ("agents/dev.md", r"kể cả khi merge `Already up to date`", "resume sau khi chết lúc chờ pipeline vẫn chờ deploy"),
        ("agents/dev.md", r"Bash `timeout: 170000`", "lệnh chờ pipeline xong trước mốc 180 giây harness đẩy nền"),
        ("references/protocol.md", r"`\[AF:DEV\] fixed\|reply` mới hơn", "DEV trả lời không sửa code vẫn là vòng mới"),
        ("agents/sa.md", r"unit/mock test mới mà `CLAUDE.md` không bắt buộc", "plugin không viết mock test"),
        ("agents/sa.md", r"\*\*Có mục \(có nội dung\) chưa tick\*\* ⇒ state `stage: in_qc`", "còn QC tay thì chờ QC người"),
        ("agents/sa.md", r"gắn `qc_manual`; Status → `in_qc`", "SA gắn qc_manual khi giao QC người"),
        ("agents/sa.md", r"\*\*Không có\*\* ⇒ state `stage: ready_to_merge`.*\*\*`update_pull_request draft=false`\*\*", "không có QC tay thì SA undraft"),
        ("agents/dev.md", r"\|\| \{ echo MERGE_CONFLICT", "conflict dừng khối deploy"),
        ("agents/dev.md", r"Không bao giờ merge staging vào nhánh ticket", "DEV không đưa code ticket khác vào PR"),
        ("agents/dev.md", r"--wait 2\.5", "chờ pipeline dưới 180 giây, vẫn trong TTL của prompt cache"),
        ("agents/dev.md", r"`--skip '<glob>'` cho mỗi mục `staging.skip_checks`", "không chờ release mobile"),
        ("agents/dev.md", r"Tối đa `run.max_test_rounds` vòng", "vòng sửa test có trần"),
        ("agents/dev.md", r"\*\*Lỗi block\*\*.*`\[AF:DEV\] blocked`", "hết vòng thì ghi lỗi block lên issue"),
        ("agents/dev.md", r"gắn `blocked`, giữ `in_progress`, mention `people.po`", "lỗi block báo PO"),
        ("agents/dev.md", r"không viết unit/integration test có mock", "plugin không viết mock test"),
        ("agents/dev.md", r"`test_sha: <head>`", "DEV ghi head đã test cho SA"),
        ("references/automation.md", r"\*\*Chọn flow liên quan\*\*", "chỉ chạy flow liên quan, không cả suite"),
        # 3.5 (người dùng chọn 2026-11-14): SA chốt regression, flow mới 1 + 2 lần, DEV tách lượt verify
        ("agents/sa.md", r"\*\*Regression\*\* — flow có sẵn DEV chạy lại.*≤ `run.max_regression`", "SA chốt flow regression có trần"),
        ("agents/sa.md", r"`only: web` \(chỉ chạm backend\) ⇒ chỉ flow web", "diff chỉ chạm backend thì regression chỉ trên web"),
        ("references/automation.md", r"đúng mục \*\*Regression\*\* của `\[AF:SA\] design`", "DEV chạy đúng danh sách SA chốt"),
        ("references/automation.md", r"head cuối chạy thêm `--repeat 2`", "flow mới chạy 1 lần khi sửa, thêm 2 lần ở head cuối"),
        ("agents/dev.md", r"\*\*Tách lượt\*\*.*`RESULT: in_progress · verify`", "phần chạy flow ở context mới"),
        ("references/dispatch.md", r"RESULT `verify`.*spawn ngay DEV `MODE=verify`", "orchestrator nối lượt verify"),
        ("references/protocol.md", r"`verify` = DEV đã code \+ deploy staging", "RESULT verify có nghĩa"),
        ("references/automation.md", r"không chờ release mobile", "mobile test bằng build local trỏ staging"),
        ("references/automation.md", r"Chỉ mở ảnh \(Read\) khi flow fail, cộng \*\*một\*\* ảnh cuối mỗi AC UI", "xem ảnh tiết kiệm token"),
        ("references/automation.md", r"\*\*QC tay\*\* \(chặn merge", "QC tay là cổng duy nhất của QC người"),
        ("references/automation.md", r"\*\*Đề xuất kiểm chứng thêm\*\* \(không chặn", "danh sách testcase cần kiểm chứng lại"),
        ("references/dispatch.md", r"\*requeue\*: state `stage: in_progress`", "ticket của luồng cũ ở In QC không kẹt"),
        ("references/dispatch.md", r"`in_qc` \| `A` \+ `qc_failed` \(QC người fail\) \| SYS \*qc-failed\*", "QC người fail về DEV, kể cả khi qc_manual đã bị gỡ"),
        ("references/dispatch.md", r"trừ khi state đã `stage: ready` \(chạy lại sau crash\)", "chạy lại qc-failed không tăng round hai lần"),
        ("references/automation.md", r"QC tay \*\*luôn\*\* có `- \[ \] Xác nhận lại lỗi QC đã báo", "QC người báo fail thì kiểm lại trước merge (người dùng chọn)"),
        ("agents/sa.md", r"`qc_round` > 0 mà QC tay thiếu mục xác nhận lại", "SA không cho rework sau QC fail bỏ qua QC người"),
        # 3.6: làm rõ yêu cầu trước khi tạo task / implement — auto tự chọn có căn cứ, ask cho người chọn rồi xác nhận
        ("agents/sa.md", r"`CLARIFY: auto` ⇒ tự chọn.*căn cứ", "auto: SA tự quyết điểm mơ hồ và ghi căn cứ"),
        ("agents/sa.md", r"`ask`/`ask-live` ⇒ làm theo `\$\{CLAUDE_PLUGIN_ROOT\}/references/clarify.md` §SA", "ask: SA đưa phương án thay vì tự chọn"),
        ("references/clarify.md", r"\*\*không\*\* gắn `labels.agent`", "options chưa trả lời thì DEV không nhận ticket"),
        ("references/clarify.md", r"Cả hai gắn `needs_info` khi chờ người", "/do đứt giữa chừng thì /run không tự cho DEV làm"),
        ("references/clarify.md", r"Chưa xác nhận ⇒ không ghi ticket, DEV không bắt đầu", "ask: không làm khi người chưa xác nhận"),
        ("references/clarify.md", r"Cổng Ready \(§6\) vẫn hỏi PO", "auto /task vẫn không tự đưa ticket ra khỏi Backlog"),
        ("references/clarify.md", r"\"Dừng ở đây\" ⇒ giữ \(thiếu thì gắn\) `needs_info`", "dừng ở cổng xác nhận thì /run không tự cho DEV làm"),
        ("references/dispatch.md", r"ask mà `plan` thiếu/`options` \| SA `MODE=design`", "ask: ticket đã thiết kế bằng auto vẫn qua cổng xác nhận"),
        ("references/dispatch.md", r"`plan: confirm`.*SYS \*confirmed\* → DEV `MODE=new`", "ask: DEV chỉ bắt đầu sau xác nhận"),
        ("skills/do/SKILL.md", r"trừ cổng ask ở điểm 8", "/do được hỏi ở cổng ask"),
        # 3.8: a ticket's work starts from origin/<base>; the main checkout is the person's and changes branch at any time
        ("references/protocol.md", r"\*\*Không dùng checkout chính\*\*.*Không tạo/đổi nhánh local", "agent không đọc code/luật ở nhánh người đang mở"),
        ("references/protocol.md", r"`git -C <wt> push origin HEAD:refs/heads/<branch>`", "worktree detached push bằng refspec đầy đủ"),
        ("agents/dev.md", r"`agentflow-base worktree <n> --branch <branch>`", "DEV làm trong worktree từ origin, không nhánh local"),
        ("agents/dev.md", r"Project skill `\$WT/\.claude/skills/", "luật của repo theo nhánh ticket, không theo checkout chính"),
        ("references/dispatch.md", r"`agentflow-base clean --issue <n>…`", "dọn worktree không mất commit chưa push"),
        ("skills/init/SKILL.md", r"git rev-parse --git-common-dir\)/info/exclude", "init không sửa .gitignore của project"),
        # 3.8: several tickets in Ready — a freed slot is filled at once; parallel DEVs share staging and the device
        ("skills/run/SKILL.md", r"dừng ⇒ slot trống, lấp ngay, không chờ agent khác xong", "slot trống không chờ cả lô xong"),
        ("references/dispatch.md", r"run_in_background=<true khi parallel > 1>", "song song thật: spawn thường chặn orchestrator tới khi xong"),
        ("references/dispatch.md", r"slot trống thì lấp ngay", "song song theo slot, không theo lô"),
        ("references/automation.md", r"`run --install`.*`queued` = DEV khác đang dùng", "một thiết bị một ticket một lúc"),
        ("references/automation.md", r"Head staging đổi so với lúc bắt đầu chạy.*không tính vòng", "ticket khác deploy giữa chừng không thành vòng sửa/blocked"),
        ("references/engineering.md", r"Đổi state/vòng đời của một luồng ⇒ liệt kê mọi lối vào/ra", "tự review bắt lỗi sót lối vào/ra (review ❌ hay gặp nhất)"),
        # 3.9: /agentflow:checklist — experts find evidence, the person picks, tickets land in Backlog
        ("skills/checklist/SKILL.md", r"không đưa ticket ra khỏi Backlog khi người chưa xác nhận", "checklist không tự đưa việc vào pipeline"),
        ("skills/checklist/SKILL.md", r"Không assign, không ghi Status nào khác `backlog`", "ticket của checklist chờ PO chốt"),
        ("skills/checklist/SKILL.md", r"\*\*ask\*\*: AskUserQuestion \"Lên ticket cho mục nào", "ask: người chọn mục trước khi tạo ticket"),
        ("skills/checklist/SKILL.md", r"Sổ phát hiện", "lần sau nhớ mục đã có, báo tái phát (GitHub là nơi duy nhất giữ trạng thái)"),
        ("skills/checklist/SKILL.md", r"\*\*không nuốt lỗi\*\*", "ghi lỗi giữa chừng thì dừng và báo"),
        ("skills/checklist/SKILL.md", r"run_in_background=true", "các lăng kính chạy song song"),
        ("agents/audit.md", r"\*\*Bằng chứng trước kết luận\*\*", "không phát hiện nào không có bằng chứng"),
        ("agents/audit.md", r"`agentflow-audit findings <OUT>`: exit 0", "file phát hiện đúng dạng trước khi trả về"),
        ("agents/audit.md", r"không thao tác không hoàn tác được trên staging", "audit không làm hỏng dữ liệu staging"),
        ("references/audit-qa.md", r"`--issue 0` = audit", "lượt chạy của audit tách khỏi ticket"),
        ("references/audit-qa.md", r"≤ 30 ảnh mỗi lượt", "soi ảnh có trần token"),
        ("references/audit-qa.md", r"có thể do ticket đang làm", "lỗi của ticket chưa merge không thành bug của sản phẩm"),
        ("references/audit-arch.md", r"Số đo chỉ nói \*\*chỗ cần đọc\*\*", "radar không thay cho đọc code"),
        ("references/audit-product.md", r"không gửi tên khách hàng, code, dữ liệu nội bộ", "WebSearch không lộ dữ liệu của repo"),
        ("references/audit-product.md", r"`Chưa rõ: <câu hỏi> \(đề xuất", "PO chốt con số agent đề xuất"),
    ]

    def test_rules_still_stated(self):
        for rel, pattern, why in self.RULES:
            with self.subTest(why):
                self.assertRegex(read(rel), pattern)

    def test_feedback_mark_is_written_by_dev_only(self):
        # SYS writing fb when it triggers would hide feedback that lands while DEV works.
        self.assertNotRegex(read("references/dispatch.md"), r"\*feedback\*:[^\n]*`fb:")

    def test_every_label_has_a_remover(self):
        text = "".join(read(p) for p in prompts())
        for key in ("changes_requested", "qc_failed", "qc_manual"):
            with self.subTest(key):
                self.assertRegex(text, r"gỡ[^.\n]{0,60}`%s`" % key)


class RealGitHubMcp(unittest.TestCase):
    """tests/e2e/github_tools.json is what the real server answered to tools/list. Re-record it when the server changes."""

    def setUp(self):
        self.tools = json.loads(read("tests/e2e/github_tools.json"))
        self.text = "\n".join(read(p) for p in prompts())

    def test_methods_the_prompts_call_exist(self):
        for tool, method in re.findall(r"\b(\w+) method=(\w+)", self.text):
            if tool in self.tools:
                with self.subTest("%s method=%s" % (tool, method)):
                    self.assertIn(method, self.tools[tool]["properties"]["method"]["enum"])

    def test_parameters_the_prompts_rely_on_exist(self):
        props = lambda tool: self.tools[tool]["properties"]
        self.assertIn("updated_field", props("projects_write"))
        self.assertIn("draft", props("update_pull_request"))
        self.assertIn("draft", props("create_pull_request"))
        self.assertIn("event", props("pull_request_review_write"))
        self.assertIn("field_names", props("projects_list"))
        self.assertIn("field_names", props("projects_get"))
        self.assertIn("perPage", props("issue_read"))
        self.assertNotIn("per_page", self.text)
        for key in ("failed_only", "return_content", "tail_lines"):
            self.assertIn(key, props("get_job_logs"))

    def test_guard_knows_the_dangerous_tool_names(self):
        guard = read("scripts/guard.py")
        for name in ("merge_pull_request", "actions_run_trigger"):
            self.assertIn(name, self.tools)
            self.assertIn(name, guard)


class Evals(unittest.TestCase):
    CASES = ["guard-force-push", "guard-secret-read", "sa-ask-options", "sa-dor-missing-ac", "sa-escalates", "sa-rejects"]

    def graders(self):
        for path in glob.glob(os.path.join(ROOT, "evals", "*", "graders", "*.md")):
            yield os.path.relpath(path, ROOT), frontmatter(os.path.relpath(path, ROOT))

    def test_cases_have_everything(self):
        names = sorted(d for d in os.listdir(os.path.join(ROOT, "evals")) if os.path.isfile(os.path.join(ROOT, "evals", d, "case.yaml")))
        self.assertEqual(names, self.CASES)
        for name in names:
            meta = afconfig.parse_yaml(read("evals/%s/case.yaml" % name))
            self.assertEqual(meta["name"], name)
            self.assertTrue(os.stat(os.path.join(ROOT, "evals", name, "fixture.sh")).st_mode & stat.S_IXUSR)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "evals", name, "prompt.md")))
            self.assertIn(name, read("evals/README.md"))

    def test_trace_regex_is_anchored_to_a_tool_call(self):
        """Unanchored, a trace regex also matches the prompts the agent read: `[AF:SA] deployed` is in sa.md."""
        for rel, meta in self.graders():
            if meta.get("type") == "regex" and meta.get("target") == "trace" and "[AF:" in meta["pattern"]:
                with self.subTest(rel):
                    self.assertTrue(meta["pattern"].startswith('"name":"mcp__plugin_agentflow_github__'))

    def test_llm_grader_can_see_the_verdict(self):
        for rel, meta in self.graders():
            if meta.get("type") == "llm":
                self.assertEqual(meta.get("focus"), "trace", rel)

    def test_mocks_name_tools_the_prompts_use(self):
        text = "".join(read(p) for p in prompts())
        for path in glob.glob(os.path.join(ROOT, "evals", "**", "mocks", "github", "*.md"), recursive=True):
            name = os.path.basename(path)[:-3]
            with self.subTest(name):
                self.assertIn(name, text)

    def test_runner_never_publishes_and_keeps_the_real_manifest(self):
        runner = read("evals/run.sh")
        self.assertIn("--no-publish", runner)
        self.assertIn("$TMP/agentflow/.claude-plugin/plugin.json", runner)
        self.assertIs(json.loads(read(".claude-plugin/plugin.json"))["defaultEnabled"], False)


class SharedFacts(unittest.TestCase):
    def test_schema(self):
        self.assertEqual(TEMPLATE["schema"], afconfig.SCHEMA)
        self.assertIn("(schema %d)" % afconfig.SCHEMA, read("references/protocol.md"))
        self.assertIn("`schema` phải là `%d`" % afconfig.SCHEMA, read("references/protocol.md"))
        self.assertIn("schema %d" % afconfig.SCHEMA, read("skills/init/SKILL.md"))

    def test_stages_everywhere(self):
        self.assertEqual(list(TEMPLATE["board"]["status"]), afconfig.STAGES)
        protocol_stages = re.findall(r"^\| `([a-z_]+)` \|", read("references/protocol.md").split("## 2.")[1].split("## 3.")[0], re.M)
        self.assertEqual(protocol_stages, afconfig.STAGES)
        board = read("bin/agentflow-board")
        for table in ("STATUS_COLORS", "STATUS_DESC"):
            body = board.split(table + " = {", 1)[1].split("}", 1)[0]
            self.assertEqual(re.findall(r'"([a-z_]+)":', body), afconfig.STAGES, table)
        setup = read("skills/init/references/board-setup.md")
        self.assertEqual(re.findall(r"^\| `([a-z_]+)` \| [A-Z]", setup.split("## Link board")[1].split("Thiếu stage")[0], re.M), afconfig.STAGES)

    def test_labels_everywhere(self):
        signals = {k: v for k, v in TEMPLATE["labels"].items() if k != afconfig.PLATFORM_KEY}
        self.assertEqual(list(signals), afconfig.LABEL_KEYS)
        setup = read("skills/init/references/board-setup.md").split("## Label")[1].split("Repo đã có")[0]
        rows = re.findall(r"^\| `([a-z_]+)` \| ([\w-]+) \|", setup, re.M)
        self.assertEqual(rows, list(signals.items()))
        for key, name in TEMPLATE["labels"][afconfig.PLATFORM_KEY].items():
            self.assertIn("%s → %s" % (key, name), setup)
        for rel in prompts():
            for key in re.findall(r"labels\.([a-z_]+)", read(rel)):
                self.assertIn(key, afconfig.LABEL_KEYS + [afconfig.PLATFORM_KEY], rel)

    def test_prompts_use_label_keys_not_literal_names(self):
        for name in ("agents/sa.md", "agents/dev.md", "references/dispatch.md"):
            self.assertNotRegex(read(name), r"gắn `(needs-info|changes-requested|qc-failed|qc-manual)`", name)

    def test_comment_heads_are_documented(self):
        table = read("references/protocol.md").split("## 5.")[1].split("## 6.")[0]
        known = set(re.findall(r"\[AF:(\w+)\] ([^\s`@#<]+)", table))
        sys_events = re.search(r"`\[AF:SYS\] <event>` \| ([^\n]+)", table).group(1)
        known |= {("SYS", e) for e in re.findall(r"`([a-z-]+)`", sys_events)}
        if "`[AF:REVIEW]`: đọc như `[AF:SA]`" in table:  # 2.x name of the SA, still read on old tickets
            known |= {("REVIEW", e) for role, e in set(known) if role == "SA"}
        for rel in ["agents/%s.md" % a for a in AGENTS] + ["references/dispatch.md"] + ["skills/%s/SKILL.md" % s for s in SKILLS] + ["templates/board-readme.md", "bin/agentflow-board"]:
            legacy = {("QC", e) for e in ("✅", "❌", "?")} if rel == "bin/agentflow-board" else set()  # metrics of pre-3.0 tickets
            for role, events in re.findall(r"\[AF:(\w+)\] ([^\s`@#<\"…]+)", read(rel)):
                for event in events.split("|"):
                    if (role, event) in legacy:
                        continue
                    with self.subTest("%s: [AF:%s] %s" % (rel, role, event)):
                        self.assertIn((role, event), known)

    def test_audit_never_writes_github(self):
        tools = frontmatter("agents/audit.md")["tools"]
        self.assertIn("mcp__plugin_agentflow_github__*", tools)  # reads issues for the product lens
        self.assertIn('"audit"', read("scripts/guard.py"))  # … and the guard keeps it to reads
        self.assertNotRegex(read("agents/audit.md"), r"\b(issue_write|add_issue_comment|projects_write)\b")

    def test_every_role_prefix_used_by_its_agent(self):
        self.assertIn("[AF:DEV]", read("agents/dev.md"))
        self.assertIn("[AF:SA]", read("agents/sa.md"))

    def test_result_values(self):
        check = read("scripts/result-check.py")
        values = re.search(r"\(ok\|([\w|]+)\)", check).group(0).strip("()").split("|")
        protocol = re.search(r"RESULT: <stage hiện tại> · <([\w|]+)>", read("references/protocol.md")).group(1).split("|")
        self.assertEqual(values, protocol)
        for value in re.findall(r"RESULT: [\w<>`]+ · ([a-z_]+)", "".join(read("agents/%s.md" % a) for a in AGENTS)):
            self.assertIn(value, protocol)

    def test_journal_kinds(self):
        kinds = re.search(r'KINDS = \(([^)]*)\)', read("bin/agentflow-journal")).group(1)
        code = set(re.findall(r'"(\w+)"', kinds))
        documented = set(re.findall(r"`(\w+)`", read("references/protocol.md").split("`kind`:")[1].split("\n")[0]))
        self.assertEqual(code - {"other"}, documented)
        for rel in prompts():
            for kind in re.findall(r"journal `(?:kind=)?(\w+)`", read(rel)):
                self.assertIn(kind, code, rel)

    def test_notify_events(self):
        self.assertEqual(set(TEMPLATE["notify"]["events"]), afconfig.NOTIFY_EVENTS)
        for rel in prompts():
            for event in re.findall(r"agentflow-notify (\w+) ", read(rel)):
                self.assertIn(event, afconfig.NOTIFY_EVENTS, rel)

    def test_default_forbidden_documented(self):
        for doc in ("references/protocol.md", "agentflow.yaml"):
            text = read(doc)
            for pattern in afconfig.DEFAULT_FORBIDDEN:
                name = pattern.replace("**/", "")
                if name == ".env":
                    continue
                needle = ".env" if name == ".env.*" else name
                self.assertIn(needle, text, "%s thiếu %s" % (doc, pattern))

    def test_agent_mode_and_input_line_up_with_dispatch(self):
        dispatch = read("references/dispatch.md")
        self.assertIn("MODE=new", dispatch)
        for mode in ("new", "rework", "resume"):
            self.assertIn("`%s`" % mode, read("agents/dev.md"))
        self.assertIn("agentflow:<sa|dev>", dispatch)
        for agent, modes in (("sa", ("design", "review")),):
            for mode in modes:
                self.assertIn("%s `MODE=%s`" % (agent.upper(), mode), dispatch)
                self.assertIn("`MODE=%s`" % mode, read("agents/%s.md" % agent))
        for agent in AGENTS:
            self.assertIn("RESULT", read("agents/%s.md" % agent))
            self.assertIn("references/protocol.md", read("agents/%s.md" % agent))

    def test_docs_list_every_command_and_agent(self):
        readme = read("README.md")
        for name in SKILLS:
            self.assertIn("/agentflow:%s" % name, readme)
        for name in AGENTS:
            self.assertIn("%s.md" % name, readme)

    def test_no_stale_claims(self):
        notes = read("DESIGN-NOTES.md")
        self.assertNotIn("isolation: worktree` truyền lúc spawn", notes)
        self.assertNotIn("hook không phân biệt role", notes)
        self.assertNotIn("CHANGELOG", "".join(read(p) for p in all_docs()))


if __name__ == "__main__":
    unittest.main()
