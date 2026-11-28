#!/usr/bin/env python3
"""agentflow-settings, agentflow-journal, agentflow-notify, agentflow-base, agentflow-audit, mcp-headers, result-check: run as
the user runs them."""

import json
import os
import re
import shutil
import stat
import struct
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

    def rev(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, check=True).stdout.strip()

    def baseline(self, surface, *flows):
        env = self.maestro_env()
        res = tool("agentflow-e2e", "run", "--baseline", "--issue", "42", "--dir", os.path.join(self.repo, surface), "--name", surface,
                   *flows, cwd=self.repo, env=env)
        out = json.loads(res.stdout)
        if out.get("run"):  # detached runner must end before the temp dir goes
            self.wait(env, "--issue", "42", "--max", "30")
        return res.returncode, out

    def test_baseline_runs_on_a_build_without_the_change(self):
        self.write("agentflow.yaml", E2E_CONFIG + "staging:\n  branch: staging\n")
        self.git("commit", "-q", "-am", "staging key")
        base = self.rev()
        self.git("update-ref", "refs/remotes/origin/master", base)
        self.git("update-ref", "refs/remotes/origin/staging", base)
        self.change("web/.maestro/af-42-tc1-new.yaml", "url: x\ntags: [af-42]\n---\n- tapOn:\n    id: b\n")
        self.assertEqual(self.baseline("web", ".maestro/af-42-tc1-new.yaml")[1]["baseline"], "skipped")  # flows only
        self.change("web/src/settings.tsx", "export const A = 2\n")
        code, out = self.baseline("web", ".maestro/af-42-tc1-new.yaml")
        self.assertEqual((code, out["run"], out["baseline"]), (0, "web-baseline", base))
        self.git("update-ref", "refs/remotes/origin/staging", self.rev())  # staging merged the ticket
        code, out = self.baseline("web", ".maestro/af-42-tc1-new.yaml")
        self.assertEqual(out["baseline"], "skipped")
        self.assertIn("staging đã có commit", out["why"])
        record = os.path.join(self.out.name, "af-device-default.installed")
        self.assertIn("chưa có bản cài", self.baseline("mobile", ".maestro/settings.yaml")[1]["why"])
        with open(record, "w") as fh:
            fh.write("mobile %s" % base)
        self.assertEqual(self.baseline("mobile", ".maestro/settings.yaml")[1]["baseline"], base)
        with open(record, "w") as fh:
            fh.write("mobile %s" % self.rev())
        self.assertIn("bản đang cài đã có commit", self.baseline("mobile", ".maestro/settings.yaml")[1]["why"])
        res, _ = self.run_flows(".maestro/af-42-tc1-new.yaml", extra=("--baseline", "--install"))
        self.assertEqual(res.returncode, 3)

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


AUDIT_CONFIG = """schema: 5
labels:
  platform: {web: "platform:web", mobile: "platform:mobile"}
surfaces:
  web:
    path: "web/"
    platform: "web"
    e2e_dir: ".maestro"
forbidden: ["web/src/secret/**"]
"""
SAME = "".join("  const step%d = total * %d + offset;\n" % (i, i) for i in range(10))
AUDIT_FILES = {
    "agentflow.yaml": AUDIT_CONFIG,
    "web/src/features/cart/cart.ts": "import { pay } from '../pay/pay'\n// TODO: tách giỏ hàng\nexport function cart() { return pay() }\n",
    "web/src/features/pay/pay.ts": "import { cart } from '../cart/cart'\nexport function pay() {\n  try { return cart() } catch (e) {}\n  console.log('paid')\n}\n",
    "web/src/features/cart/format.ts": "export function a(total, offset) {\n" + SAME + "}\n",
    "web/src/features/pay/format.ts": "export function b(total, offset) {\n" + SAME + "}\n",
    "web/src/domain/order.ts": "import { api } from '../data/api'\nexport const order = api\n",
    "web/src/data/api.ts": "export const api = 'https://staging.example.com/v1'\n",
    "web/src/features/cart/view.tsx": "export const V = () => <button data-testid=\"cart_checkout\" />\n",
    "web/src/auth/login.tsx": "export const L = () => <form><input data-testid=\"login_email\" /><input data-testid=\"login_password\" /></form>\n",
    "web/src/secret/keys.ts": "".join("export const k%d = %d\n" % (i, i) for i in range(400)),
    "web/.maestro/shared/login.yaml": "url: ${STAGING_URL}\n---\n- tapOn:\n    id: login_email\n- inputText: ${EMAIL}\n- tapOn:\n    id: login_password\n- inputText: hunter2\n",
    "web/.maestro/checkout.yaml": "url: ${STAGING_URL}\nname: Checkout\ntags: [smoke, pay]\n---\n- runFlow: shared/login.yaml\n- tapOn:\n    id: cart_checkout\n- assertVisible:\n    id: pay_done\n",
    "web/.maestro/profile.yaml": "url: ${STAGING_URL}\n---\n- tapOn: \"Profile\"\n- tapOn:\n    point: \"50%,50%\"\n    optional: true\n",
    "web/.maestro/config.yaml": "flows:\n  - \"*.yaml\"\n",
}
QA_FINDINGS = """# audit qa · o/r @abc1234 · 2026-11-24
Phạm vi: web · Đã chạy: 2 flow · Không chạy được: mobile (không có thiết bị)

## F1. Báo lỗi khi bấm thanh toán lúc mất mạng
- fp: qa/checkout/offline-no-feedback
- type: Bug
- sev: cao
- effort: S
- platform: web
- evidence: audit-checkout-offline.png (state: bấm Thanh toán, mất mạng)

### Các bước tái hiện
1. Đăng nhập, thêm hàng, tắt mạng, bấm Thanh toán
### Tiêu chí nghiệm thu
- [ ] Khi mất mạng và bấm Thanh toán, thì người dùng thấy thông báo thử lại trong 1 giây

## F2. Phủ automation cho luồng hồ sơ
- fp: qa/profile/no-flow
- type: Task
- sev: thấp
- effort: M
- evidence: profile.yaml: no_assert, optional, point

### Tiêu chí nghiệm thu
- [ ] Flow hồ sơ assert tên người dùng sau khi lưu

## F3. Báo lỗi khi bấm thanh toán lúc mất mạng (lặp)
- fp: qa/checkout/offline-no-feedback
- type: Bug
- sev: vừa
- effort: S
- evidence: lần chạy thứ hai

### Tiêu chí nghiệm thu
- [ ] như F1

## Ngoài danh sách
- 4 mục thấp về khoảng cách chữ
"""
ARCH_FINDINGS = """# audit arch · o/r @abc1234 · 2026-11-24

## F1. Cắt vòng phụ thuộc giữa giỏ hàng và thanh toán
- fp: arch/features-cart-pay/cycle
- type: Task
- sev: vừa
- effort: M
- evidence: scan cycles: web/src/features/cart ↔ web/src/features/pay
- regressed: #12

### Tiêu chí nghiệm thu
- [ ] `agentflow-audit scan web` không còn cycle cart ↔ pay

## F2. Mục viết sai
- fp: Arch/Bad Line 12
- type: Chore
- sev: urgent
- effort: XL
- platform: desktop
- evidence: x

không có tiêu chí
"""


class Audit(RepoCase):
    """agentflow-audit: the numbers that tell the auditor where to read, and the findings file the checklist files."""

    git = Style.git
    write = Style.write

    def setUp(self):
        super().setUp()
        for rel, text in AUDIT_FILES.items():
            self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        for n in range(3):  # cart and pay always change together, from two folders
            for rel in ("web/src/features/cart/cart.ts", "web/src/features/pay/pay.ts"):
                with open(os.path.join(self.repo, rel), "a", encoding="utf-8") as fh:
                    fh.write("// change %d\n" % n)
            self.git("commit", "-q", "-am", "change %d" % n)

    def audit(self, *args, code=0):
        res = tool("agentflow-audit", *args, cwd=self.repo)
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        return res.stdout

    def test_scan_points_at_cycles_upward_imports_duplicates_and_hotspots(self):
        out = json.loads(self.audit("scan", "--top", "5"))
        self.assertEqual(out["paths"], ["web"])
        self.assertEqual([c["modules"] for c in out["cycles"]], [["web/src/features/cart", "web/src/features/pay"]])
        self.assertEqual(out["cycles"][0]["edges"][0]["at"], "web/src/features/cart/cart.ts:1")
        self.assertEqual(out["upward"]["examples"], [{"rule": "domain→data", "at": "web/src/domain/order.ts:1", "to": "web/src/data/api.ts"}])
        self.assertEqual(out["duplicates"]["blocks"], 1)
        self.assertEqual(out["duplicates"]["top"][0]["lines"], 10)
        self.assertEqual({h["path"] for h in out["hotspots"]}, {"web/src/features/cart/cart.ts", "web/src/features/pay/pay.ts"})
        self.assertEqual(out["coupling"], [{"a": "web/src/features/cart/cart.ts", "b": "web/src/features/pay/pay.ts", "together": 4, "ratio": 1.0}])
        self.assertEqual(out["smells"]["empty_catch"]["at"], ["web/src/features/pay/pay.ts:3"])
        self.assertEqual(out["smells"]["debug_print"]["count"], 1)
        self.assertEqual(out["smells"]["hardcoded_env_url"]["at"], ["web/src/data/api.ts:1"])
        self.assertEqual(out["markers"]["count"], 1)
        self.assertNotIn("web/src/secret/keys.ts", json.dumps(out))  # forbidden: never opened, never listed

    def test_scan_of_one_folder(self):
        out = json.loads(self.audit("scan", "web/src/domain", "web/src/data"))
        self.assertEqual(out["cycles"], [])
        self.assertEqual(out["upward"]["count"], 1)
        self.assertEqual(sorted(out["size"]), ["ts"])

    def test_flows_lint_and_stale_ids(self):
        out = json.loads(self.audit("flows"))
        web = out["surfaces"][0]
        self.assertEqual((web["surface"], web["dir"], web["flows"], web["subflows"]), ("web", "web/.maestro", 2, 1))
        self.assertEqual(web["tags"], {"smoke": 1, "pay": 1})
        self.assertEqual([s["id"] for s in web["stale_ids"]], ["pay_done"])
        self.assertEqual(web["issues"]["no_assert"], ["web/.maestro/profile.yaml"])
        self.assertEqual(web["issues"]["credential_literal"], ["web/.maestro/shared/login.yaml"])
        by_file = {f["file"]: f for f in out["flows"]}
        self.assertEqual(sorted(by_file["web/.maestro/profile.yaml"]["issues"]), ["no_assert", "no_tags", "optional", "point", "text_selectors"])
        self.assertEqual(by_file["web/.maestro/checkout.yaml"]["issues"], [])
        self.assertNotIn("web/.maestro/config.yaml", by_file)  # workspace config, not a flow

    def test_ids_built_at_run_time_labels_and_vacuous_asserts(self):
        self.write("web/src/features/cart/list.tsx", "export const R = (i) => <li data-testid={`cart-row-${i}`} />\n")
        self.write("web/src/ui/stepper.tsx", "export const S = ({ id }) => <button data-testid={`${id}-increase`} />\n")
        self.write("web/.maestro/cart.yaml", "url: ${STAGING_URL}\ntags: [cart]\n---\n- tapOn:\n    id: cart-row-0\n"
                   "- tapOn: {id: cart-qty-increase}\n- assertNotVisible:\n    id: cart-legacy-banner\n- extendedWaitUntil:\n"
                   "    notVisible:\n      id: cart_checkout\n    timeout: 5000\n- assertVisible:\n    id: \"Remove item 2\"\n"
                   "- assertVisible:\n    id: cart-gone-for-good\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "cart flow")
        web = json.loads(self.audit("flows"))["surfaces"][0]
        self.assertEqual([s["id"] for s in web["stale_ids"]], ["cart-gone-for-good", "pay_done"])
        self.assertEqual(web["vacuous_ids"], [{"id": "cart-legacy-banner", "flows": ["web/.maestro/cart.yaml"]}])
        cart = next(f for f in json.loads(self.audit("flows"))["flows"] if f["file"] == "web/.maestro/cart.yaml")
        self.assertNotIn("text_selectors", cart["issues"])  # one label among five ids

    def test_flows_without_surfaces_find_specs_by_folder_name(self):
        self.write("agentflow.yaml", "schema: 5\n")
        self.write("e2e/home.spec.ts", "import { test, expect } from '@playwright/test'\ntest.only('home', async ({ page }) => {\n"
                                       "  await page.waitForTimeout(3000)\n  await page.locator('xpath=//div[2]').click()\n})\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "specs")
        out = json.loads(self.audit("flows"))
        spec = next(s for s in out["specs"] if s["file"] == "e2e/home.spec.ts")
        self.assertEqual(spec["framework"], "playwright")
        self.assertEqual(sorted(spec["issues"]), ["hard_wait", "no_assert", "only", "xpath_or_nth"])

    def test_findings_merge_rank_and_report_errors(self):
        self.write("out/qa.md", QA_FINDINGS)
        self.write("out/arch.md", ARCH_FINDINGS)
        out = json.loads(self.audit("findings", "out/qa.md", "out/arch.md", code=1))
        self.assertEqual([f["id"] for f in out["findings"]], ["qa:F1", "arch:F1", "qa:F2"])
        self.assertEqual(out["findings"][0]["also"], ["qa:F3"])  # same fp twice: the higher sev stays
        self.assertEqual(out["findings"][0]["platform"], ["web"])
        self.assertEqual(out["findings"][1]["regressed"], "#12")
        self.assertEqual(out["by_sev"], {"cao": 1, "vừa": 1, "thấp": 1})
        self.assertNotIn("body", out["findings"][0])
        [error] = out["errors"]
        self.assertEqual(error["id"], "arch:F2")
        for part in ("type phải", "sev phải", "effort phải", "fp `Arch/Bad Line 12`", "platform desktop", "thiếu tiêu chí"):
            self.assertIn(part, error["error"])

    def test_findings_body_is_the_ticket_only(self):
        self.write("out/qa.md", QA_FINDINGS)
        body = self.audit("findings", "out/qa.md", "--body", "qa:F2")
        self.assertTrue(body.startswith("### Tiêu chí nghiệm thu"))
        self.assertNotIn("Ngoài danh sách", body)
        self.assertNotIn("- fp:", body)
        self.assertEqual(json.loads(self.audit("findings", "out/qa.md", "--body", "qa:F9", code=3))["error"][:9], "không có ")

    def test_findings_need_the_lens_line(self):
        self.write("out/x.md", QA_FINDINGS.split("\n", 1)[1])
        out = json.loads(self.audit("findings", "out/x.md", code=1))
        self.assertIn("thiếu dòng đầu", out["errors"][0]["error"])


UX_FINDINGS = """# audit ux · o/r @abc1234 · 2026-11-24

## F1. Góc nhìn thiết kế cho lỗi thanh toán mất mạng
- extends: qa:F1
- evidence: audit-checkout-offline.png — banner lỗi đỏ chữ 11px, tương phản 2.8:1
- platform: web
- role: member

### Góc nhìn UI/UX
Banner lỗi dùng màu và cỡ chữ lệch token `danger`.

## F2. Thống nhất bo góc nút theo token radius
- fp: ux/buttons/radius-mismatch
- type: Improvement
- sev: thấp
- effort: S
- evidence: audit-home-default.png, audit-pay-default.png — 4px và 12px

### Tiêu chí nghiệm thu
- [ ] Mọi nút chính dùng `radius.md`

## F3. Trỏ vào mục không có
- extends: qa:F9
- evidence: x

### Góc nhìn
không có đích
"""
ARCH_VIEW = """# audit arch · o/r @abc1234 · 2026-11-24

## F1. Nguyên nhân gốc lỗi thanh toán mất mạng
- extends: qa:F2
- sev: cao
- evidence: web/src/features/pay/pay.ts:3 — catch rỗng

### Nguyên nhân gốc (Engineering)
`pay()` nuốt lỗi mạng.
"""
MAP_FILES = {
    "agentflow.yaml": AUDIT_CONFIG.replace("forbidden:", "staging:\n  branch: staging\n  notes: \"Tài khoản ở secret/staging/, coach dùng E2E_COACH_EMAIL\"\nforbidden:"),
    "web/package.json": '{"dependencies": {"next": "15.0.0"}}\n',
    "web/src/app/(main)/page.tsx": "export default function P() { return null }\n",
    "web/src/app/(main)/orders/[orderId]/page.tsx": "export default function P() { return null }\n",
    "web/src/app/login/page.tsx": "export default function P() { return null }\n",
    "web/src/app/api/health/route.ts": "export async function GET() { return Response.json({ ok: true }) }\n",
    "web/src/features/admin/guard.ts": "export const canSee = (user) => user.role === 'admin' || isOwner(user)\n"
                                        "export enum UserRole { Admin = 'admin', Member = 'member' }\n"
                                        "export enum SlotRole { Warmup = 'warmup' }\n",
    "backend/src/routes/orders.router.ts": "router.get('/orders', requireAuth, list)\nrouter.post('/orders/:id/refund', refund)\n",
    "mobile/lib/routes.dart": "class R {\n  static const String home = '/';\n  static const String gym = '/gym/detail';\n}\n"
                              "final r = GoRouter(routes: [GoRoute(path: R.home, builder: (c, s) => const Home()),\n"
                              "  GoRoute(path: gym.substring(1), builder: (c, s) => const Gym())]);\n",
    "web/.maestro/admin.yaml": "url: ${STAGING_URL}\ntags: [admin]\n---\n- inputText: ${E2E_ADMIN_EMAIL}\n- assertVisible:\n    id: x\n",
}


class AuditMap(RepoCase):
    """agentflow-audit map/plan/ledger: the whole product, every role, and a coverage map that carries over runs."""

    git = Style.git
    write = Style.write

    def setUp(self):
        super().setUp()
        for rel, text in MAP_FILES.items():
            self.write(rel, text)
        self.write("secret/staging/web.env", "E2E_ADMIN_EMAIL=a@x\nE2E_ADMIN_PASSWORD=hunter2\nE2E_MEMBER_EMAIL=m@x\nSTAGING_URL=x\n")
        self.git("add", "-A", ":!secret")
        self.git("commit", "-q", "-m", "base")
        self.out = os.path.join(self.repo, "out")
        os.makedirs(self.out)

    def audit(self, *args, code=0):
        res = tool("agentflow-audit", *args, cwd=self.repo)
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        return res.stdout

    def save(self, name, text):
        path = os.path.join(self.out, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_map_lists_screens_endpoints_roles_and_accounts(self):
        out = json.loads(self.audit("map", "web", "backend", "mobile"))
        self.assertEqual(sorted(s["area"] for s in out["screens"] if s["at"].startswith("web/")), ["/", "/login", "/orders/:orderId"])
        self.assertEqual(sorted(s["area"] for s in out["screens"] if s["at"].startswith("mobile/")), ["/", "/gym/detail"])
        by_path = {(e["method"], e["path"]): e for e in out["endpoints"]}
        self.assertTrue(by_path[("GET", "/orders")]["auth_hint"])
        self.assertFalse(by_path[("POST", "/orders/:p/refund")]["auth_hint"])
        self.assertIn(("GET", "/api/health"), by_path)
        self.assertEqual(out["unguarded"][0]["path"], "/api/health")
        roles = [r["role"] for r in out["roles"]]
        self.assertEqual(roles[:2], ["admin", "member"])
        self.assertIn("owner", roles)
        self.assertIn("guest", roles)  # a login screen: someone not signed in
        self.assertNotIn("warmup", roles)  # SlotRole names no actor
        self.assertEqual(out["accounts"]["admin"], ["E2E_ADMIN_EMAIL", "E2E_ADMIN_PASSWORD"])
        self.assertEqual(out["accounts"]["coach"], ["E2E_COACH_EMAIL"])  # named by the notes
        self.assertEqual(out["env_files"], [os.path.join(self.repo, "secret/staging/web.env")])
        self.assertIn("owner", out["missing_accounts"])
        self.assertNotIn("hunter2", json.dumps(out))  # key names only
        kinds = {a["area"]: a["kind"] for a in out["areas"]}
        self.assertEqual(kinds["API orders"], "api")
        self.assertEqual(kinds["web /orders/:orderId"], "ui")

    def test_map_groups_screens_when_the_table_would_be_too_long(self):
        out = json.loads(self.audit("map", "--max-areas", "4", "web"))
        self.assertLessEqual(len(out["areas"]), 4)
        self.assertIn("/orders", [a["area"] for a in out["areas"]])

    def test_plan_puts_fix_checks_and_changed_areas_first(self):
        amap = self.save("map.json", self.audit("map", "web", "backend", "mobile"))
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        self.write("web/src/app/login/page.tsx", "export default function P() { return 1 }\n")
        self.git("commit", "-q", "-am", "login changed")
        prev = self.save("prev.md", "## Bản đồ phủ\n\n| Vùng | admin | member | Lần cuối |\n|---|---|---|---|\n"
                         "| web / | ✓ | ✓ | @%s 2026-11-01 |\n| web /login | ✓ | ✓ | @%s 2026-11-10 |\n"
                         "| web /orders/:orderId | ✓ | ✗ #12 | @%s 2026-11-10 |\n| API /health | ✓ | ✓ | @%s 2026-11-10 |\n" % ((base[:7],) * 4))
        out = json.loads(self.audit("plan", "--map", amap, "--prev", prev, "--closed", "12,40", "--max", "4"))
        whys = [(s["area"], s["why"].split(" ")[0]) for s in out["selected"]]
        self.assertEqual(whys[:2], [("web /orders/:orderId", "verify"), ("web /login", "changed")])
        self.assertEqual(whys[2][1], "new")
        self.assertEqual(out["roles"], ["admin", "member"])
        self.assertEqual(out["covered_before"], 4)
        self.assertEqual(out["selected"][0]["cells"], {"admin": "✓", "member": "✗ #12"})
        focus = json.loads(self.audit("plan", "--map", amap, "--focus", "orders", "--max", "0"))
        self.assertEqual({s["area"] for s in focus["selected"]}, {"web /orders/:orderId", "API orders"})

    def test_ledger_merges_runs_and_keeps_the_trend(self):
        amap = self.save("map.json", self.audit("map", "web", "backend", "mobile"))
        prev = self.save("prev.md", "## Sức khoẻ\n\n| Ngày | @sha | Vùng đã phủ | Role | Cao | Vừa | Thấp | Tái phát | Xác minh sửa |\n"
                         "|---|---|---|---|---|---|---|---|---|\n| 2026-11-01 | @aaaaaaa | 1/9 (11%) | 1/2 | 2 | 1 | 0 | 0 | — |\n\n"
                         "## Bản đồ phủ\n\n| Vùng | admin | member | Lần cuối |\n|---|---|---|---|\n| web / | ✓ | · | @aaaaaaa 2026-11-01 |\n"
                         "| web /gone | ✓ | ✓ | @aaaaaaa 2026-11-01 |\n")
        run = self.save("run.md", "## Bản đồ phủ\n\n| Vùng | admin | member | guest |\n|---|---|---|---|\n"
                        "| web /orders/:orderId | ✓ | ✗ qa:F1 | ⛔ |\n\n## Xác minh sửa\n- #12 ✓\n- #13 ✗\n")
        index = self.save("index.json", json.dumps({"by_sev": {"cao": 1, "vừa": 2}, "findings": [{"regressed": "#13"}]}))
        md = self.audit("ledger", "--map", amap, "--prev", prev, "--run", run, "--index", index, "--sha", "b" * 40,
                        "--tickets", "qa:F1=#45", "--date", "2026-11-27")
        self.assertIn("| web /orders/:orderId | ✓ | ✗ #45 | ⛔ | · | @bbbbbbb 2026-11-27 |", md)
        self.assertIn("| web / | ✓ | · | · | · | @aaaaaaa 2026-11-01 |", md)  # untouched this run: kept
        self.assertNotIn("/gone", md)  # no longer in the product
        self.assertIn("| 2026-11-01 | @aaaaaaa | 1/9 (11%) | 1/2 | — | 2 |", md)  # a run before readiness: its column padded
        self.assertRegex(md, r"\| 2026-11-27 \| @bbbbbbb \| 2/\d+ \(\d+%\) \| 3/3 \| — \| 1 \| 2 \| 0 \| 1 \| 1/2 \|")
        self.assertIn("Phủ vùng 1/", md)
        self.assertLess(md.index("## Sức khoẻ"), md.index("## Bản đồ phủ"))
        again = self.save("again.md", md)
        out = json.loads(self.audit("plan", "--map", amap, "--prev", again, "--closed", "45"))
        self.assertEqual(out["selected"][0]["why"], "verify #45")


class AuditPanel(RepoCase):
    """findings: the UI/UX, Product and Engineering experts add their view to a finding the tester found."""

    git = Style.git
    write = Style.write

    def setUp(self):
        super().setUp()
        self.write("agentflow.yaml", AUDIT_CONFIG)
        self.write("out/qa.md", QA_FINDINGS)
        self.write("out/ux.md", UX_FINDINGS)
        self.write("out/arch.md", ARCH_VIEW)

    def audit(self, *args, code=0):
        res = tool("agentflow-audit", *args, cwd=self.repo)
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        return res.stdout

    def test_views_join_the_finding_they_extend(self):
        out = json.loads(self.audit("findings", "out/qa.md", "out/ux.md", "out/arch.md", code=1))
        by_id = {f["id"]: f for f in out["findings"]}
        self.assertEqual(by_id["qa:F1"]["panel"], ["qa", "ux"])
        self.assertEqual(by_id["qa:F1"]["roles"], ["member"])
        self.assertEqual(by_id["qa:F2"]["sev"], "cao")  # Engineering showed a lost payment error: raised
        self.assertEqual(by_id["qa:F2"]["sev_from"], "thấp → cao (arch:F1)")
        self.assertNotIn("ux:F1", by_id)
        self.assertIn("ux:F2", by_id)
        self.assertEqual(out["panel"], 2)
        self.assertEqual(out["by_lens"], {"qa": 2, "ux": 1})
        [error] = out["errors"]
        self.assertEqual(error["id"], "ux:F3")
        body = self.audit("findings", "out/qa.md", "out/ux.md", "out/arch.md", "--body", "qa:F1")
        self.assertLess(body.index("### Tiêu chí nghiệm thu"), body.index("### Góc nhìn UI/UX"))

    def test_a_view_cannot_extend_its_own_lens(self):
        self.write("out/qa2.md", "# audit qa · o/r\n\n## F1. x\n- extends: qa:F2\n- evidence: y\n\n### Góc nhìn\nz\n")
        out = json.loads(self.audit("findings", "out/qa2.md", code=1))
        self.assertIn("lăng kính khác", out["errors"][0]["error"])


def png(width, height, pad=0):
    """A PNG header the size reader understands, padded to weigh `pad` bytes more."""
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
            + b"\0" * (4 + pad))


READY_CONFIG = """schema: 5
surfaces:
  web:
    path: "web/"
  mobile:
    path: "mobile/"
forbidden: ["web/src/secret/**"]
"""
READY_FILES = {
    "agentflow.yaml": READY_CONFIG,
    "web/package.json": '{"dependencies": {"vite": "5.0.0", "react": "18.3.1", "lucide-react": "0.400.0", "react-icons": "5.0.0", '
                        '"@sentry/react": "8.0.0"}}\n',
    "web/index.html": '<html><head><link rel="icon" href="/vite.svg" /><title>Vite + React</title></head></html>\n',
    "web/public/vite.svg": "<svg/>\n",
    "web/src/theme/colors.ts": "export const colors = { primary: '#0a84ff', danger: '#ff3b30' }\n",
    "web/src/i18n/vi.json": '{"home": "Trang chủ"}\n',
    "web/src/main.tsx": "import Home from './pages/home'\nexport const routes = <Route path=\"/home\" element={<Home />} />\n",
    "web/src/pages/home.tsx": "import { Search } from 'lucide-react'\n"
                              "import { FaUser } from 'react-icons/fa'\n"
                              "import hero from '../assets/hero.png'\n"
                              "import gone from '../assets/gone.png'\n"
                              "import { Card } from '../components/card'\n"
                              "export default function Home() {\n"
                              "  const { data } = useQuery(['feed'], load)\n"
                              "  return <div style={{ color: '#ff0000', padding: 10 }}>\n"
                              "    <p>Lorem ipsum dolor sit amet</p>\n"
                              "    <button onClick={() => {}}>Đăng nhập</button>\n"
                              "    <span>Something went wrong, try again</span>\n"
                              "    <img src=\"https://picsum.photos/200\" /> <i>🔥</i>\n"
                              "    {data.map((x) => <Card key={x.id} />)}\n"
                              "    <p>{error.message}</p> <img src={hero} /> <img src={gone} /> <Search /> <FaUser />\n"
                              "  </div>\n}\n",
    "web/src/components/card.tsx": "export const Card = () => <div className=\"bg-[#123abc] p-[13px]\">Coming soon</div>\n",
    "web/src/secret/keys.tsx": "export const K = () => <p>Lorem ipsum</p>\n",
    "mobile/pubspec.yaml": "name: app\nflutter:\n  assets:\n    - assets/images/\n",
    "mobile/lib/pages/profile.dart": "class ProfilePage extends StatelessWidget {\n"
                                     "  Widget build(BuildContext context) {\n"
                                     "    return Column(children: [\n"
                                     "      Image.asset('assets/images/logo.png'),\n"
                                     "      Image.asset('assets/images/gone.png'),\n"
                                     "      Icon(Icons.add), Icon(CupertinoIcons.add),\n"
                                     "      Container(color: Colors.red, padding: EdgeInsets.all(Spacing.x3)),\n"
                                     "      Container(color: const Color(0xFF123456), padding: EdgeInsets.all(10)),\n"
                                     "      TextButton(onPressed: () {}, child: Text('Sắp ra mắt')),\n"
                                     "    ]);\n  }\n}\n",
    "mobile/android/app/src/main/AndroidManifest.xml": '<manifest><application android:label="my_app" android:icon="@mipmap/ic_launcher">'
                                                       '<intent-filter android:label="flutter_web_auth_2"/></application></manifest>\n',
    "mobile/ios/Runner.xcodeproj/project.pbxproj": "// project\n",
    "mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Contents.json":
        '{"images": [{"size": "60x60", "scale": "2x", "filename": "a.png"}, {"size": "1024x1024", "scale": "1x"}]}\n',
}
READY_IMAGES = {
    "web/src/assets/hero.png": png(1600, 900, 400 * 1024),
    "web/src/assets/unused-banner.png": png(800, 200),
    "web/src/assets/icons/ic_star.png": png(24, 24),
    "mobile/assets/images/logo.png": png(100, 100),
    "mobile/assets/images/2.0x/logo.png": png(200, 200),
    "mobile/android/app/src/main/res/mipmap-hdpi/ic_launcher.png": png(72, 72),
    "mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/a.png": png(120, 120),
}


class AuditReady(RepoCase):
    """agentflow-audit ready: what still makes the product look like a prototype, counted where ux should look."""

    write = Style.write

    def setUp(self):
        super().setUp()
        for rel, text in READY_FILES.items():
            self.write(rel, text)
        for rel, data in READY_IMAGES.items():
            os.makedirs(os.path.dirname(os.path.join(self.repo, rel)), exist_ok=True)
            with open(os.path.join(self.repo, rel), "wb") as fh:
                fh.write(data)
        Style.git(self, "add", "-A")
        Style.git(self, "commit", "-q", "-m", "base")

    def audit(self, *args, code=0):
        res = tool("agentflow-audit", *args, cwd=self.repo)
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        return res.stdout

    def test_prototype_traces_a_user_sees(self):
        out = json.loads(self.audit("ready"))
        proto = out["prototype"]
        self.assertEqual(proto["lorem"]["at"], ["web/src/pages/home.tsx:9"])  # the forbidden folder is never read
        self.assertEqual(proto["coming_soon"]["count"], 2)  # English and Vietnamese
        self.assertEqual(proto["placeholder_image"]["at"], ["web/src/pages/home.tsx:12"])
        self.assertEqual(proto["dead_handler"]["files"], 2)  # onClick={() => {}} and onPressed: () {}
        self.assertEqual(proto["raw_error"]["at"], ["web/src/pages/home.tsx:14"])
        self.assertEqual(sorted(proto["default_title"]["at"]), ["mobile/android/app/src/main/AndroidManifest.xml:1", "web/index.html:1"])
        self.assertEqual(proto["template_leftovers"], [{"path": "web/public/vite.svg", "used": True}])
        self.assertNotIn("Lorem", json.dumps(out["prototype"].get("todo_text", {})))

    def test_design_system_drift_outside_the_token_files(self):
        ds = json.loads(self.audit("ready"))["design_system"]
        self.assertEqual(ds["token_files"], ["web/src/theme/colors.ts"])
        self.assertEqual(ds["hardcoded"]["hex"]["at"], ["web/src/pages/home.tsx:8"])  # the tokens' own hex do not count
        self.assertEqual(ds["hardcoded"]["arbitrary_value"]["at"], ["web/src/components/card.tsx:1"])  # one hit a line
        self.assertEqual(ds["hardcoded"]["default_palette"]["at"], ["mobile/lib/pages/profile.dart:7"])
        self.assertEqual(ds["hardcoded"]["color_literal"]["count"], 1)
        self.assertEqual(ds["hardcoded"]["off_grid"]["count"], 2)  # padding: 10 and EdgeInsets.all(10), not Spacing.x3
        self.assertEqual(ds["icon_mixed"], {"mobile (dart)": ["cupertino", "material"], "web (js)": ["lucide", "react-icons/fa"]})
        self.assertEqual(ds["emoji"]["count"], 1)

    def test_assets_identity_copy_states_and_ops(self):
        out = json.loads(self.audit("ready"))
        assets = out["assets"]
        self.assertEqual(assets["heavy"][0]["path"], "web/src/assets/hero.png")
        self.assertEqual(assets["heavy"][0]["px"], "1600x900")
        self.assertEqual(assets["raster_icons"]["at"], ["web/src/assets/icons/ic_star.png"])
        gaps = {g["asset"]: g["missing"] for g in assets["density_gaps"]["top"]}
        self.assertEqual(gaps["mobile/assets/images/logo.png"], ["3.0x"])
        self.assertEqual(gaps["mobile/android/app/src/main/res/mipmap/ic_launcher"], ["mdpi", "xhdpi", "xxhdpi", "xxxhdpi"])
        self.assertIn("web/src/assets/unused-banner.png", assets["unused"]["top"])
        self.assertNotIn("web/src/assets/hero.png", assets["unused"]["top"])
        self.assertEqual(sorted(m["ref"] for m in assets["missing"]), ["../assets/gone.png", "assets/images/gone.png"])
        identity = out["identity"]
        self.assertIn("app icon 1024×1024 (App Store)", identity["ios"]["missing"])
        self.assertIn("launch screen", identity["ios"]["missing"])
        self.assertIn("adaptive icon (mipmap-anydpi-v26)", identity["android"]["missing"])
        self.assertEqual(identity["web"]["missing"], ["apple-touch-icon", "web manifest (icon 192/512)", "ảnh chia sẻ (og:image)"])
        self.assertFalse(out["fonts"]["custom"])
        self.assertTrue(out["copy"]["l10n"])
        self.assertEqual(out["copy"]["mixed_lang"]["en"], 1)
        self.assertIn("web/src/pages/home.tsx", out["states"]["no_loading"])
        self.assertIn("web/src/pages/home.tsx", out["states"]["no_empty"])
        self.assertEqual(out["ops"]["crash_reporting"], ["sentry"])
        self.assertEqual(out["ops"]["tracking"], [])

    def test_signals_of_each_area_follow_the_screens_imports(self):
        amap = os.path.join(self.repo, "map.json")
        with open(amap, "w", encoding="utf-8") as fh:
            fh.write(self.audit("map"))
        areas = {a["area"]: a for a in json.loads(self.audit("ready", "--map", amap))["areas"]}
        home = next(a for name, a in areas.items() if name.endswith("/home"))
        self.assertEqual(home["signals"]["coming_soon"], 1)  # from the card it imports
        self.assertEqual(home["signals"]["lorem"], 1)
        self.assertEqual(home["files"], 3)  # main.tsx → pages/home.tsx → components/card.tsx


READY_QA = """# audit qa · o/r @abc1234 · 2026-11-28

## F1. Nút Xuất báo cáo không làm gì
- fp: qa/reports/export-dead
- type: Bug
- sev: vừa
- effort: S
- evidence: audit-reports-admin-default.png

### Tiêu chí nghiệm thu
- [ ] Bấm Xuất tải về file CSV
"""
READY_UX = """# audit ux · o/r @abc1234 · 2026-11-28

## F1. Góc nhìn: nút chết là dấu vết prototype
- extends: qa:F1
- ready: prototype
- evidence: ready.json prototype.dead_handler

### Góc nhìn UI/UX
Nút chính của màn không làm gì: chưa đạt production.

## F2. Thay emoji bằng icon của bộ đang dùng ở 3 màn
- fp: ux/profile/emoji-icons
- type: Improvement
- sev: thấp
- effort: S
- evidence: audit-profile-member-default.png

### Tiêu chí nghiệm thu
- [ ] Không còn emoji làm icon

## F3. Ảnh hero mờ trên màn chủ
- fp: ux/home/hero-blurry
- type: Bug
- sev: vừa
- ready: beta
- effort: S
- evidence: audit-home-guest-default.png

### Tiêu chí nghiệm thu
- [ ] Ảnh hero có bản @2x, @3x

## Mức sẵn sàng
| Vùng | Mức | Lý do |
|---|---|---|
| web /reports | Prototype | ux:F1 — nút Xuất chưa nối |
| web /home | Beta | ux:F3 |
| web /profile | Production | ux:F2 chỉ đánh bóng |
| web /orders | Production | — |
| web /settings | Beta | không dẫn mục |
| web /cart | Production | ux:F3 |
"""


class AuditReadiness(RepoCase):
    """findings + ledger: ux grades each tested area Prototype · Beta · Production, and the grade follows its findings."""

    write = Style.write

    def setUp(self):
        super().setUp()
        self.write("agentflow.yaml", AUDIT_CONFIG)
        self.write("out/qa.md", READY_QA)
        self.write("out/ux.md", READY_UX)

    def audit(self, *args, code=0):
        res = tool("agentflow-audit", *args, cwd=self.repo)
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        return res

    def test_grades_must_match_the_findings_they_cite(self):
        out = json.loads(self.audit("findings", "out/qa.md", "out/ux.md", code=1).stdout)
        self.assertEqual(next(f for f in out["findings"] if f["id"] == "qa:F1")["ready"], "prototype")  # the view marked it
        self.assertEqual({g["area"]: g["level"] for g in out["ready"]},
                         {"web /reports": "Prototype", "web /home": "Beta", "web /profile": "Production", "web /orders": "Production"})
        self.assertEqual(out["ready"][0]["cites"], ["qa:F1"])  # a view stands for the finding it extends
        self.assertEqual(out["by_level"], {"Prototype": 1, "Beta": 1, "Production": 2})
        errors = {e["id"]: e["error"] for e in out["errors"]}
        self.assertIn("phải dẫn ít nhất một mục", errors["ready:web /settings"])
        self.assertIn("mức Production nhưng mục dẫn ra cho Beta", errors["ready:web /cart"])

    def test_only_ux_grades(self):
        self.write("out/arch.md", "# audit arch · o/r\n\n## F1. x\n- extends: qa:F1\n- evidence: y\n\n### Góc nhìn\nz\n\n"
                                  "## Mức sẵn sàng\n| Vùng | Mức | Lý do |\n|---|---|---|\n| web /a | Beta | qa:F1 |\n")
        out = json.loads(self.audit("findings", "out/qa.md", "out/arch.md", code=1).stdout)
        self.assertIn("chỉ ux chấm", out["errors"][0]["error"])
        self.assertEqual(out["ready"], [])

    def test_ledger_keeps_levels_of_tested_areas_across_runs(self):
        self.write("out/map.json", json.dumps({"areas": [{"area": a, "kind": "ui"} for a in
                                                         ("web /reports", "web /home", "web /profile", "web /orders", "web /old")],
                                               "roles": [{"role": "admin"}]}))
        self.write("out/prev.md", "## Bản đồ phủ\n\n| Vùng | admin | Mức | Lần cuối |\n|---|---|---|---|\n"
                                  "| web /old | ✓ | Beta | @aaaaaaa 2026-11-01 |\n| web /home | ✓ | Prototype | @aaaaaaa 2026-11-01 |\n")
        self.write("out/run.md", "## Bản đồ phủ\n\n| Vùng | admin |\n|---|---|\n| web /reports | ✗ qa:F1 |\n| web /home | ✓ |\n"
                                 "| web /profile | ✓ |\n")
        self.write("out/index.json", json.dumps({"ready": [{"area": "web /reports", "level": "Prototype"}, {"area": "web /home", "level": "Beta"},
                                                           {"area": "web /profile", "level": "Production"},
                                                           {"area": "web /orders", "level": "Production"}]}))
        res = self.audit("ledger", "--map", "out/map.json", "--prev", "out/prev.md", "--run", "out/run.md", "--index", "out/index.json",
                         "--sha", "b" * 40, "--date", "2026-11-28")
        md = res.stdout
        self.assertIn("| web /reports | ✗ qa:F1 | Prototype | @bbbbbbb 2026-11-28 |", md)
        self.assertIn("| web /home | ✓ | Beta | @bbbbbbb 2026-11-28 |", md)  # tested again: the new grade
        self.assertIn("| web /old | ✓ | Beta | @aaaaaaa 2026-11-01 |", md)  # not tested: its grade kept
        self.assertIn("| web /orders | · | · | — |", md)  # graded without a test this run: ignored
        self.assertIn("web /orders", res.stderr)
        self.assertIn("mức 1 Production · 2 Beta · 1 Prototype / 4 vùng đã chấm", md)
        self.assertRegex(md, r"\| 2026-11-28 \| @bbbbbbb \| \d/5 \(\d+%\) \| 1/1 \| 1/4 \|")
        plan = os.path.join(self.repo, "out/again.md")
        with open(plan, "w", encoding="utf-8") as fh:
            fh.write(md)
        out = json.loads(self.audit("plan", "--map", "out/map.json", "--prev", plan, "--max", "0").stdout)
        self.assertEqual({s["area"]: s["level"] for s in out["selected"]}["web /reports"], "Prototype")


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

    def test_audit_worktree_is_reset_to_the_fresh_base_each_time(self):
        wt = os.path.join(self.main, ".claude", "worktrees", "af-audit")
        out = self.base("audit")
        self.assertEqual((out["path"], out["sync"], out["base"], out["head"]), (wt, "created", "master", self.git(self.main, "rev-parse", "origin/master")))
        self.assertEqual(self.git(wt, "rev-parse", "HEAD"), out["head"])
        self.git(self.other, "fetch", "-q", "origin")
        self.git(self.other, "switch", "-q", "-C", "master", "origin/master")
        self.write(self.other, ".gitignore", "build/\n")
        self.commit(self.other, "ignore build")
        self.git(self.other, "push", "-q", "origin", "master")
        os.makedirs(os.path.join(wt, "_audit"))
        os.makedirs(os.path.join(wt, "build"))
        self.write(wt, "_audit/checkout.yaml", "url: x\n")  # scratch flow of the last audit
        self.write(wt, "build/app.bin", "deps\n")  # ignored once the new base is checked out: kept for the next build
        self.write(wt, "a.txt", "edited by a build\n")
        self.write(self.main, "a.txt", "the person's own edit\n")
        out = self.base("audit")
        self.assertEqual((out["sync"], out["head"]), ("reset", self.git(self.main, "rev-parse", "origin/master")))
        self.assertEqual(self.git(wt, "rev-parse", "HEAD"), out["head"])
        self.assertFalse(os.path.exists(os.path.join(wt, "_audit")))
        self.assertTrue(os.path.isfile(os.path.join(wt, "build", "app.bin")))
        self.assertEqual(self.git(wt, "status", "--porcelain"), "")
        self.assertEqual(self.git(self.main, "status", "--porcelain"), "M a.txt")  # the main checkout is the person's
        self.assertEqual(self.git(self.main, "branch", "--format=%(refname:short)"), "master")
        self.assertEqual(self.base("clean", "--issue", "7")["removed"], [])  # ticket cleanup never takes the audit worktree
        self.assertTrue(os.path.isdir(wt))

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


class Metrics(unittest.TestCase):
    """agentflow-metrics: cost per ticket and per step from the local transcripts of agentflow spawns only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(self.home, "my.repo")
        os.makedirs(self.repo)
        self.folder = os.path.join(self.home, "claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", self.repo), "s1", "subagents")  # as Claude Code names it
        os.makedirs(self.folder)

    def spawn(self, name, agent, prompt, usages, minutes=10):
        with open(os.path.join(self.folder, name + ".meta.json"), "w") as fh:
            json.dump({"agentType": agent}, fh)
        lines = [{"type": "user", "timestamp": "2026-11-26T10:00:00Z", "message": {"content": prompt}}]
        for u in usages:
            lines.append({"type": "assistant", "timestamp": "2026-11-26T10:%02d:00Z" % minutes, "message": {"usage": u}})
        with open(os.path.join(self.folder, name + ".jsonl"), "w") as fh:
            fh.write("\n".join(json.dumps(l) for l in lines) + "\nnot json\n")

    def metrics(self, *args):
        res = tool("agentflow-metrics", "--project", self.repo, "--json", *args, cwd=self.repo, env={"CLAUDE_CONFIG_DIR": os.path.join(self.home, "claude")})
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_per_ticket_and_step(self):
        big = {"input_tokens": 0, "cache_read_input_tokens": 10_000_000, "cache_creation_input_tokens": 0, "output_tokens": 0}
        self.spawn("a1", "agentflow:dev", "REPO: o/r\nISSUE: #42\nMODE: new", [big, dict(big, output_tokens=200_000)], minutes=30)
        self.spawn("a2", "agentflow:sa", "REPO: o/r\nISSUE: #42\nMODE: review", [big])
        self.spawn("a3", "agentflow:sa", [{"type": "text", "text": "ISSUE: #43\nMODE: review"}], [big])
        self.spawn("a4", "general-purpose", "ISSUE: #42", [big])  # not an agentflow spawn
        res = self.metrics()
        self.assertEqual((res["tickets"], res["spawns"]), (2, 3))
        top = res["top"][0]
        self.assertEqual((top["issue"], top["eq"], top["sa_reviews"], top["minutes"]), (42, 4_000_000, 1, 40))
        steps = {r["step"]: r for r in res["by_step"]}
        self.assertEqual((steps["dev/new"]["turns_median"], steps["dev/new"]["peak_median"], steps["dev/new"]["share"]), (2, 10_000_000, 0.6))
        self.assertEqual(self.metrics("--issue", "43")["tickets"], 1)

    def test_nothing_yet(self):
        res = tool("agentflow-metrics", "--project", self.repo, cwd=self.repo, env={"CLAUDE_CONFIG_DIR": os.path.join(self.home, "nope")})
        self.assertIn("chưa có lượt agent", res.stdout)


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

    def test_the_auditor_reports_on_no_ticket(self):
        self.assertEqual(self.check("RESULT: audit · ok\nNOTE: 7 phát hiện", agent="agentflow:audit"), "")
        self.assertEqual(json.loads(self.check("RESULT: in_review · ok", agent="agentflow:audit"))["decision"], "block")
        self.assertEqual(json.loads(self.check("RESULT: audit · ok"))["decision"], "block")  # a DEV always has a ticket stage

    def test_other_agents_untouched(self):
        self.assertEqual(self.check("không có", agent="Explore"), "")
        self.assertEqual(self.check("không có", agent=""), "")

    def test_broken_stdin(self):
        self.assertEqual(tool("result-check.py", stdin="not json").returncode, 0)


if __name__ == "__main__":
    unittest.main()
