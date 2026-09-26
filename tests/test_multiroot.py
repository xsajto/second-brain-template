"""Tests for the multi-root layout (brain.config.json › roots: workspace + roots `work/` and `home/`): root
discovery, per-root parse cache, git with the repository one level up, cross-root links, the context guard on
create, the PostToolUse hook for a file in the sibling root. Everything runs in temp dirs (fixture.Vault)."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import BIN, LIB, NOTES, Vault  # noqa: E402

sys.path.insert(0, str(LIB))
import vault  # noqa: E402

CONFIG = {
    "roots": {"work": {"contexts": ["work"]}, "home": {"contexts": ["private", "side"]}},
    "contexts": {"work": {"slug": "work"}, "private": {"slug": "priv"}, "side": {"slug": "side"}},
}
HOME = {
    "CLAUDE.md": "# Home root\n",
    "30_Areas/private/private-hub.md": "---\nid: area/private\ntype: area\nkind: role\ntitle: Private\n"
                                       "context: private\ntags: [ctx/private]\n---\n\n# Private\n",
    "20_Projects/priv-garden/CLAUDE.md": "---\nid: project/priv-garden\ntype: project\ntitle: Garden\n"
                                         "context: private\narea: \"[[private-hub|Private]]\"\nstatus: active\n"
                                         "tags: [ctx/private]\n---\n\n# Garden\n",
    "40_Knowledge/private/recipes/goulash.md": "---\nid: note/goulash\ntype: note\ntitle: Goulash\n"
                                               "context: private\n---\n\nSee [[billing|Billing]] at work.\n",
}


class MultiRoot(unittest.TestCase):
    def setUp(self):
        billing = "40_Knowledge/work/billing/billing.md"
        self.m = Vault(name="work", config=CONFIG, git=False,
                       extra={billing: NOTES[billing].replace("# Billing System\n",
                                                              "# Billing System\n\nRecipe: [[goulash]].\n")})
        self.o = self.m.ws / "home"
        for rel, text in HOME.items():
            p = self.o / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        self.env_o = dict(self.m.env, BRAIN_ROOT=str(self.o))

    def tearDown(self):
        self.m.cleanup()

    # -- root discovery (config-dependent module state: run in a subprocess with the fixture config)
    def test_find_root_per_root_and_error_from_workspace(self):
        env = {k: v for k, v in self.m.env.items() if k != "BRAIN_ROOT"}
        code = f"""
import json, paths
out = {{"work": str(paths.find_root({str(self.m.root / '40_Knowledge/people')!r})),
       "home": str(paths.find_root({str(self.o / '20_Projects/priv-garden')!r})),
       "siblings": [str(p) for p in paths.sibling_roots({str(self.m.root)!r})],
       "home_ctx": list(paths.root_contexts({str(self.o)!r})),
       "split": paths.is_split_root({str(self.o)!r}),
       "all": sorted(str(p) for p in paths.all_roots())}}
try:
    paths.find_root({str(self.m.ws)!r})
except SystemExit as e:
    out["err"] = str(e)
print(json.dumps(out))
"""
        r = self.m.py(code, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual((d["work"], d["home"]), (str(self.m.root), str(self.o)))
        self.assertEqual(d["siblings"], [str(self.o)])
        self.assertEqual(d["home_ctx"], ["private", "side"])
        self.assertTrue(d["split"])
        self.assertEqual(d["all"], sorted([str(self.m.root), str(self.o)]))
        self.assertIn("cd into work/, home/", d["err"])
        r = self.m.brain("validate", cwd=self.m.ws, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Brain root not found", r.stderr)

    def test_separate_cache_files(self):
        saved = os.environ.pop("BRAIN_CACHE", None)
        try:
            a, b = vault.cache_path(self.m.root), vault.cache_path(self.o)
        finally:
            if saved is not None:
                os.environ["BRAIN_CACHE"] = saved
        self.assertNotEqual(a, b)
        self.assertTrue(a.name.startswith("graph-work-") and b.name.startswith("graph-home-"), (a, b))

    # -- git: one repository for the workspace, the root is a subfolder of its work tree
    def git_ws(self):
        g = ["git", "-C", str(self.m.ws), "-c", "user.email=t@example.com", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", str(self.m.ws)], check=True)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-qm", "x"], check=True)

    def test_git_parent_repository_strips_prefix(self):
        self.git_ws()
        git = vault.Git(self.m.root)
        self.assertTrue(git.available)
        self.assertEqual(git.prefix, "work")
        self.m.put("40_Knowledge/people/ada-example.md", self.m.read("40_Knowledge/people/ada-example.md") + "- change\n")
        (self.o / "30_Areas/private/private-hub.md").write_text("changed\n", encoding="utf-8")  # other root: not ours
        dirty = git.dirty(["40_Knowledge/people/ada-example.md", "40_Knowledge/people/bob-sample.md"])
        self.assertEqual(dirty, ["40_Knowledge/people/ada-example.md"])
        self.assertTrue(git.is_tracked("40_Knowledge/people/bob-sample.md"))

    def test_separate_git_dir(self):
        gd = self.m.tmp / "vault.git"
        subprocess.run(["git", "init", "-q", "--bare", str(gd)], check=True)
        g = ["git", f"--git-dir={gd}", f"--work-tree={self.m.ws}"]
        subprocess.run(g + ["config", "core.bare", "false"], check=True)
        subprocess.run(g + ["config", "core.worktree", str(self.m.ws)], check=True)
        subprocess.run(g + ["-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A"], check=True)
        subprocess.run(g + ["-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "x"], check=True)
        os.environ["BRAIN_GIT_DIR"] = str(gd)
        try:
            git = vault.Git(self.m.root)
        finally:
            os.environ.pop("BRAIN_GIT_DIR", None)
        self.assertTrue(git.available)
        self.assertEqual(git.prefix, "work")
        self.assertTrue(git.is_tracked("40_Knowledge/people/bob-sample.md"))

    # -- validate
    def test_cross_root_link_is_info_not_error(self):
        r = self.m.brain("validate", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["errors"], 0, r.stdout)
        cross = [i for i in data["issues"] if i["code"] == "cross-root-link"]
        self.assertEqual([(i["severity"], i["detail"]) for i in cross],
                         [("info", "[[goulash]] -> home/40_Knowledge/private/recipes/goulash.md")])
        r = self.m.brain("validate", "--json", cwd=self.o, env=self.env_o)     # and from the other side
        data = json.loads(r.stdout)
        self.assertEqual(data["errors"], 0, r.stdout)
        self.assertIn("cross-root-link", {i["code"] for i in data["issues"]})

    def test_context_wrong_root_and_stem_collision(self):
        self.m.put("40_Knowledge/shared/goulash.md", "---\nid: note/goulash-2\ntype: note\ntitle: G\ncontext: private\n"
                   "---\n")
        data = json.loads(self.m.brain("validate", "--json").stdout)
        codes = {(i["code"], i["path"]) for i in data["issues"]}
        self.assertIn(("context-wrong-root", "40_Knowledge/shared/goulash.md"), codes)
        self.assertIn(("cross-root-stem-collision", "40_Knowledge/shared/goulash.md"), codes)

    def test_create_refuses_context_of_other_root(self):
        r = self.m.brain("create", "person", "Eve Sample", "--context", "private")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("create it in root home/", r.stderr)
        r = self.m.brain("create", "note", "Recipe", "--namespace", "private", "--apply", cwd=self.o, env=self.env_o)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(vault.Frontmatter((self.o / "40_Knowledge/private/recipe.md").read_text()).get("context"),
                         "private")
        r = self.m.brain("create", "project", "Side Gig", "--context", "side", "--apply", cwd=self.o, env=self.env_o)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.o / "20_Projects/side-side-gig/CLAUDE.md").is_file())

    # -- PostToolUse hook: a file in the sibling root is validated against its own root (or ignored)
    def test_post_tool_sibling_root_file(self):
        payload = {"tool_name": "Edit", "tool_input": {"file_path": str(self.o / "40_Knowledge/private/recipes/goulash.md")}}
        r = subprocess.run([sys.executable, str(BIN / "context.py"), "--post-tool"], input=json.dumps(payload),
                           cwd=self.m.root, env=self.m.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        stray = self.m.tmp / "elsewhere/note.md"
        stray.parent.mkdir(parents=True)
        stray.write_text("---\ntitle: x\n---\n", encoding="utf-8")
        payload["tool_input"]["file_path"] = str(stray)
        r = subprocess.run([sys.executable, str(BIN / "context.py"), "--post-tool"], input=json.dumps(payload),
                           cwd=self.m.root, env=self.m.env, capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
