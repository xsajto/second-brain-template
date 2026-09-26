"""A vault with localized (Czech) folder names, two roots and its own contexts runs on the engine purely via
brain.config.json: registries, project/area subfolders, companions, labels, weekdays, stopwords and the pending
marker all come from the config. Neutral words only; the people are fictional."""
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import Vault  # noqa: E402

CONFIG = {
    "language": "cs",
    "roots": {"prace": {"contexts": ["prace"]}, "domov": {"contexts": ["soukrome", "spolek"]}},
    "contexts": {"prace": {"slug": "pr"}, "soukrome": {"slug": "sou"}, "spolek": {"slug": "spo"}},
    "folders": {"people": "40_Knowledge/lide", "orgs": "40_Knowledge/organizace", "meetings": "schuzky",
                "decisions": "rozhodnuti", "notes": "poznamky", "outputs": "vystupy", "sources": "podklady",
                "ideas": "napady", "reports": "50_Raw/reporty", "relationship_map": "mapa-vztahu.md",
                "templates": "_templates", "system_docs": "_system"},
    "companions": ["registr-prepisu.md"],
    "labels": {"project": "Projekty", "person": "Lidé", "decision": "Rozhodnutí"},
    "weekdays": ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"],
    "stopwords": ["kde", "je"],
    "pending_marker": "čeká",
}
NOTES = {
    "CLAUDE.md": "# Práce\n",
    "30_Areas/vedeni/vedeni-hub.md": "---\nid: area/vedeni\ntype: area\nkind: role\ntitle: Vedení\ncontext: prace\n"
                                     "primary: true\n---\n\n# Vedení\n",
    "30_Areas/vedeni/mapa-vztahu.md": "---\nid: map/mapa-vztahu\ntype: map\ntitle: Mapa vztahů\ncontext: prace\n---\n",
    "30_Areas/vedeni/registr-prepisu.md": "---\nid: note/registr-prepisu\ntype: note\ntitle: Registr\n---\n",
    "30_Areas/vedeni/rozhodnuti/2026-09-01-volba.md": "---\nid: decision/volba\ntitle: Volba\ndate: 2026-09-01\n"
                                                      "context: prace\n---\n\nVolba nástroje.\n",
    "20_Projects/pr-alfa/CLAUDE.md": "---\nid: project/pr-alfa\ntype: project\ntitle: Alfa\ncontext: prace\n"
                                     "status: active\narea: \"[[vedeni-hub|Vedení]]\"\n"
                                     "stakeholders: [\"[[ada-example|Ada Example]]\"]\n---\n\n# Alfa\n",
    "20_Projects/pr-alfa/schuzky/2026-09-02-porada.md": "---\nid: meeting/porada\ntitle: Porada\ncontext: prace\n---\n",
    "40_Knowledge/lide/ada-example.md": "---\nid: person/ada-example\ntitle: Ada Example\ncontext: prace\n---\n",
    "40_Knowledge/organizace/acme-corp.md": "---\nid: org/acme-corp\ntitle: Acme Corp\n---\n",
    "40_Knowledge/prace/napady/napad.md": "---\nid: note/napad\ntitle: Nápad\n---\n\nZpracování dat v noci.\n",
    "10_Daily/2026/2026-09-24.md": "---\nid: daily/2026-09-24\ntype: daily\ntitle: 2026-09-24\n---\n\n## Top 3\n- [ ] Úkol\n",
    "50_Raw/logs/kurator/2026-09-23-2200.md": "1. návrh — čeká\n2. jiný — ano\n",
}


class LocalizedConfig(unittest.TestCase):
    def setUp(self):
        self.v = Vault(name="prace", notes=NOTES, config=CONFIG)
        (self.v.ws / "domov/20_Projects").mkdir(parents=True)
        (self.v.ws / "domov/CLAUDE.md").write_text("# Domov\n", encoding="utf-8")
        self.v.env["BRAIN_TODAY"] = "2026-09-24"

    def tearDown(self):
        self.v.cleanup()

    def typ(self, note):
        r = self.v.brain("show", note, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        return d["type"], d["kind"]

    def test_types_from_localized_folders(self):
        self.assertEqual(self.typ("ada-example")[0], "person")
        self.assertEqual(self.typ("acme-corp")[0], "org")
        self.assertEqual(self.typ("2026-09-01-volba")[0], "decision")
        self.assertEqual(self.typ("2026-09-02-porada")[0], "meeting")
        self.assertEqual(self.typ("napad"), ("note", "idea"))

    def test_validate_clean_and_companions(self):
        d = json.loads(self.v.brain("validate", "--json").stdout)
        self.assertEqual(d["errors"], 0, d)
        self.assertEqual([i for i in d["issues"] if i["code"] in ("branch-leaf", "type-folder-mismatch")], [])
        self.v.put("40_Knowledge/lide/omyl.md", "---\nid: org/omyl\ntype: org\ntitle: Omyl\n---\n")
        d = json.loads(self.v.brain("validate", "--json").stdout)
        self.assertIn("40_Knowledge/lide/omyl.md", [i["path"] for i in d["issues"] if i["code"] == "type-folder-mismatch"])

    def test_create_uses_localized_destinations(self):
        r = self.v.brain("create", "person", "Bob Sample", "--context", "prace", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.v.root / "40_Knowledge/lide/bob-sample.md").is_file())
        r = self.v.brain("create", "decision", "Rozpočet", "--context", "prace", "--apply")   # primary area
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(list((self.v.root / "30_Areas/vedeni/rozhodnuti").glob("*-rozpocet.md"))), 1)
        r = self.v.brain("create", "project", "Beta", "--context", "prace", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.v.root / "20_Projects/pr-beta/CLAUDE.md").is_file())
        r = self.v.brain("create", "note", "Recept", "--namespace", "soukrome")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("create it in root domov/", r.stderr)

    def test_labels_weekdays_stopwords_marker(self):
        self.assertEqual(self.v.brain("project", "vedeni", "--write", "--apply").returncode, 0)
        hub = self.v.read("30_Areas/vedeni/vedeni-hub.md")
        self.assertIn("**Projekty (1)**", hub)
        self.assertIn("**Rozhodnutí (1)**", hub)
        r = self.v.ctx("--hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(čtvrtek)", r.stdout)
        self.assertIn("▸ 1 proposal from kurator", r.stdout)
        hits = [x["path"] for x in json.loads(self.v.brain("find", "--text", "kde je zpracování", "--json").stdout)]
        self.assertEqual(hits, ["40_Knowledge/prace/napady/napad.md"])
        self.assertNotEqual(self.v.brain("find", "--text", "kde je").returncode, 0)     # only stopwords


if __name__ == "__main__":
    unittest.main()
