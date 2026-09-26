"""Smoke tests for the project skills (.claude/skills/): SKILL.md frontmatter and referenced scripts, and each helper
script on the temp fixture vault (fixture.Vault): process-meetings/check_evidence.py."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import REPO, Vault  # noqa: E402

SKILLS = REPO / ".claude" / "skills"
EXPECTED = {"onboarding", "morning", "weekly", "process-meetings", "research", "new-project", "people", "correct", "sync"}
TODAY = "2026-09-26"


class SkillFiles(unittest.TestCase):
    def test_skill_md_frontmatter_and_script_refs(self):
        found = {p.parent.name for p in SKILLS.glob("*/SKILL.md")}
        self.assertEqual(found, EXPECTED)
        for name in sorted(found):
            text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            fm = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
            self.assertTrue(fm, name)
            self.assertRegex(fm.group(1), rf"(?m)^name: {re.escape(name)}$")
            self.assertRegex(fm.group(1), r"(?m)^description: .{40,}")
            self.assertLess(len(text.splitlines()), 220 if name == "onboarding" else 150, name)
            for ref in re.findall(r"\.claude/skills/([\w-]+/scripts/[\w.]+\.py)", text):
                self.assertTrue((SKILLS / ref).is_file(), f"{name}: missing {ref}")

    def test_scripts_have_help(self):
        import subprocess
        for py in sorted(SKILLS.glob("*/scripts/*.py")):
            r = subprocess.run([sys.executable, str(py), "--help"], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, f"{py}: {r.stderr}")


class Case(unittest.TestCase):
    extra = {}

    def setUp(self):
        self.v = Vault(self.extra)
        self.env = dict(self.v.env, BRAIN_TODAY=TODAY)

    def tearDown(self):
        self.v.cleanup()

    def run_json(self, script, *args, code=0, raw=False):
        r = self.v.run(script, *args, env=self.env)
        self.assertEqual(r.returncode, code, r.stderr + r.stdout)
        return r.stdout if raw or not r.stdout.strip().startswith(("{", "[")) else json.loads(r.stdout)


class Evidence(Case):
    script = SKILLS / "process-meetings" / "scripts" / "check_evidence.py"

    def test_found_missing_marked(self):
        src = self.v.put("src.md", 'Ada: budget is 12,500 EUR, launch on 14.10. at 9:30, up 15 percent. '
                                   '"we ship the beta to five pilots" she said.\n')
        note = self.v.put("2026-09-26-sync.md", '---\ndate: 2026-09-26\n---\n# Sync 2026-09-26\n'
                                                '- Budget 12 500 EUR, launch 2026-10-14 at 9:30, +15 %.\n'
                                                '- "we ship the beta to five pilots"\n- Cost 7000 (unverified)\n')
        r = self.run_json(self.script, str(note), "--source", str(src), "--json")
        self.assertEqual(r["counts"]["MISSING"], 0, r)
        self.assertEqual(r["counts"]["MARKED"], 1)
        self.v.put("2026-09-26-sync.md", "# Sync\n- Headcount 42.\n")
        r = self.run_json(self.script, str(note), "--source", str(src), "--json", code=1)
        self.assertEqual(r["counts"]["MISSING"], 1)


if __name__ == "__main__":
    unittest.main()
