#!/usr/bin/env python3
"""agentflow-distribute against a throwaway source repo, a bare origin, a fake Claude config dir and a fake `claude`:
no network, no real project touched."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SCRIPT = os.path.join(REPO, "agentflow", "bin", "agentflow-distribute")
MKT = "test-mkt"
ID = "agentflow@" + MKT

# Fake `claude`: logs argv + cwd, tags like `claude plugin tag`, and `plugin update` writes the source version into
# installed_plugins.json for the install of its cwd (what Claude Code does when it copies the snapshot).
FAKE_CLAUDE = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, subprocess, sys
    args = sys.argv[1:]
    with open(os.environ["FAKE_LOG"], "a") as fh:
        fh.write(json.dumps({"args": args, "cwd": os.path.realpath(os.getcwd())}) + "\\n")
    fail = os.environ.get("FAKE_FAIL_IN")
    if fail and os.path.realpath(os.getcwd()) == os.path.realpath(fail) and args[:2] == ["plugin", "update"]:
        sys.exit("boom")
    if args[:2] == ["plugin", "tag"]:
        meta = json.load(open(os.path.join(args[2], ".claude-plugin", "plugin.json")))
        msg = args[args.index("-m") + 1].replace("%s", meta["version"])
        sys.exit(subprocess.call(["git", "tag", "-a", "agentflow--v" + meta["version"], "-m", msg]))
    if args[:2] == ["plugin", "update"]:
        src = os.environ["FAKE_SRC"]
        version = json.load(open(os.path.join(src, "agentflow", ".claude-plugin", "plugin.json")))["version"]
        path = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "plugins", "installed_plugins.json")
        data = json.load(open(path))
        for entry in data["plugins"][args[2]]:
            here = entry.get("projectPath") and os.path.realpath(entry["projectPath"]) == os.path.realpath(os.getcwd())
            if here or (entry["scope"] == "user" and args[4] == "user"):
                entry["version"] = version
        json.dump(data, open(path, "w"))
    """)


def sh(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def git_commit(cwd, msg="c"):
    sh(["git", "add", "-A"], cwd)
    sh(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg], cwd)


class Distribute(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.src = os.path.join(self.tmp, "src")
        self.home = os.path.join(self.tmp, "claude")
        self.log = os.path.join(self.tmp, "claude.log")
        os.makedirs(os.path.join(self.src, ".claude-plugin"))
        os.makedirs(os.path.join(self.src, "agentflow", ".claude-plugin"))
        os.makedirs(os.path.join(self.src, "agentflow", "scripts"))
        os.makedirs(os.path.join(self.src, "agentflow", "bin"))
        os.makedirs(os.path.join(self.home, "plugins"))
        self.write(os.path.join(self.src, ".claude-plugin", "marketplace.json"),
                   json.dumps({"name": MKT, "plugins": [{"name": "agentflow", "source": "./agentflow"}]}))
        self.write(os.path.join(self.src, "agentflow", ".claude-plugin", "plugin.json"),
                   '{\n  "name": "agentflow",\n  "version": "1.2.3",\n  "license": "MIT"\n}\n')
        shutil.copy(os.path.join(REPO, "agentflow", "scripts", "afconfig.py"), os.path.join(self.src, "agentflow", "scripts"))
        shutil.copy(os.path.join(REPO, "agentflow", "agentflow.yaml"), os.path.join(self.src, "agentflow"))
        shutil.copy(SCRIPT, os.path.join(self.src, "agentflow", "bin"))
        self.claude = os.path.join(self.tmp, "fake-claude")
        self.write(self.claude, FAKE_CLAUDE)
        os.chmod(self.claude, 0o755)
        self.origin = os.path.join(self.tmp, "origin.git")
        sh(["git", "init", "-q", "--bare", "-b", "master", self.origin], self.tmp)
        sh(["git", "init", "-q", "-b", "master"], self.src)
        sh(["git", "remote", "add", "origin", self.origin], self.src)
        git_commit(self.src, "init")
        sh(["git", "push", "-q", "origin", "master"], self.src)
        self.write(os.path.join(self.home, "plugins", "known_marketplaces.json"),
                   json.dumps({MKT: {"source": {"source": "directory", "path": self.src}}}))
        self.installs = []
        self.save_installs()

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def save_installs(self):
        self.write(os.path.join(self.home, "plugins", "installed_plugins.json"),
                   json.dumps({"version": 2, "plugins": {ID: self.installs}}))

    def project(self, name, config=None, version="1.0.0", sha=None):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        sh(["git", "init", "-q", "-b", "master"], path)
        if config is not None:
            self.write(os.path.join(path, "agentflow.yaml"), config)
        self.installs.append({"scope": "local", "projectPath": path, "version": version, "gitCommitSha": sha})
        self.save_installs()
        return path

    def template(self):
        with open(os.path.join(REPO, "agentflow", "agentflow.yaml"), encoding="utf-8") as fh:
            return fh.read()

    def tool(self, *args, fail_in=None, script=None):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.tmp, "CLAUDE_CONFIG_DIR": self.home, "AGENTFLOW_CLAUDE_BIN": self.claude,
               "FAKE_LOG": self.log, "FAKE_SRC": self.src}
        if fail_in:
            env["FAKE_FAIL_IN"] = fail_in
        script = script or os.path.join(self.src, "agentflow", "bin", "agentflow-distribute")
        return subprocess.run([sys.executable, "-I", script, *args], cwd=self.tmp, capture_output=True, text=True, env=env)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [json.loads(line) for line in fh]

    def plan(self):
        res = self.tool("plan", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    # ── source ──

    def cache_copy(self):
        """An older copy in the plugin cache: its `source` prints OLD, so output proves which copy ran."""
        path = os.path.join(self.home, "plugins", "cache", MKT, "agentflow", "1.0.0", "bin", "agentflow-distribute")
        os.makedirs(os.path.dirname(path))
        with open(SCRIPT, encoding="utf-8") as fh:
            self.write(path, fh.read().replace("print(ROOT)", 'print("OLD")'))
        return path

    def test_cache_copy_hands_over_to_the_source_copy(self):
        self.project("a", self.template())
        res = self.tool("source", script=self.cache_copy())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), self.src)

    def test_no_source_on_this_machine_stops(self):
        self.project("a", self.template())
        self.write(os.path.join(self.home, "plugins", "known_marketplaces.json"),
                   json.dumps({MKT: {"source": {"source": "github", "repo": "x/y"}}}))
        res = self.tool("plan", script=self.cache_copy())
        self.assertEqual(res.returncode, 2)
        self.assertIn("không giữ source", res.stderr)

    # ── plan / compat ──

    def test_plan_reports_release_state_and_compat_of_each_project(self):
        good = self.project("good", self.template())
        old = self.project("old", "schema: 2\nboard:\n  url: https://github.com/orgs/x/projects/1\n")
        bare = self.project("bare")
        out = self.plan()
        self.assertEqual(out["release"]["state"], "unreleased")
        self.assertEqual(out["release"]["version"], "1.2.3")
        self.assertEqual(out["release"]["marketplace_source"], "directory")
        by = {r["project"]: r for r in out["installs"]}
        self.assertIn(by[good]["status"], ("ok", "warn"))
        self.assertEqual(by[good]["fails"], [])
        self.assertEqual(by[old]["status"], "incompatible")
        self.assertTrue(any("schema 2" in m for m in by[old]["fails"]))
        self.assertEqual(by[bare]["status"], "not_initialized")
        self.assertFalse(by[good]["up_to_date"])

    def test_compat_exit_code_follows_incompatible_projects(self):
        old = self.project("old", "schema: 2\n")
        self.assertEqual(self.tool("compat").returncode, 1)
        self.write(os.path.join(old, "agentflow.yaml"), self.template())
        res = self.tool("compat", "--project", old)
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_unknown_project_is_refused(self):
        self.project("a", self.template())
        res = self.tool("compat", "--project", os.path.join(self.tmp, "nope"))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("không có bản cài", res.stderr)

    def test_schema_change_since_last_tag_asks_for_minor(self):
        self.tool("publish")
        path = os.path.join(self.src, "agentflow", "scripts", "afconfig.py")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.write(path, re.sub(r"^SCHEMA = (\d+)", lambda m: "SCHEMA = %d" % (int(m.group(1)) + 1), text, flags=re.M))
        release = self.plan()["release"]
        self.assertEqual(release["state"], "needs_bump")
        self.assertEqual(release["min_bump"], "minor")

    # ── bump ──

    def test_bump_keeps_the_rest_of_plugin_json(self):
        res = self.tool("bump", "minor")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("1.2.3 → 1.3.0", res.stdout)
        with open(os.path.join(self.src, "agentflow", ".claude-plugin", "plugin.json")) as fh:
            self.assertEqual(fh.read(), '{\n  "name": "agentflow",\n  "version": "1.3.0",\n  "license": "MIT"\n}\n')
        self.tool("bump", "major")
        self.assertEqual(self.plan()["release"]["version"], "2.0.0")

    # ── publish ──

    def test_publish_refuses_dirty_tree(self):
        self.write(os.path.join(self.src, "x.txt"), "x")
        res = self.tool("publish")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("chưa commit", res.stderr)
        self.assertEqual(self.calls(), [])

    def test_publish_tags_and_pushes_branch_and_tag_then_is_idempotent(self):
        self.write(os.path.join(self.src, "x.txt"), "x")
        git_commit(self.src, "feat")
        res = self.tool("publish")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(json.loads(res.stdout)["pushed"])
        remote_tag = subprocess.run(["git", "rev-parse", "agentflow--v1.2.3^{commit}"], cwd=self.origin, capture_output=True, text=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.src, capture_output=True, text=True).stdout.strip()
        self.assertEqual(remote_tag.stdout.strip(), head)
        remote_master = subprocess.run(["git", "rev-parse", "master"], cwd=self.origin, capture_output=True, text=True)
        self.assertEqual(remote_master.stdout.strip(), head)
        self.assertEqual(self.plan()["release"]["state"], "released")
        again = self.tool("publish")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(sum(c["args"][:2] == ["plugin", "tag"] for c in self.calls()), 1)

    def test_publish_after_new_commit_on_tagged_version_needs_bump(self):
        self.tool("publish")
        self.write(os.path.join(self.src, "y.txt"), "y")
        git_commit(self.src, "more")
        res = self.tool("publish")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("bump version", res.stderr)
        self.tool("bump", "patch")
        git_commit(self.src, "bump")
        self.assertEqual(self.tool("publish").returncode, 0)

    def test_publish_refuses_other_branch(self):
        sh(["git", "checkout", "-q", "-b", "feature"], self.src)
        res = self.tool("publish")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("chỉ phát hành từ", res.stderr)

    def test_failed_push_exits_3_and_keeps_the_local_tag(self):
        sh(["git", "remote", "set-url", "origin", os.path.join(self.tmp, "missing.git")], self.src)
        res = self.tool("publish")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertFalse(json.loads(res.stdout)["pushed"])
        tag = subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/tags/agentflow--v1.2.3"], cwd=self.src, capture_output=True)
        self.assertEqual(tag.returncode, 0)

    # ── install ──

    def test_install_updates_each_project_in_its_own_dir_and_checks_the_version(self):
        a = self.project("a", self.template())
        b = self.project("b", self.template())
        res = self.tool("install")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        rows = json.loads(res.stdout)["installs"]
        self.assertEqual({(r["project"], r["to"], r["ok"]) for r in rows}, {(a, "1.2.3", True), (b, "1.2.3", True)})
        calls = self.calls()
        self.assertEqual(calls[0]["args"], ["plugin", "marketplace", "update", MKT])
        updates = [c for c in calls if c["args"][:2] == ["plugin", "update"]]
        self.assertEqual({c["cwd"] for c in updates}, {a, b})
        self.assertTrue(all(c["args"][2:] == [ID, "--scope", "local"] for c in updates))

    def test_install_reports_the_project_that_failed(self):
        a = self.project("a", self.template())
        b = self.project("b", self.template())
        res = self.tool("install", fail_in=b)
        self.assertEqual(res.returncode, 1)
        rows = {r["project"]: r for r in json.loads(res.stdout)["installs"]}
        self.assertTrue(rows[a]["ok"])
        self.assertFalse(rows[b]["ok"])
        self.assertIn("boom", rows[b]["error"])

    def test_install_refuses_same_version_from_another_tree(self):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.src, capture_output=True, text=True).stdout.strip()
        self.project("same", self.template(), version="1.2.3", sha=head)
        self.assertEqual(self.tool("install").returncode, 0)
        self.write(os.path.join(self.src, "x.txt"), "x")
        res = self.tool("install")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("bump version", res.stderr)
        self.assertEqual(sum(c["args"][:3] == ["plugin", "marketplace", "update"] for c in self.calls()), 1)

    def test_install_can_target_one_project(self):
        a = self.project("a", self.template())
        self.project("b", self.template())
        res = self.tool("install", "--project", a)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([r["project"] for r in json.loads(res.stdout)["installs"]], [a])


if __name__ == "__main__":
    unittest.main()
