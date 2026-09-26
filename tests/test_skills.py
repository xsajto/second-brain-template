"""Smoke tests for the project skills (.claude/skills/): SKILL.md frontmatter and referenced scripts, and each helper
script on the temp fixture vault (fixture.Vault): weekly/review.py, morning/daily.py, process-meetings/route.py and
check_evidence.py, people/people.py, onboarding/sessions.py."""
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
S = {name: SKILLS / name / "scripts" for name in EXPECTED}
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


class Review(Case):
    extra = {
        "00_Inbox/2026-09-01-idea.md": "---\ntitle: Idea\n---\n\nBob Sample suggested it.\n",
        "00_Inbox/meetings/2026-09-25-sync.md": "---\ntitle: Sync\n---\n\ntranscript\n",
        "40_Knowledge/work/billing/runbook.md": "---\ntitle: Runbook\n---\n\nAsk Carol Demo before touching Billing System.\n\n"
        "- [risk] Invoices lag — [[ada-example]], 2025-01-01, low ^f-aaa111\n- [risk] No provenance ^f-aaa222\n",
        "40_Knowledge/people/ada-copy.md": "---\ntype: person\ntitle: Ada Example\n---\n\n# Ada\n",
        "50_Raw/logs/morning/2026-09-24-0800.md": "# run\n\n## Friction\n- calendar token expired\n",
        "50_Raw/logs/morning/2026-09-25-0800.md": "# run\n\n## Friction\n- Calendar token expired\n",
    }
    script = S["weekly"] / "review.py"

    def test_links_finds_unlinked_mentions_and_orphans(self):
        rows = {r["note"]: r for r in self.run_json(self.script, "links", "--days", "2")["rows"]}
        rb = rows["40_Knowledge/work/billing/runbook.md"]
        self.assertEqual({u["link"] for u in rb["unlinked"]}, {"[[carol-demo|Carol Demo]]", "[[billing|Billing System]]"})
        self.assertTrue(rows["00_Inbox/2026-09-01-idea.md"]["orphan"])

    def test_inbox_projects_portfolio(self):
        ib = self.run_json(self.script, "inbox")
        self.assertEqual(ib["older_than_7"], 1)
        self.assertEqual(ib["meetings_pending"], ["00_Inbox/meetings/2026-09-25-sync.md"])
        pr = self.run_json(self.script, "projects")["projects"]
        self.assertEqual([p["slug"] for p in pr], ["work-alpha"])
        self.assertTrue(pr[0]["goal_missing"])
        out = self.run_json(self.script, "portfolio", "--write")
        self.assertTrue(out["written"])
        text = self.v.read("CLAUDE.md")
        self.assertIn("<!-- auto:portfolio start -->", text)
        self.assertIn("work-alpha/CLAUDE", text)
        self.assertFalse(self.run_json(self.script, "portfolio", "--write")["written"])  # idempotent

    def test_facts_dupes_friction(self):
        f = self.run_json(self.script, "facts")
        self.assertEqual([x["id"] for x in f["no_provenance"]], ["f-aaa222"])
        self.assertEqual([x["id"] for x in f["low_confidence_old"]], ["f-aaa111"])
        d = self.run_json(self.script, "dupes")["groups"]
        self.assertTrue(any(set(g["notes"]) == {"40_Knowledge/people/ada-copy.md", "40_Knowledge/people/ada-example.md"}
                            for g in d))
        fr = self.run_json(self.script, "friction", "--days", "7")["items"]
        self.assertEqual((fr[0]["skill"], fr[0]["count"]), ("morning", 2))


class Daily(Case):
    extra = {"10_Daily/2026/2026-09-25.md": "---\ntitle: 2026-09-25\n---\n\n## Top 3\n- [ ] Ship Alpha\n- [x] Done\n"
                                            "- [ ] (from 2026-09-20) Old item\n\n## Log\n"}
    script = S["morning"] / "daily.py"

    def test_create_carry_over_and_briefing(self):
        out = self.run_json(self.script)
        self.assertTrue(out["created"])
        self.assertEqual(out["carried"], ["- [ ] (from 2026-09-25) Ship Alpha", "- [ ] (from 2026-09-20) Old item"])
        self.assertEqual(self.run_json(self.script)["carried"], [])  # idempotent
        brief = self.v.tmp / "brief.md"
        brief.write_text("### Calendar\n- 09:00 Standup\n", encoding="utf-8")
        self.run_json(self.script, "--briefing", str(brief))
        self.run_json(self.script, "--briefing", str(brief))
        text = self.v.read("10_Daily/2026/2026-09-26.md")
        self.assertEqual(text.count("<!-- auto:briefing start -->"), 1)
        self.assertIn("- 09:00 Standup", text)


class Route(Case):
    extra = {
        "20_Projects/work-beta/CLAUDE.md": "---\ntype: project\ntitle: Beta Launch\ncontext: work\nstatus: active\n"
                                          "keywords: [pricing, launch]\n---\n\n# Beta\n",
        "30_Areas/engineering/meetings/standup.md": "---\ntitle: Standup\nmeeting_match: [standup]\n---\n\n# Standup\n",
        "00_Inbox/meetings/2026-09-25-pricing.md": "---\ntitle: Pricing review\n---\n\nWe discussed the launch and pricing.\n",
        "00_Inbox/meetings/2026-09-25-standup.md": "---\ntitle: Daily standup\n---\n\nPricing and Alpha.\n",
        "00_Inbox/meetings/2026-09-25-misc.md": "---\ntitle: Coffee\n---\n\nNothing specific.\n",
    }
    script = S["process-meetings"] / "route.py"

    def test_project_ritual_ambiguous(self):
        r = self.run_json(self.script, "00_Inbox/meetings/2026-09-25-pricing.md")
        self.assertEqual((r["route"], r["target"]), ("work-beta", "20_Projects/work-beta/"))
        r = self.run_json(self.script, "00_Inbox/meetings/2026-09-25-standup.md")
        self.assertEqual(r["target"], "30_Areas/engineering/meetings/standup.md")
        r = self.run_json(self.script, "00_Inbox/meetings/2026-09-25-misc.md")
        self.assertEqual((r["route"], r["target"]), ("ambiguous", "00_Inbox/meetings/"))
        self.assertEqual(len(self.run_json(self.script, "--list")["projects"]), 2)


class Evidence(Case):
    script = S["process-meetings"] / "check_evidence.py"

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


class People(Case):
    script = S["people"] / "people.py"

    def test_block_log_map(self):
        blk = self.v.tmp / "blk.md"
        blk.write_text("**Style:** short and direct\n**Relations:**\n- [[bob-sample|Bob Sample]] — works with — 4\n",
                       encoding="utf-8")
        note = "40_Knowledge/people/ada-example.md"
        self.run_json(self.script, "--write-block", note, "--from", str(blk))
        self.run_json(self.script, "--write-block", note, "--from", str(blk))
        self.run_json(self.script, "--log", note, "--line", "profile created (3 sources)")
        text = self.v.read(note)
        self.assertEqual(text.count("<!-- auto:profile start -->"), 1)
        self.assertIn(f"- {TODAY} — profile created (3 sources)", text)
        rows = {r["name"]: r for r in self.run_json(self.script, "--list", "--context", "work")}
        self.assertEqual(rows["Ada Example"]["relations"], [{"to": "Bob Sample", "type": "works with", "strength": 4}])
        out = self.run_json(self.script, "--map", "work", "--write")
        self.assertEqual(out.strip(), "30_Areas/work/relationship-map.md")
        self.assertIn("==>|works with|", self.v.read("30_Areas/work/relationship-map.md"))


class Sessions(Case):
    script = S["onboarding"] / "sessions.py"

    def test_list_and_extract(self):
        proj = self.v.tmp / "claude" / "projects" / "-home-ada-code"
        proj.mkdir(parents=True)
        lines = [{"type": "user", "cwd": "/home/ada/code", "timestamp": "2026-09-01T10:00:00Z",
                  "message": {"role": "user", "content": "Plan the Acme Corp migration with Bob"}},
                 {"type": "assistant", "timestamp": "2026-09-01T10:01:00Z",
                  "message": {"role": "assistant", "content": [{"type": "text", "text": "Sure, three steps."},
                                                               {"type": "tool_use", "name": "Bash", "input": {}}]}},
                 {"type": "user", "timestamp": "2026-09-01T10:02:00Z",
                  "message": {"role": "user", "content": "<system-reminder>noise</system-reminder>"}}]
        (proj / "abc12345.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
        rows = self.run_json(self.script, "--list", "--base", str(proj.parent))
        self.assertEqual((rows[0]["cwd"], rows[0]["sessions"]), ("/home/ada/code", 1))
        text = self.run_json(self.script, "--extract", str(proj), raw=True)
        self.assertIn("Acme Corp migration", text)
        self.assertIn("three steps", text)
        self.assertNotIn("noise", text)


if __name__ == "__main__":
    unittest.main()
