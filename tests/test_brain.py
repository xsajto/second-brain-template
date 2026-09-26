"""Core test suite (python3 stdlib unittest). Run: `bin/brain test` (= python3 -m unittest discover -s tests).

Covers the vault library (frontmatter round-trip, link resolution), the brain CLI on a fixture vault (validate,
create, rename + dirty guard, doctor) and sync conflict-copy detection.
"""
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import BIN, LIB, Vault  # noqa: E402  (pins BRAIN_CONFIG before lib/ is imported)

sys.path.insert(0, str(LIB))
sys.path.insert(0, str(BIN))
import brainkg  # noqa: E402
import paths  # noqa: E402
import vault  # noqa: E402


class FixtureCase(unittest.TestCase):
    extra = None

    def setUp(self):
        self.v = Vault(self.extra)

    def tearDown(self):
        self.v.cleanup()

    def graph(self):
        return vault.Graph.load(self.v.root, use_cache=False)

    def issues(self, code):
        return [i for i in brainkg.validate(self.graph()) if i["code"] == code]


# ---------------------------------------------------------------- library
class FrontmatterRoundTrip(unittest.TestCase):
    TEXTS = [
        """---
id: person/ada-example   # never changes
type: person
title: "Ada Example: CTO"
aliases: [Ada, "A. E."]
stakeholders:
  - "[[a|A]]"
  - "[[b]]"
meeting:
  cadence: weekly
  day: monday
empty:
tags: [ctx/work, person]
---

# Body

text [[x|y]]
""",
        "no frontmatter at all\n",
        "---\n---\nbody only\n",
        "---\ntitle: x\n---",
        "---\r\ntitle: crlf\r\n---\r\nbody\r\n",
    ]

    def test_render_is_byte_identical(self):
        for t in self.TEXTS:
            with self.subTest(t=t[:30]):
                self.assertEqual(vault.Frontmatter(t).render(), t)

    def test_edit_keeps_other_lines(self):
        t = self.TEXTS[0]
        fmo = vault.Frontmatter(t)
        fmo.set("status", "active", after=["title"])
        out = fmo.render()
        self.assertEqual(out.replace("status: active\n", ""), t)
        self.assertEqual(vault.Frontmatter(out).get("stakeholders"), ["[[a|A]]", "[[b]]"])
        self.assertEqual(vault.Frontmatter(out).get("meeting")["_raw"].count("\n"), 1)


class Defaults(unittest.TestCase):
    def test_default_structure_is_english(self):
        self.assertEqual(paths.PEOPLE_DIR, "40_Knowledge/people")
        self.assertEqual(paths.ORGS_DIR, "40_Knowledge/orgs")
        self.assertEqual(paths.RELATION_MAP, "relationship-map.md")
        self.assertEqual(paths.CONTEXTS, ("work", "private"))
        self.assertEqual(paths.SLUG_CTX, {"work": "work", "priv": "private"})
        self.assertTrue(paths.SLUG_RE.match("priv-garden-plan"))
        self.assertFalse(paths.SLUG_RE.match("other-thing"))

    def test_schema_placeholders_filled(self):
        sch = vault.load_schema(LIB / "schema.json")
        self.assertEqual(vault.infer_type("40_Knowledge/people/x.md", [], sch), ("person", None))
        self.assertEqual(vault.infer_type("40_Knowledge/orgs/x.md", [], sch), ("org", None))
        self.assertEqual(vault.infer_type("20_Projects/work-a/decisions/x.md", [], sch), ("decision", None))
        self.assertEqual(vault.infer_type("30_Areas/eng/meetings/x.md", [], sch), ("meeting", None))
        self.assertIn("relationship-map.md", sch["companions"]["names"])
        self.assertNotIn("{{", json.dumps(sch["inference"]))
        self.assertEqual(vault.knowledge_cfg(sch)["registries"], {"people": "person", "orgs": "org"})


class LinkResolution(FixtureCase):
    def test_stem_alias_title_slug(self):
        g = self.graph()
        self.assertEqual(g.resolve("ada-example"), "40_Knowledge/people/ada-example.md")
        self.assertEqual(g.resolve("[[ada-example|Ada Example]]"), "40_Knowledge/people/ada-example.md")
        self.assertEqual(g.resolve("Ada"), "40_Knowledge/people/ada-example.md")          # alias
        self.assertEqual(g.resolve("Billing System"), "40_Knowledge/work/billing/billing.md")  # title
        self.assertEqual(g.resolve("work-alpha/CLAUDE"), "20_Projects/work-alpha/CLAUDE.md")
        self.assertIsNone(g.resolve("does-not-exist"))

    def test_body_links_become_edges(self):
        g = self.graph()
        daily = "10_Daily/2026/2026-09-24.md"
        dsts = {e["dst"] for e in g.out(daily, {"links_to"})}
        self.assertIn("40_Knowledge/people/ada-example.md", dsts)
        self.assertIn("20_Projects/work-alpha/CLAUDE.md", dsts)

    def test_engine_folders_are_not_notes(self):
        self.v.put("docs/guide.md", "[[nowhere]]\n")
        self.v.put("bin/notes.md", "[[nowhere]]\n")
        self.v.put("README.md", "[[nowhere]]\n")
        g = self.graph()
        self.assertFalse({"docs/guide.md", "bin/notes.md", "README.md"} & set(g.nodes))


# ---------------------------------------------------------------- validate
class Validate(FixtureCase):
    extra = {
        "40_Knowledge/orgs/mistake.md": "---\nid: person/mistake\ntype: person\ntitle: Mistake\ncontext: work\n---\n",
        "20_Projects/work-beta/CLAUDE.md": "---\nid: project/work-beta\ntype: project\ntitle: Beta\ncontext: private\n"
                                           "status: active\narea: \"[[engineering-hub|Engineering]]\"\n"
                                           "owner: \"[[nobody]]\"\n---\n\n# Beta\n\n[[does-not-exist]]\n",
        "20_Projects/work-gamma/CLAUDE.md": "---\nid: project/work-gamma\ntype: project\ntitle: Gamma\n"
                                            "context: work\nstatus: active\n---\n\n# Gamma\n",
        "40_Knowledge/shared/ai/note-one.md": "---\nid: note/note-one\ntype: note\ntitle: Note one\n---\n",
        "40_Knowledge/shared/ai/sub/deep.md": "---\nid: note/deep\ntype: note\ntitle: Deep\n---\n",
    }

    def test_clean_fixture_has_no_errors(self):
        v = Vault()
        try:
            g = vault.Graph.load(v.root, use_cache=False)
            errs = [i for i in brainkg.validate(g) if i["severity"] == "error"]
            self.assertEqual(errs, [])
            self.assertEqual(v.brain("validate").returncode, 0)
        finally:
            v.cleanup()

    def test_errors(self):
        self.assertEqual([i["path"] for i in self.issues("type-folder-mismatch")], ["40_Knowledge/orgs/mistake.md"])
        unres = self.issues("relation-unresolved")
        self.assertTrue(any(i["path"] == "20_Projects/work-beta/CLAUDE.md" and "owner" in i["detail"] for i in unres))
        self.assertTrue(any("[[does-not-exist]]" in i["detail"] for i in self.issues("broken-link")))
        self.assertTrue(all(i["severity"] == "error" for i in
                            self.issues("type-folder-mismatch") + unres + self.issues("broken-link")))
        self.assertEqual(self.v.brain("validate").returncode, 1)

    def test_branch_leaf(self):
        self.assertEqual([i["path"] for i in self.issues("branch-leaf")], ["40_Knowledge/shared/ai"])

    def test_raw_is_exempt_from_structure(self):
        for rel in ("50_Raw/reports/x/y/z/w/Deep Report.md", "50_Raw/reports/x/note-one.md",
                    "50_Raw/reports/y/note-one.md"):  # any depth, branch+leaf mix, bad name, stem collision
            self.v.put(rel, "---\ntitle: R\n---\n")
        self.v.put("50_Raw/reports/x/data.csv", "a,b\n")
        raw = [i for i in brainkg.validate(vault.Graph.load(self.v.root, use_cache=False))
               if i["path"].startswith("50_Raw/")
               and i["code"] in ("branch-leaf", "stem-collision", "knowledge-depth", "name-not-kebab")]
        self.assertEqual(raw, [])
        r = self.v.brain("validate", "--json", "--file", "50_Raw/reports/x/y/z/w/Deep Report.md")
        self.assertNotIn("name-not-kebab", r.stdout)

    def test_severity_decisions(self):
        self.v.put("40_Knowledge/shared/ai/sub/a.md", "---\nid: resource/a\ntype: note\ntitle: A\n"
                   "aliases: [host.example.com]\nowner: Nobody Known\n---\n")
        self.v.put("40_Knowledge/shared/ai/sub/b.md", "---\nid: note/b\ntype: note\ntitle: B\n"
                   "aliases: [host.example.com, note-one]\n---\n")
        iss = brainkg.validate(vault.Graph.load(self.v.root, use_cache=False))
        sev = lambda code: sorted((i["severity"], i["path"]) for i in iss if i["code"] == code)  # noqa: E731
        self.assertEqual(sev("id-type-mismatch"), [("info", "40_Knowledge/shared/ai/sub/a.md")])
        self.assertIn(("info", "40_Knowledge/shared/ai/sub/a.md"), sev("relation-unresolved-string"))
        da = sev("duplicate-alias")  # shared hostname -> info; alias naming another note's file -> warning
        self.assertIn(("info", "40_Knowledge/shared/ai/sub/a.md"), da)
        self.assertIn(("warning", "40_Knowledge/shared/ai/sub/b.md"), da)

    def test_context_area_mismatch_and_project_no_area(self):
        cam = self.issues("context-area-mismatch")
        self.assertEqual([i["path"] for i in cam], ["20_Projects/work-beta/CLAUDE.md"])
        self.assertEqual(cam[0]["severity"], "warning")
        self.assertEqual([i["path"] for i in self.issues("project-no-area")], ["20_Projects/work-gamma/CLAUDE.md"])


# ---------------------------------------------------------------- write commands
class DirtyGuard(FixtureCase):
    P = "20_Projects/work-alpha/CLAUDE.md"   # links ada-example, so a rename rewrites it

    def test_dry_run_writes_nothing(self):
        before = self.v.read(self.P)
        r = self.v.brain("rename", "ada-example", "ada-e")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertEqual(self.v.read(self.P), before)

    def test_apply_dirty_guard_and_own_write(self):
        # a foreign edit -> refused, file untouched
        self.v.put(self.P, self.v.read(self.P) + "\nmanual edit\n")
        before = self.v.read(self.P)
        r = self.v.brain("rename", "ada-example", "ada-e", "--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing", r.stderr)
        self.assertEqual(self.v.read(self.P), before)
        r = self.v.brain("rename", "ada-example", "ada-e", "--apply", "--allow-dirty")
        self.assertEqual(r.returncode, 0, r.stderr)
        # uncommitted now, but it is brain's own last write -> allowed
        r = self.v.brain("rename", "ada-e", "ada-f", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[[ada-f|", self.v.read(self.P))
        log = (self.v.root / paths.BRAIN_LOGS).glob("*.jsonl")
        actions = [json.loads(ln)["action"] for f in log for ln in f.read_text().splitlines()]
        self.assertIn("dirty-own", actions)
        self.assertIn("dirty-allowed", actions)


class Rename(FixtureCase):
    def test_rename_rewrites_links_and_adds_alias(self):
        r = self.v.brain("rename", "ada-example", "ada-e", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertFalse((self.v.root / "40_Knowledge/people/ada-example.md").exists())
        person = self.v.read("40_Knowledge/people/ada-e.md")
        fmo = vault.Frontmatter(person)
        self.assertEqual(fmo.get("title"), "Ada Example")
        self.assertEqual(fmo.get("id"), "person/ada-example")                 # id never changes
        self.assertIn("ada-example", fmo.get("aliases"))
        daily = self.v.read("10_Daily/2026/2026-09-24.md")
        self.assertIn("[[ada-e|her plan]]", daily)                            # label kept
        self.assertIn("[[ada-e|ada-example]]", daily)                         # bare link keeps what the reader saw
        self.assertIn("[[ada-e|Ada]]", daily)                                 # alias link retargeted, label kept
        proj = self.v.read("20_Projects/work-alpha/CLAUDE.md")
        self.assertIn("[[ada-e|Ada Example]]", proj)
        self.assertNotIn("[[ada-example", proj)
        self.assertEqual(self.v.brain("validate").returncode, 0)


class Create(FixtureCase):
    def test_project_person_decision(self):
        r = self.v.brain("create", "project", "Garden Plan", "--context", "private", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.v.root / "20_Projects/priv-garden-plan/CLAUDE.md").is_file())
        r = self.v.brain("create", "person", "Dan Placeholder", "--context", "work", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.v.root / "40_Knowledge/people/dan-placeholder.md").is_file())
        r = self.v.brain("create", "decision", "Pick a database", "--project", "work-alpha/CLAUDE", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        made = list((self.v.root / "20_Projects/work-alpha").glob("*-pick-a-database.md"))
        self.assertEqual(len(made), 1)
        self.assertEqual(vault.Frontmatter(made[0].read_text()).get("context"), "work")   # from the slug prefix
        self.assertNotEqual(self.v.brain("create", "person", "X", "--context", "nope").returncode, 0)


class Doctor(FixtureCase):
    def test_doctor_generic_checks(self):
        r = self.v.brain("doctor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("brain.config.json missing: defaults in use", r.stdout)
        self.assertIn("vault is in a git repository", r.stdout)
        self.v.config.write_text('{"roots": {".": {"contexts": ["ghost"]}}}', encoding="utf-8")
        r = self.v.brain("doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown context ghost", r.stdout)
        self.v.config.write_text("{not json", encoding="utf-8")
        r = self.v.brain("doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("invalid JSON", r.stdout)

    def test_cli_dispatcher(self):
        import subprocess
        r = subprocess.run([str(BIN / "brain"), "validate"], cwd=self.v.root, env=self.v.env, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([str(BIN / "brain"), "nope"], env=self.v.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)


# ---------------------------------------------------------------- sync conflict copies
class SyncConflicts(unittest.TestCase):
    def test_detection(self):
        v = Vault(git=False)
        try:
            for rel in ("40_Knowledge/people/ada-example 2.md", "bin/tool", "bin/tool 2",
                        "00_Inbox/capture (conflicted copy).md", "50_Raw/report 2023.pdf",
                        ".git/objects 2", ".gitignore", ".gitignore 3"):
                v.put(rel, "x")
            v.put(".git/objects", "x")
            self.assertEqual(paths.conflict_copies(v.root),
                             [".gitignore 3", "00_Inbox/capture (conflicted copy).md",
                              "40_Knowledge/people/ada-example 2.md", "bin/tool 2"])
        finally:
            v.cleanup()


if __name__ == "__main__":
    unittest.main()
