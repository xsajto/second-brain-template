"""Tests for the 40_Knowledge/ layout: namespaces + topics, the type/kind registry (schema.json), `@entity`
relation wildcards, `brain create` destinations and validate codes (knowledge-depth, knowledge-loose, stem-collision). All on the temp fixture vault (fixture.Vault) with a temp copy of schema.json
(BRAIN_SCHEMA)."""
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import LIB, Vault  # noqa: E402

sys.path.insert(0, str(LIB))
import paths  # noqa: E402
import vault  # noqa: E402

def add_entity_type(v, name):
    """What a hand edit of schema.json does: register an entity type with any kind."""
    raw = json.loads(v.schema.read_text(encoding="utf-8"))
    raw["types"]["entity"].append(name)
    raw["kinds"][name] = []
    v.schema.write_text(json.dumps(raw), encoding="utf-8")


SITE = "---\nid: location/{s}\ntype: location\ntitle: {t}\ncontext: work\n{extra}---\n\n# {t}\n"


class KCase(unittest.TestCase):
    extra = None

    def setUp(self):
        self.v = Vault(self.extra)

    def tearDown(self):
        self.v.cleanup()

    def ok(self, *args):
        r = self.v.brain(*args)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def validate(self):
        return json.loads(self.v.brain("validate", "--json").stdout)["issues"]

    def codes(self, code):
        return [i for i in self.validate() if i["code"] == code]


class Library(unittest.TestCase):
    def test_entity_wildcard_expands(self):
        raw = vault.load_schema_raw(LIB / "schema.json")
        self.assertEqual(raw["relations"]["part_of"]["from"], ["@entity"])
        raw["types"]["entity"].append("location")
        sch = vault.expand_schema(raw)
        self.assertIn("location", sch["relations"]["part_of"]["from"])
        self.assertIn("location", sch["relations"]["uses"]["to"])
        self.assertEqual(sch["relations"]["related"]["from"], ["*"])
        self.assertEqual(raw["relations"]["part_of"]["from"], ["@entity"])  # the raw schema is not modified

    def test_namespace_helpers(self):
        self.assertEqual(paths.namespace_of("40_Knowledge/work/infra/x.md"), "work")
        self.assertEqual(paths.namespace_of("40_Knowledge/work"), "work")
        self.assertIsNone(paths.namespace_of("40_Knowledge/people/ada-example.md"))
        self.assertIsNone(paths.namespace_of("40_Knowledge/knowledge-moc.md"))
        self.assertEqual(paths.topic_parts("40_Knowledge/work/infra/sites/x.md"), ("infra", "sites"))
        self.assertEqual(paths.namespace_dir("shared"), "40_Knowledge/shared")

    def test_ideas_anywhere_is_idea(self):
        sch = vault.load_schema(LIB / "schema.json")
        self.assertEqual(vault.infer_type("40_Knowledge/work/ideas/x.md", [], sch), ("note", "idea"))
        self.assertEqual(vault.infer_type("40_Knowledge/ideas/x.md", [], sch), ("note", "idea"))
        self.assertEqual(vault.infer_type("40_Knowledge/work/infra/x.md", [], sch), ("note", None))
        self.assertEqual(vault.infer_type("00_Inbox/x.md", ["idea"], sch), ("note", "idea"))  # tag still works


class NewType(KCase):
    extra = {
        "40_Knowledge/work/infra/locations/dc-north.md": SITE.format(s="dc-north", t="DC North", extra=""),
        "40_Knowledge/work/infra/locations/rack-1.md": SITE.format(
            s="rack-1", t="Rack 1", extra='part_of: "[[dc-north|DC North]]"\nuses: "[[billing|Billing System]]"\n'),
    }

    def test_unknown_before_valid_after(self):
        unk = self.codes("unknown-type")
        self.assertEqual(len(unk), 2)
        self.assertEqual(unk[0]["severity"], "error")
        self.assertIn("lib/schema.json › types", unk[0]["detail"])
        add_entity_type(self.v, "location")
        issues = self.validate()
        bad = [i for i in issues if i["code"] in ("unknown-type", "relation-source-type", "relation-target-type",
                                                  "type-folder-mismatch", "bad-id-format")]
        self.assertEqual(bad, [])          # @entity: part_of / uses accept the new type at once

    def test_kebab_type_ids_are_valid(self):
        self.v.put("40_Knowledge/work/infra/x.md", "---\nid: data-centre/x\ntype: note\ntitle: X\n---\n")
        self.assertEqual([i for i in self.codes("bad-id-format") if "x.md" in i["path"]], [])

    def test_unknown_kind_suggests_add_kind(self):
        self.v.put("40_Knowledge/work/infra/s.md", "---\nid: system/s\ntype: system\nkind: rack\ntitle: S\n"
                                                     "context: work\n---\n")
        uk = self.codes("unknown-kind")
        self.assertIn("lib/schema.json › kinds", uk[0]["detail"])


class Create(KCase):
    def test_system_lands_in_context_namespace(self):
        self.ok("create", "system", "Dashboard", "--context", "work", "--topic", "monitoring", "--apply")
        rel = "40_Knowledge/work/monitoring/dashboard.md"
        fmo = vault.Frontmatter(self.v.read(rel))
        self.assertEqual((fmo.get("type"), fmo.get("id"), fmo.get("context")), ("system", "system/dashboard", "work"))
        self.ok("create", "concept", "Idempotence", "--apply")                       # no context -> shared
        self.assertTrue((self.v.root / "40_Knowledge/shared/idempotence.md").is_file())
        self.ok("create", "note", "Zsh tips", "--in", "shared/tools/shell", "--apply")
        self.assertTrue((self.v.root / "40_Knowledge/shared/tools/shell/zsh-tips.md").is_file())
        self.ok("create", "note", "Recipe", "--namespace", "private", "--apply")      # namespace -> private
        self.assertEqual(vault.Frontmatter(self.v.read("40_Knowledge/private/recipe.md")).get("context"), "private")
        self.assertEqual(self.v.brain("validate").returncode, 0, self.v.brain("validate").stdout)

    def test_dry_run_and_limits(self):
        r = self.ok("create", "system", "Dashboard", "--context", "work")
        self.assertIn("40_Knowledge/work/dashboard.md", r.stdout)
        self.assertFalse((self.v.root / "40_Knowledge/work/dashboard.md").exists())
        self.assertEqual(self.v.brain("create", "note", "X", "--topic", "a/b/c/d/e/f/g").returncode, 2)  # max 6
        self.assertIn("a/b/c/d/e/f/x.md", self.ok("create", "note", "X", "--topic", "a/b/c/d/e/f").stdout)
        self.assertEqual(self.v.brain("create", "note", "X", "--in", "people").returncode, 2)       # registry
        self.assertEqual(self.v.brain("create", "note", "X", "--topic", "Bad Topic").returncode, 2)
        self.assertEqual(self.v.brain("create", "nope", "X").returncode, 2)

    def test_stem_collision_gets_namespace_prefix(self):
        r = self.ok("create", "system", "Billing", "--context", "work", "--apply")
        self.assertTrue((self.v.root / "40_Knowledge/work/work-billing.md").is_file(), r.stdout)
        self.ok("create", "system", "Billing", "--context", "work", "--apply")
        self.assertTrue((self.v.root / "40_Knowledge/work/work-billing-2.md").is_file())

    def test_new_type_after_add_type(self):
        self.assertEqual(self.v.brain("create", "location", "DC South").returncode, 2)
        add_entity_type(self.v, "location")
        self.ok("create", "location", "DC South", "--context", "work", "--topic", "infra", "--apply")
        fmo = vault.Frontmatter(self.v.read("40_Knowledge/work/infra/dc-south.md"))
        self.assertEqual(fmo.get("type"), "location")

    def test_slug_sets_stem_and_id(self):
        self.ok("create", "note", "A long human title", "--namespace", "private", "--slug", "short-stem", "--apply")
        fm = vault.Frontmatter(self.v.read("40_Knowledge/private/short-stem.md"))
        self.assertEqual((fm.get("id"), fm.get("title")), ("note/short-stem", "A long human title"))
        self.ok("create", "org", "Acme Corp", "--context", "work", "--slug", "acme", "--apply")
        self.assertTrue((self.v.root / "40_Knowledge/orgs/acme.md").exists())
        self.ok("create", "decision", "Something", "--context", "work", "--slug", "2026-01-01-choice", "--apply")
        made = [p.name for p in self.v.root.rglob("*-choice.md")]
        self.assertEqual(len(made), 1, made)
        self.assertNotIn("2026-01-01-choice", made[0][11:])


class ValidateKnowledge(KCase):
    extra = {
        "40_Knowledge/work/a/b/c/d/e/f/g/deep.md": "---\nid: note/deep\ntype: note\ntitle: H\n---\n",
        "40_Knowledge/work/a/b/c/d/e/f/ok.md": "---\nid: note/ok-depth\ntype: note\ntitle: OK\n---\n",
        "40_Knowledge/loose.md": "---\nid: note/loose\ntype: note\ntitle: V\n---\n",
        "40_Knowledge/knowledge-moc.md": "---\nid: map/knowledge-moc\ntype: map\nkind: moc\ntitle: Knowledge MOC\n---\n",
        "40_Knowledge/shared/concepts/billing.md": "---\nid: concept/billing-term\ntype: concept\ntitle: F\n---\n",
        "40_Knowledge/work/infra/term.md": "---\nid: concept/term\ntype: concept\ntitle: P\n---\n",
    }

    def test_codes(self):
        issues = self.validate()
        by = lambda c: sorted(i["path"] for i in issues if i["code"] == c)  # noqa: E731
        self.assertEqual(by("knowledge-depth"), ["40_Knowledge/work/a/b/c/d/e/f/g/deep.md"])  # max 6
        self.assertEqual(by("knowledge-loose"), ["40_Knowledge/loose.md"])
        self.assertEqual(by("stem-collision"), ["40_Knowledge/shared/concepts/billing.md",
                                                "40_Knowledge/work/billing/billing.md"])
        self.assertEqual(by("type-folder-mismatch"), [])   # system + concepts in arbitrary Knowledge folders
        self.assertTrue(all(i["severity"] == "warning" for i in issues if i["code"] in
                            ("knowledge-depth", "knowledge-loose", "stem-collision")))


class FolderHub(unittest.TestCase):
    def test_folder_hub_rule(self):
        self.assertTrue(vault.is_folder_hub("40_Knowledge/a/repos/repos-hub.md"))
        self.assertTrue(vault.is_folder_hub("40_Knowledge/a/servers/infrastructure-servers-31-hub.md"))
        self.assertTrue(vault.is_folder_hub("40_Knowledge/a/x/anything-hub.md", "map"))
        self.assertFalse(vault.is_folder_hub("40_Knowledge/a/repos/repo-infra-mcp-hub.md", "system"))


if __name__ == "__main__":
    unittest.main()
