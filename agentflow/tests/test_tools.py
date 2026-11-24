#!/usr/bin/env python3
"""agentflow-settings, agentflow-journal, agentflow-notify, agentflow-base, mcp-headers, result-check: run as the user runs them."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FAKE_PAT = "gh" + "p_" + "a1B2" * 9


def tool(name, *args, cwd=None, stdin=None, env=None):
    path = os.path.join(ROOT, "bin", name) if name.startswith("agentflow-") else os.path.join(ROOT, "scripts", name)
    full = {"PATH": "/usr/bin:/bin", "HOME": cwd or tempfile.gettempdir()}
    full.update(env or {})
    return subprocess.run([sys.executable, "-I", path, *args], cwd=cwd, input=stdin, capture_output=True, text=True, env=full)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.realpath(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "master"], cwd=self.repo, check=True)
        self.settings = os.path.join(self.repo, ".claude", "settings.local.json")

    def read_settings(self):
        with open(self.settings, encoding="utf-8") as fh:
            return json.load(fh)


class Settings(RepoCase):
    def test_secret_is_stored_private_and_never_shown(self):
        res = tool("agentflow-settings", "set-secret", "GITHUB_TOKEN", cwd=self.repo, stdin="s3cret-value\n")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("s3cret-value", res.stdout + res.stderr)
        self.assertEqual(self.read_settings()["env"]["GITHUB_TOKEN"], "s3cret-value")
        self.assertEqual(stat.S_IMODE(os.stat(self.settings).st_mode), 0o600)
        shown = tool("agentflow-settings", "show", cwd=self.repo)
        self.assertNotIn("s3cret-value", shown.stdout)
        self.assertEqual(json.loads(shown.stdout)["env"]["GITHUB_TOKEN"], "<set>")

    def test_existing_world_readable_file_is_tightened(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w") as fh:
            fh.write("{}")
        os.chmod(self.settings, 0o644)
        tool("agentflow-settings", "set-secret", "X", cwd=self.repo, stdin="v\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.settings).st_mode), 0o600)

    def test_stale_temp_file_cannot_widen_the_mode(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings + ".tmp", "w") as fh:
            fh.write("")
        os.chmod(self.settings + ".tmp", 0o644)
        tool("agentflow-settings", "set-secret", "X", cwd=self.repo, stdin="v\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.settings).st_mode), 0o600)

    def test_show_masks_secret_looking_keys_anywhere(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w") as fh:
            json.dump({"mcpServers": {"x": {"headers": {"Authorization": "Bearer abc"}}}, "apiKeyHelper": "keep", "env": {"A": ""}}, fh)
        shown = json.loads(tool("agentflow-settings", "show", cwd=self.repo).stdout)
        self.assertEqual(shown["mcpServers"]["x"]["headers"]["Authorization"], "<set>")
        self.assertEqual(shown["env"]["A"], "<empty>")

    def test_set_merges_and_parses_json(self):
        tool("agentflow-settings", "set", "permissions.defaultMode", '"bypassPermissions"', cwd=self.repo)
        tool("agentflow-settings", "set", "enabledPlugins.agentflow@m", "true", cwd=self.repo)
        tool("agentflow-settings", "set", "x.plain", "not json", cwd=self.repo)
        self.assertEqual(self.read_settings(), {"permissions": {"defaultMode": "bypassPermissions"}, "enabledPlugins": {"agentflow@m": True}, "x": {"plain": "not json"}})

    def test_refuses_env_and_locked_keys(self):
        for key, value in (("env.A", "1"), ("disableAllHooks", "true"), ("hooks.PreToolUse", "[]"), ("enabledPlugins.agentflow@m", "false")):
            with self.subTest(key):
                self.assertNotEqual(tool("agentflow-settings", "set", key, value, cwd=self.repo).returncode, 0)
        self.assertFalse(os.path.exists(self.settings))

    def test_has(self):
        self.assertEqual(tool("agentflow-settings", "has", "A", cwd=self.repo).returncode, 1)
        tool("agentflow-settings", "set-secret", "A", cwd=self.repo, stdin="v\n")
        self.assertEqual(tool("agentflow-settings", "has", "A", cwd=self.repo).returncode, 0)

    def test_empty_stdin_writes_nothing(self):
        self.assertNotEqual(tool("agentflow-settings", "set-secret", "A", cwd=self.repo, stdin="\n").returncode, 0)
        self.assertFalse(os.path.exists(self.settings))

    def test_broken_json_reports_without_content(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w") as fh:
            fh.write('{"env": {"T": "leaky-value"')
        res = tool("agentflow-settings", "show", cwd=self.repo)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("JSON", res.stderr)
        self.assertNotIn("leaky-value", res.stdout + res.stderr)

    def test_exec_runs_with_the_file_env_over_the_process_env(self):
        tool("agentflow-settings", "set-secret", "A", cwd=self.repo, stdin="from-file\n")
        probe = "import os,sys; sys.exit(0 if os.environ.get('A') == 'from-file' and os.environ.get('B') == 'kept' else 1)"
        for prefix in (["--"], []):
            with self.subTest(prefix):
                res = tool("agentflow-settings", "exec", *prefix, sys.executable, "-c", probe, cwd=self.repo, env={"A": "stale", "B": "kept"})
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertNotIn("from-file", res.stdout + res.stderr)

    def test_import_copies_the_value_in_use_without_echo(self):
        res = tool("agentflow-settings", "import", "TELEGRAM_BOT_TOKEN", cwd=self.repo, env={"TELEGRAM_BOT_TOKEN": FAKE_PAT})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn(FAKE_PAT, res.stdout + res.stderr)
        res = tool("agentflow-settings", "import", "STAGING_TEST_USER", cwd=self.repo, env={"STAGING_TEST_USER": "qa@x"})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read_settings()["env"], {"TELEGRAM_BOT_TOKEN": FAKE_PAT, "STAGING_TEST_USER": "qa@x"})
        self.assertEqual(stat.S_IMODE(os.stat(self.settings).st_mode), 0o600)

    def test_allow_appends_unique_rules_and_keeps_the_rest(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w") as fh:
            json.dump({"permissions": {"allow": ["Bash"], "defaultMode": "acceptEdits"}, "env": {"A": "1"}}, fh)
        res = tool("agentflow-settings", "allow", "Bash", "Edit", "mcp__plugin_agentflow_github", "Edit", cwd=self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read_settings(), {"permissions": {"allow": ["Bash", "Edit", "mcp__plugin_agentflow_github"], "defaultMode": "acceptEdits"}, "env": {"A": "1"}})
        self.assertIn("đã có đủ", tool("agentflow-settings", "allow", "Edit", cwd=self.repo).stdout)

    def test_allow_user_writes_the_user_settings_and_keeps_its_mode(self):
        cfg = os.path.join(self.repo, "cfg")
        os.makedirs(cfg)
        user = os.path.join(cfg, "settings.json")
        with open(user, "w") as fh:
            json.dump({"model": "opus", "permissions": {"allow": ["Read"]}}, fh)
        os.chmod(user, 0o644)
        res = tool("agentflow-settings", "allow", "--user", "Read", "mcp__plugin_agentflow_github", cwd=self.repo, env={"CLAUDE_CONFIG_DIR": cfg})
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(user) as fh:
            self.assertEqual(json.load(fh), {"model": "opus", "permissions": {"allow": ["Read", "mcp__plugin_agentflow_github"]}})
        self.assertEqual(stat.S_IMODE(os.stat(user).st_mode), 0o644)
        self.assertFalse(os.path.exists(self.settings))
        self.assertEqual(tool("agentflow-settings", "allow", "--user", cwd=self.repo, env={"CLAUDE_CONFIG_DIR": cfg}).returncode, 2)

    def test_github_token_is_not_imported_from_gh(self):
        self.assertNotEqual(tool("agentflow-settings", "import", "GITHUB_TOKEN", cwd=self.repo).returncode, 0)

    def test_unset_removes_one_env_key(self):
        tool("agentflow-settings", "set-secret", "GITHUB_TOKEN", cwd=self.repo, stdin="old\n")
        tool("agentflow-settings", "set-secret", "TELEGRAM_CHAT_ID", cwd=self.repo, stdin="1\n")
        res = tool("agentflow-settings", "unset", "GITHUB_TOKEN", cwd=self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read_settings()["env"], {"TELEGRAM_CHAT_ID": "1"})
        self.assertEqual(stat.S_IMODE(os.stat(self.settings).st_mode), 0o600)
        self.assertEqual(tool("agentflow-settings", "unset", "GITHUB_TOKEN", cwd=self.repo).returncode, 0)

    def test_import_without_a_value_writes_nothing(self):
        self.assertNotEqual(tool("agentflow-settings", "import", "STAGING_TEST_USER", cwd=self.repo).returncode, 0)
        self.assertFalse(os.path.exists(self.settings))

    def test_exec_without_command_or_missing_binary(self):
        for args in (["exec"], ["exec", "--"]):
            self.assertEqual(tool("agentflow-settings", *args, cwd=self.repo).returncode, 2)
        res = tool("agentflow-settings", "exec", "--", "no-such-binary-af", cwd=self.repo)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("no-such-binary-af", res.stderr)

    def test_worktree_shares_the_main_settings(self):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i", "--allow-empty"], cwd=self.repo, check=True)
        subprocess.run(["git", "worktree", "add", "-q", "wt", "-b", "f"], cwd=self.repo, check=True)
        tool("agentflow-settings", "set-secret", "A", cwd=os.path.join(self.repo, "wt"), stdin="v\n")
        self.assertEqual(self.read_settings()["env"]["A"], "v")


class Journal(RepoCase):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.repo, "j", "journal.jsonl")
        self.env = {"AGENTFLOW_JOURNAL": self.path}

    def jr(self, *args):
        return tool("agentflow-journal", *args, cwd=self.repo, env=self.env)

    def rows(self):
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh]

    def test_add_list_mark_stats(self):
        first = self.jr("add", "retry", "nên X", "--issue", "7", "--role", "dev", "--repo", "o/r").stdout.split()[1]
        second = self.jr("add", "slow", "nên Y").stdout.split()[1]
        self.assertIn("nên X", self.jr("list").stdout)
        self.assertEqual(self.rows()[0]["issue"], 7)
        self.assertIn("marked 1/1", self.jr("mark", first, "--as", "applied", "--ref", "v2").stdout)
        self.assertNotIn("nên X", self.jr("list").stdout)
        self.assertIn("nên X", self.jr("list", "--all").stdout)
        self.assertIn("slow", self.jr("stats").stdout)
        self.assertNotIn("retry", self.jr("stats").stdout)
        self.jr("mark", second, "--as", "dismissed")
        self.assertIn("không có entry mới", self.jr("stats").stdout)

    def test_unknown_kind_refused(self):
        self.assertNotEqual(self.jr("add", "nope", "x").returncode, 0)

    def test_token_is_scrubbed_before_it_reaches_disk(self):
        self.jr("add", "tool_error", "call lỗi với %s rồi" % FAKE_PAT)
        with open(self.path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn(FAKE_PAT, text)
        self.assertIn("<secret>", text)

    def test_note_is_one_line_and_bounded(self):
        self.jr("add", "other", "a\nb  " + "c" * 1000)
        note = self.rows()[0]["note"]
        self.assertNotIn("\n", note)
        self.assertLessEqual(len(note), 400)

    def test_corrupt_line_is_skipped(self):
        self.jr("add", "other", "ok")
        with open(self.path, "a") as fh:
            fh.write("{broken\n")
        self.assertIn("ok", self.jr("list").stdout)

    def test_empty_journal(self):
        self.assertIn("trống", self.jr("list").stdout)


class Notify(RepoCase):
    def write_cfg(self, text):
        with open(os.path.join(self.repo, "agentflow.yaml"), "w") as fh:
            fh.write(text)

    def test_off_by_default(self):
        self.write_cfg("notify:\n  telegram: false\n")
        res = tool("agentflow-notify", "blocked", "x", cwd=self.repo)
        self.assertEqual((res.returncode, res.stdout.strip()), (0, "notify: off"))

    def test_event_not_listed(self):
        self.write_cfg("notify:\n  telegram: true\n  events: [blocked]\n")
        self.assertIn("không bật", tool("agentflow-notify", "qc_manual", "x", cwd=self.repo).stdout)

    def test_missing_credentials_does_not_fail(self):
        self.write_cfg("notify:\n  telegram: true\n  events: [blocked]\n")
        res = tool("agentflow-notify", "blocked", "x", cwd=self.repo)
        self.assertEqual(res.returncode, 0)
        self.assertIn("thiếu", res.stdout)

    def test_unreachable_network_does_not_fail_nor_leak(self):
        self.write_cfg("notify:\n  telegram: true\n  events: [blocked]\n")
        env = {"TELEGRAM_BOT_TOKEN": "123:bot-secret", "TELEGRAM_CHAT_ID": "1", "HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"}
        res = tool("agentflow-notify", "blocked", "x", cwd=self.repo, env=env)
        self.assertEqual(res.returncode, 0)
        self.assertNotIn("bot-secret", res.stdout + res.stderr)

    def test_credentials_from_the_settings_file_without_restart(self):
        self.write_cfg("notify:\n  telegram: true\n  events: [blocked]\n")
        for name, value in (("TELEGRAM_BOT_TOKEN", "123:bot-secret"), ("TELEGRAM_CHAT_ID", "1")):
            tool("agentflow-settings", "set-secret", name, cwd=self.repo, stdin=value + "\n")
        res = tool("agentflow-notify", "blocked", "x", cwd=self.repo, env={"HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"})
        self.assertEqual(res.returncode, 0)
        self.assertIn("failed", res.stdout)  # it tried to send: the credentials were found
        self.assertNotIn("bot-secret", res.stdout + res.stderr)

    def test_broken_config_and_outside_repo(self):
        self.write_cfg("\tbad: [\n")
        self.assertEqual(tool("agentflow-notify", "blocked", "x", cwd=self.repo).returncode, 0)
        self.assertEqual(tool("agentflow-notify", "blocked", "x", cwd=tempfile.gettempdir()).returncode, 0)

    def test_usage(self):
        self.assertEqual(tool("agentflow-notify", cwd=self.repo).returncode, 0)


WRAPPED = """const isWordChar = (char?: string) =>
  !!char && (char.toLowerCase() !== char.toUpperCase() || /[0-9_]/.test(char));
const isRNAnimatedValue = (v: unknown): v is Animated.Value =>
  !!v &&
  typeof (v as Animated.Value).setValue === 'function' &&
  typeof (v as Animated.Value).interpolate === 'function';
const label = isLoggedIn
  ? translate('home.greeting', { name: user.fullName })
  : translate('home.guest');
"""
ONE_LINERS = """const isEven = (n: number) => n % 2 === 0;
const short = isDone ? 'Xong' : 'Chưa';
const Row = ({ item }: Props) => (
  <View>{item.visible && <Text>{item.name}</Text>}</View>
);
const x = a?.b ?? c;
// a comment that ends with &&
items.map((item) => {
  return item;
});
"""


class Style(RepoCase):
    def setUp(self):
        super().setUp()
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        self.git("switch", "-q", "-c", "feat")

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.repo, check=True)

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_wrapped_expressions_one_hit_each(self):
        self.write("src/a.ts", ONE_LINERS + WRAPPED)
        res = tool("agentflow-style", "master", cwd=self.repo)
        self.assertEqual(res.returncode, 1, res.stderr)
        hits = [line.split("  ")[:2] for line in res.stdout.splitlines() if line.startswith("src/")]
        self.assertEqual(hits, [["src/a.ts:11", "arrow"], ["src/a.ts:13-15", "arrow,logic"], ["src/a.ts:18-19", "ternary"]])

    def test_one_liners_comments_and_other_files_are_clean(self):
        self.write("src/a.ts", ONE_LINERS)
        self.write("notes.md", "a = b &&\n")
        self.write("lib/a.g.dart", "bool get x =>\n    a;\n")
        res = tool("agentflow-style", "master", cwd=self.repo)
        self.assertEqual((res.returncode, res.stdout.strip()), (0, "agentflow-style: sạch"))

    def test_only_added_lines_count(self):
        self.write("lib/a.dart", "bool get isX =>\n    a;\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "old")
        self.git("switch", "-q", "-c", "next")
        self.write("lib/a.dart", "bool get isX =>\n    a;\nfinal ok = a &&\n    b;\n")
        res = tool("agentflow-style", "feat", cwd=self.repo)
        self.assertEqual(res.returncode, 1)
        self.assertIn("lib/a.dart:3  logic", res.stdout)
        self.assertNotIn("lib/a.dart:1", res.stdout)

    def test_head_mode_reads_commits_not_the_working_tree(self):
        self.write("src/b.ts", WRAPPED)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "feat")
        self.write("src/c.ts", WRAPPED)
        res = tool("agentflow-style", "master", "feat", cwd=self.repo)
        self.assertEqual(res.returncode, 1)
        self.assertIn("src/b.ts:1", res.stdout)
        self.assertNotIn("src/c.ts", res.stdout)

    def test_bad_ref_and_usage(self):
        self.assertEqual(tool("agentflow-style", "nope", cwd=self.repo).returncode, 2)
        self.assertEqual(tool("agentflow-style", cwd=self.repo).returncode, 2)


class McpHeaders(RepoCase):
    def test_settings_file_token_is_ignored(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w") as fh:
            json.dump({"env": {"GITHUB_TOKEN": "abc"}}, fh)
        out = json.loads(tool("mcp-headers.py", cwd=self.repo).stdout)
        self.assertNotIn("Authorization", out)
        self.assertIn("projects", out["X-MCP-Toolsets"])

    def test_token_from_env(self):
        self.assertEqual(json.loads(tool("mcp-headers.py", cwd=self.repo, env={"GH_TOKEN": "xyz"}).stdout)["Authorization"], "Bearer xyz")

    def test_stdout_stays_json_without_token(self):
        out = json.loads(tool("mcp-headers.py", cwd=self.repo).stdout)
        self.assertNotIn("Authorization", out)

    def test_every_tool_family_the_prompts_use_is_enabled(self):
        toolsets = json.loads(tool("mcp-headers.py", cwd=self.repo).stdout)["X-MCP-Toolsets"].split(",")
        for name in ("context", "issues", "pull_requests", "projects", "actions"):
            self.assertIn(name, toolsets)


E2E_CONFIG = """schema: 5
surfaces:
  backend:
    path: "backend/"
  web:
    path: "web/"
    platform: "Web"
    e2e_dir: ".maestro"
  mobile:
    path: "mobile/"
    platform: "Mobile"
    e2e_dir: ".maestro"
    install: "flutter build apk"
e2e_map:
  "backend/services/billing/**": [pay]
run:
  max_regression: 3
"""
FAKE_MAESTRO = """#!/bin/sh
for a; do f=$a; done
sleep 0.3
case "$f" in *bad*) echo 'Assert that "Done" is visible... FAILED'; exit 1;; esac
echo ok
"""


class E2E(RepoCase):
    """agentflow-e2e: which existing flows a change re-runs (and why), and detached runs awaited in short steps."""

    def setUp(self):
        super().setUp()
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.env = {"AGENTFLOW_E2E_TMP": self.out.name}
        files = {
            "agentflow.yaml": E2E_CONFIG,
            "web/.maestro/af-42-tc1-new.yaml": "url: x\ntags: [af-42]\n---\n- tapOn:\n    id: settings-language\n",
            "web/.maestro/settings.yaml": "url: x\ntags: [account]\n---\n- tapOn:\n    id: settings-language\n",
            "web/.maestro/inbox.yaml": "url: x\ntags:\n  - account\n---\n- runScript:\n    file: scripts/inbox.js\n",
            "web/.maestro/scripts/inbox.js": "var r = http.get(api + '/notification/private/inbox')\n",
            "web/.maestro/pay.yaml": "url: x\ntags: [pay]\n---\n- launchApp\n",
            "web/.maestro/shared/sign-in.yaml": "url: x\n---\n- tapOn:\n    id: auth-submit\n",
            "mobile/.maestro/settings.yaml": "appId: x\ntags: [account]\n---\n- tapOn:\n    id: settings-language\n",
            "mobile/.maestro/pay.yaml": "appId: x\ntags: [pay]\n---\n- launchApp\n",
            "web/src/settings.tsx": "export const A = 1\n",
            "web/src/auth.tsx": "export const B = 1\n",
            "backend/services/notification/src/inbox.ts": "export const C = 1\n",
            "backend/services/billing/src/pay.ts": "export const D = 1\n",
        }
        for n in range(5):  # a subflow most flows use says nothing about which flow a change hits
            files["web/.maestro/home-%d.yaml" % n] = "url: x\n---\n- runFlow: shared/sign-in.yaml\n"
        for rel, text in files.items():
            self.write(rel, text)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        self.git("switch", "-q", "-c", "feat")

    git = Style.git
    write = Style.write

    def select(self, *args):
        res = tool("agentflow-e2e", "select", *args, cwd=self.repo, env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        return json.loads(res.stdout)

    def change(self, rel, text):
        self.write(rel, text)
        self.git("commit", "-q", "-am", "change")

    def flows(self, out):
        return {r["flow"]: r["why"] for r in out["regression"]}

    def test_ticket_flows_apart_and_id_hits_only_its_own_surface(self):
        self.change("web/src/settings.tsx", "export const A = <b data-testid='settings-language' />\n")
        out = self.select("--diff", "master...feat", "--issue", "42")
        self.assertEqual(out["ticket"], ["web/.maestro/af-42-tc1-new.yaml"])
        self.assertEqual(out["client"], ["web"])
        self.assertIsNone(out["only"])
        self.assertEqual(self.flows(out), {"web/.maestro/settings.yaml": ["id:settings-language←web/src/settings.tsx"]})

    def test_backend_only_diff_keeps_regression_on_web(self):
        self.change("backend/services/billing/src/pay.ts", "export const D = 2\n")
        self.change("backend/services/notification/src/inbox.ts", "export const C = 2\n")
        out = self.select("--diff", "master...feat")
        self.assertEqual((out["client"], out["only"]), ([], "web"))
        self.assertEqual(self.flows(out), {
            "web/.maestro/pay.yaml": ["map:pay←backend/services/billing/**"],
            "web/.maestro/inbox.yaml": ["api:/notification←backend/services/notification/src/inbox.ts"]})

    def test_common_subflow_is_not_evidence(self):
        self.change("web/src/auth.tsx", "export const B = <b data-testid='auth-submit' />\n")
        self.assertEqual(self.select("--diff", "master...feat")["regression"], [])

    def test_cap_moves_the_rest_to_over(self):
        out = self.select("--paths", "backend/services/billing/src/pay.ts", "backend/services/notification/src/x.ts", "--max", "1")
        self.assertEqual(len(out["regression"]), 1)
        self.assertEqual(out["regression"][0]["flow"], "web/.maestro/pay.yaml")  # map ranks above api
        self.assertEqual(out["over"], ["web/.maestro/inbox.yaml"])

    def test_paths_read_at_a_ref_not_the_working_tree(self):
        self.write("web/src/settings.tsx", "export const A = <b data-testid='settings-language' />\n")  # not committed
        self.assertEqual(self.select("--paths", "web/src/settings.tsx", "--ref", "master")["regression"], [])
        self.assertEqual(len(self.select("--paths", "web/src/settings.tsx", "--issue", "42")["regression"]), 1)

    def test_changed_flow_reruns(self):
        self.change("web/.maestro/settings.yaml", "url: x\ntags: [account]\n---\n- tapOn:\n    id: other\n")
        self.assertIn("changed:flow đổi trong diff", self.flows(self.select("--diff", "master...feat"))["web/.maestro/settings.yaml"])

    def maestro_env(self):
        fake = os.path.join(self.out.name, "bin")
        os.makedirs(fake, exist_ok=True)
        with open(os.path.join(fake, "maestro"), "w") as fh:
            fh.write(FAKE_MAESTRO)
        os.chmod(os.path.join(fake, "maestro"), 0o755)
        return dict(self.env, PATH=fake + ":/usr/bin:/bin")

    def run_flows(self, *flows, extra=(), name="web"):
        env = self.maestro_env()
        res = tool("agentflow-e2e", "run", "--issue", "42", "--dir", os.path.join(self.repo, "web"), "--name", name, *extra, *flows,
                   cwd=self.repo, env=env)
        return res, env

    def wait(self, env, *args):
        res = tool("agentflow-e2e", "wait", *args, cwd=self.repo, env=env)
        return res.returncode, json.loads(res.stdout)

    def test_run_is_detached_and_wait_reports_failures_without_secrets(self):
        self.write("web/.maestro/af-42-tc2-bad.yaml", "url: x\n---\n")
        secret = os.path.join(self.out.name, "e2e.env")
        with open(secret, "w") as fh:
            fh.write('export E2E_PASSWORD="s3cret"\n# note\n')
        res, env = self.run_flows(".maestro/af-42-tc1-new.yaml", ".maestro/af-42-tc2-bad.yaml",
                                  extra=("--repeat", "2", "--env-file", secret, "-e", "TOKEN_X=t0k"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["total"], 4)
        code, out = self.wait(env, "--issue", "42", "--max", "0.1")
        self.assertEqual((code, out["done"]), (2, False))
        code, out = self.wait(env, "--issue", "42", "--max", "30")
        self.assertEqual((code, out["done"]), (1, True))
        run = out["runs"][0]
        self.assertEqual((run["done"], run["total"]), (4, 4))
        self.assertEqual([(f["flow"], f["rep"]) for f in run["failed"]], [(".maestro/af-42-tc2-bad.yaml", 1), (".maestro/af-42-tc2-bad.yaml", 2)])
        self.assertIn("FAILED", run["failed"][0]["step"])
        folder = os.path.join(self.out.name, "af-42-e2e", "web")
        for name in os.listdir(folder):
            if name.endswith(".json"):
                with open(os.path.join(folder, name)) as fh:
                    text = fh.read()
                self.assertNotIn("s3cret", text)
                self.assertNotIn("t0k", text)

    def test_green_run_and_missing_flow(self):
        res, env = self.run_flows(".maestro/af-42-tc1-new.yaml")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.wait(env, "--issue", "42", "--max", "30")[0], 0)
        res, _ = self.run_flows(".maestro/nope.yaml")
        self.assertEqual(res.returncode, 3)
        self.assertEqual(json.loads(res.stdout)["missing"], [".maestro/nope.yaml"])
        self.assertEqual(self.wait(env, "--issue", "7", "--max", "0.1")[0], 3)

    def test_reset_drops_runs_of_an_earlier_turn(self):
        self.write("web/.maestro/af-42-tc2-bad.yaml", "url: x\n---\n")
        _, env = self.run_flows(".maestro/af-42-tc2-bad.yaml", name="mobile")  # an earlier turn, failed
        self.assertEqual(self.wait(env, "--issue", "42", "--max", "30")[0], 1)
        self.run_flows(".maestro/af-42-tc1-new.yaml")
        code, out = self.wait(env, "--issue", "42", "--max", "30")
        self.assertEqual((code, sorted(r["name"] for r in out["runs"])), (1, ["mobile", "web"]))  # without --reset it still counts
        self.run_flows(".maestro/af-42-tc1-new.yaml", extra=("--reset",))
        code, out = self.wait(env, "--issue", "42", "--max", "30")
        self.assertEqual((code, [r["name"] for r in out["runs"]]), (0, ["web"]))

    def start(self, issue, surface, *flows, extra=()):
        env = self.maestro_env()
        res = tool("agentflow-e2e", "run", "--issue", str(issue), "--dir", os.path.join(self.repo, surface), "--name", surface,
                   *extra, *flows, cwd=self.repo, env=env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return env

    def test_one_ticket_at_a_time_on_a_device_web_runs_side_by_side(self):
        flows = [".maestro/settings.yaml", ".maestro/pay.yaml"] * 3
        env = self.start(42, "mobile", *flows)
        self.start(43, "mobile", *flows)
        code, out = self.wait(env, "--issue", "43", "--name", "mobile", "--max", "0.5")
        self.assertEqual((code, out["runs"][0].get("queued"), out["runs"][0]["done"]), (2, "#42 mobile", 0))
        self.assertEqual(self.wait(env, "--issue", "42", "--name", "mobile", "--max", "30")[0], 0)
        code, out = self.wait(env, "--issue", "43", "--name", "mobile", "--max", "30")
        self.assertEqual((code, out["runs"][0]["done"], "queued" in out["runs"][0]), (0, 6, False))
        self.start(44, "web", ".maestro/af-42-tc1-new.yaml", ".maestro/settings.yaml")
        self.start(45, "web", ".maestro/af-42-tc1-new.yaml", ".maestro/settings.yaml")
        code, out = self.wait(env, "--issue", "45", "--name", "web", "--max", "0.2")
        self.assertNotIn("queued", out["runs"][0])
        for n in ("44", "45"):  # detached runners must end before the temp dir goes
            self.assertEqual(self.wait(env, "--issue", n, "--max", "30")[0], 0)

    def test_install_only_when_the_device_holds_another_build(self):
        count = os.path.join(self.out.name, "installs")
        self.write("agentflow.yaml", E2E_CONFIG.replace('install: "flutter build apk"', 'install: "echo x >> %s"' % count))
        self.write("mobile/lib/app.dart", "void main() {}\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "app")
        def installs():
            if not os.path.exists(count):
                return 0
            with open(count) as fh:
                return len(fh.read().split())

        def run(issue):
            env = self.start(issue, "mobile", ".maestro/settings.yaml", extra=("--install",))
            code, out = self.wait(env, "--issue", str(issue), "--name", "mobile", "--max", "30")
            self.assertEqual(code, 0, out)
            return out["runs"][0]["install"]
        self.assertEqual((run(42), installs()), ("ok", 1))
        self.assertEqual((run(42), installs()), ("skipped", 1))
        self.change("mobile/.maestro/settings.yaml", "appId: x\ntags: [account]\n---\n- tapOn:\n    id: other\n")
        self.assertEqual((run(43), installs()), ("skipped", 1))  # a flow change needs no new build
        self.change("mobile/lib/app.dart", "void main() { print(1); }\n")
        self.assertEqual((run(43), installs()), ("ok", 2))
        self.write("mobile/lib/app.dart", "void main() { print(2); }\n")  # uncommitted edit: never trust the record
        self.assertEqual((run(43), installs()), ("ok", 3))
        self.git("commit", "-q", "-am", "app 2")
        env = self.start(44, "mobile", extra=("--install",))  # build while the deploy runs, flows after
        self.assertEqual(self.wait(env, "--issue", "44", "--name", "mobile", "--max", "30")[0], 0)
        self.assertEqual((run(44), installs()), ("skipped", 4))

    def test_failed_install_is_the_failure_reported(self):
        self.write("agentflow.yaml", E2E_CONFIG.replace('install: "flutter build apk"', 'install: "echo no emulator >&2; exit 4"'))
        env = self.start(42, "mobile", ".maestro/settings.yaml", extra=("--install",))
        code, out = self.wait(env, "--issue", "42", "--name", "mobile", "--max", "30")
        run = out["runs"][0]
        self.assertEqual((code, run["install"], run["done"], run["failed"][0]["flow"], run["failed"][0]["step"]), (1, "failed", 0, "install", "no emulator"))
        res = tool("agentflow-e2e", "run", "--issue", "42", "--dir", os.path.join(self.repo, "web"), "--name", "web", "--install",
                   ".maestro/settings.yaml", cwd=self.repo, env=env)
        self.assertEqual(res.returncode, 3)  # web has no install command

    def test_wait_log_until_exit_line(self):
        log = os.path.join(self.out.name, "build.log")
        with open(log, "w") as fh:
            fh.write("building\n")
        code, out = self.wait(self.env, "--log", log, "--max", "0.1")
        self.assertEqual((code, out["done"]), (2, False))
        with open(log, "a") as fh:
            fh.write("error: x\nexit 1\n")
        code, out = self.wait(self.env, "--log", log, "--max", "5")
        self.assertEqual((code, out["exit"]), (1, 1))
        self.assertIn("error: x", out["tail"])


class Base(unittest.TestCase):
    """agentflow-base: a ticket's worktree comes from origin, whatever the person does in the main checkout meanwhile."""

    CONFIG = "schema: 5\ngit:\n  base: null\n  protected: [production]\nstaging:\n  branch: staging\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        top = os.path.realpath(self.tmp.name)
        self.origin, self.main, self.other = (os.path.join(top, n) for n in ("o.git", "main", "other"))
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", self.origin], check=True)
        self.git(top, "clone", "-q", self.origin, self.main)
        self.write(self.main, "agentflow.yaml", self.CONFIG)
        self.write(self.main, "a.txt", "a\n")
        self.commit(self.main, "init")
        self.git(self.main, "push", "-q", "origin", "master", "master:staging")
        self.git(self.main, "remote", "set-head", "origin", "master")
        self.git(top, "clone", "-q", self.origin, self.other)  # someone else pushing to the same branches
        self.wt = os.path.join(self.main, ".claude", "worktrees", "af-7")

    def git(self, cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    def write(self, cwd, rel, text):
        with open(os.path.join(cwd, rel), "w") as fh:
            fh.write(text)

    def commit(self, cwd, msg):
        self.git(cwd, "add", "-A")
        self.git(cwd, "commit", "-qm", msg)

    def base(self, *args, code=0):
        res = tool("agentflow-base", *args, cwd=self.main, env={"GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t",
                   "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        return json.loads(res.stdout)

    def push_from_other(self, branch, rel):
        self.git(self.other, "fetch", "-q", "origin")
        self.git(self.other, "switch", "-q", "-C", branch, "origin/" + branch)
        self.write(self.other, rel, rel + "\n")
        self.commit(self.other, rel)
        self.git(self.other, "push", "-q", "origin", branch)

    def test_new_work_starts_detached_at_the_fresh_base_without_a_local_branch(self):
        self.push_from_other("master", "newer.txt")  # the base moved since the main checkout last fetched
        self.git(self.main, "switch", "-q", "-c", "user/wip")
        self.write(self.main, "a.txt", "dirty\n")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["path"], out["sync"], out["remote"], out["ahead"], out["behind_base"]), (self.wt, "created", False, 0, 0))
        self.assertEqual(out["head"], self.git(self.main, "rev-parse", "origin/master"))
        self.assertTrue(os.path.isfile(os.path.join(self.wt, "newer.txt")))
        self.assertEqual(self.git(self.wt, "status", "--porcelain"), "")  # the person's dirty edit stays where it is
        self.assertEqual(self.git(self.main, "branch", "--list", "feat/7-x"), "")
        self.assertEqual(subprocess.run(["git", "check-ignore", "-q", ".claude/worktrees/"], cwd=self.main).returncode, 0)
        self.assertEqual(self.git(self.main, "status", "--porcelain"), "M a.txt")
        self.write(self.wt, "b.txt", "b\n")
        self.commit(self.wt, "b")
        self.git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/feat/7-x")
        self.assertEqual(self.git(self.main, "ls-remote", "origin", "feat/7-x").split()[0], self.git(self.wt, "rev-parse", "HEAD"))

    def test_the_person_checking_out_the_ticket_branch_does_not_stop_the_agent(self):
        self.base("worktree", "7", "--branch", "feat/7-x")
        self.write(self.wt, "b.txt", "b\n")
        self.commit(self.wt, "b")
        self.git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/feat/7-x")
        self.git(self.main, "fetch", "-q", "origin")
        self.git(self.main, "switch", "-q", "feat/7-x")  # git refuses this when a worktree holds the branch
        self.push_from_other("feat/7-x", "c.txt")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["sync"], out["remote"], out["ahead"]), ("fast_forward", True, 0))
        self.assertTrue(os.path.isfile(os.path.join(self.wt, "c.txt")))
        self.assertEqual(self.git(self.main, "rev-parse", "--abbrev-ref", "HEAD"), "feat/7-x")

    def test_existing_worktree_keeps_edits_and_unpushed_commits(self):
        self.base("worktree", "7", "--branch", "feat/7-x")
        self.write(self.wt, "b.txt", "b\n")
        self.commit(self.wt, "b")
        self.git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/feat/7-x")
        self.write(self.wt, "d.txt", "d\n")
        self.commit(self.wt, "d")  # a run died before pushing
        self.write(self.wt, "e.txt", "e\n")  # and before committing
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["sync"], out["dirty"], out["ahead"]), ("ahead", True, 1))
        self.push_from_other("feat/7-x", "c.txt")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual(out["sync"], "diverged")
        self.assertIn("merge origin/feat/7-x", out["next"])
        self.git(self.wt, "add", "-A")
        self.git(self.wt, "commit", "-qm", "e")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["sync"], out["dirty"], out["ahead"]), ("merged", False, 3))
        self.assertTrue(all(os.path.isfile(os.path.join(self.wt, f)) for f in ("b.txt", "c.txt", "d.txt", "e.txt")))

    def test_new_work_kept_until_pushed_and_base_drift_reported(self):
        self.base("worktree", "7", "--branch", "feat/7-x")
        self.write(self.wt, "b.txt", "b\n")
        self.commit(self.wt, "b")
        self.push_from_other("master", "newer.txt")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["sync"], out["remote"], out["ahead"], out["behind_base"]), ("kept", False, 1, 1))

    def test_new_work_not_started_yet_moves_to_the_fresh_base(self):
        self.base("worktree", "7", "--branch", "feat/7-x")  # an earlier run stopped before its first edit
        self.push_from_other("master", "newer.txt")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["sync"], out["head"], out["behind_base"]), ("fresh", self.git(self.main, "rev-parse", "origin/master"), 0))

    def test_base_from_git_base(self):
        self.git(self.main, "push", "-q", "origin", "master:main")
        self.write(self.main, "agentflow.yaml", self.CONFIG.replace("base: null", "base: main"))
        self.push_from_other("main", "on-main.txt")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["base"], out["head"]), ("main", self.git(self.main, "rev-parse", "origin/main")))
        self.assertIn("error", self.base("worktree", "8", "--branch", "main", code=1))

    def test_worktree_deleted_by_hand_is_recreated_and_other_worktrees_are_left_alone(self):
        mine = os.path.join(os.path.dirname(self.main), "mine")
        self.git(self.main, "worktree", "add", "-q", "--detach", mine, "origin/master")  # the person's own, now out of reach
        self.base("worktree", "7", "--branch", "feat/7-x")
        shutil.rmtree(self.wt)
        shutil.rmtree(mine)
        self.assertEqual(self.base("worktree", "7", "--branch", "feat/7-x")["sync"], "created")
        self.assertIn(mine, self.git(self.main, "worktree", "list", "--porcelain"))  # never pruned by agentflow
        shutil.rmtree(self.wt)
        self.assertEqual(self.base("clean", "--issue", "7"), {"removed": [self.wt], "kept": []})
        self.assertIn(mine, self.git(self.main, "worktree", "list", "--porcelain"))

    def test_other_branch_only_over_a_worktree_that_holds_nothing_unpushed(self):
        self.base("worktree", "7", "--branch", "feat/7-x")
        self.write(self.wt, "b.txt", "b\n")
        self.commit(self.wt, "b")
        self.assertIn("feat/7-x", self.base("worktree", "7", "--branch", "fix/7-y", code=1)["error"])
        self.git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/feat/7-x")
        out = self.base("worktree", "7", "--branch", "fix/7-y")
        self.assertEqual((out["sync"], out["head"]), ("switched", self.git(self.main, "rev-parse", "origin/master")))

    def test_worktree_of_the_old_dev_on_a_local_branch_is_detached_in_place(self):
        self.git(self.main, "worktree", "add", "-q", self.wt, "-b", "feat/7-x", "origin/master")
        self.write(self.wt, "b.txt", "b\n")
        self.commit(self.wt, "b")
        local = self.git(self.main, "rev-parse", "feat/7-x")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["sync"], out["head"], out["ahead"]), ("kept", local, 1))
        self.assertEqual(self.git(self.wt, "rev-parse", "--abbrev-ref", "HEAD"), "HEAD")
        self.git(self.main, "switch", "-q", "feat/7-x")  # free for the person now
        self.assertEqual(self.git(self.main, "rev-parse", "feat/7-x"), local)

    def test_refuses_base_protected_staging_and_bad_names(self):
        for branch in ("master", "production", "staging", "-x", "a..b"):
            with self.subTest(branch):
                self.assertIn("error", self.base("worktree", "7", "--branch=" + branch, code=1))
        self.assertFalse(os.path.exists(self.wt))

    def test_single_branch_clone_still_sees_the_ticket_branch(self):
        self.push_from_other("master", "x.txt")
        self.git(self.other, "push", "-q", "origin", "master:feat/7-x")
        self.git(self.main, "config", "remote.origin.fetch", "+refs/heads/master:refs/remotes/origin/master")
        out = self.base("worktree", "7", "--branch", "feat/7-x")
        self.assertEqual((out["remote"], out["head"]), (True, self.git(self.main, "rev-parse", "refs/remotes/origin/feat/7-x")))

    def test_clean_never_drops_unpushed_work(self):
        self.base("worktree", "7", "--branch", "feat/7-x")
        self.write(self.wt, "b.txt", "b\n")
        self.commit(self.wt, "b")
        staging = self.wt + "-staging"
        self.git(self.main, "worktree", "add", "-q", "--detach", staging, "origin/staging")
        self.write(staging, "s.txt", "s\n")
        self.assertEqual(self.base("clean", "--issue", "7", "--staging"), {"removed": [staging], "kept": [self.wt]})
        self.git(self.wt, "push", "-q", "origin", "HEAD:refs/heads/feat/7-x")
        self.assertEqual(self.base("clean", "--issue", "7", "--issue", "8"), {"removed": [self.wt], "kept": []})


class ResultCheck(unittest.TestCase):
    def check(self, message, agent="agentflow:dev", active=False):
        payload = {"agent_type": agent, "last_assistant_message": message, "stop_hook_active": active}
        res = tool("result-check.py", stdin=json.dumps(payload))
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout.strip()

    def test_valid(self):
        for message in ("Xong.\n\nRESULT: in_review · ok\nPR: #5 @abc\nNOTE: x", "RESULT: ready · needs_info", "RESULT: in_qc · waiting_human", "RESULT: in_progress · verify", "RESULT: in_qc · blocked", "RESULT: in_progress · escalated", "RESULT: in_review · abort"):
            with self.subTest(message):
                self.assertEqual(self.check(message), "")

    def test_invalid_is_sent_back(self):
        for message in ("Tôi đã xong.", "", "RESULT: in_review", "RESULT: in_review · done", "RESULT: nowhere · ok", "result: ready · ok"):
            with self.subTest(message):
                self.assertEqual(json.loads(self.check(message))["decision"], "block")

    def test_blocks_only_once(self):
        self.assertEqual(self.check("không có", active=True), "")

    def test_other_agents_untouched(self):
        self.assertEqual(self.check("không có", agent="Explore"), "")
        self.assertEqual(self.check("không có", agent=""), "")

    def test_broken_stdin(self):
        self.assertEqual(tool("result-check.py", stdin="not json").returncode, 0)


if __name__ == "__main__":
    unittest.main()
