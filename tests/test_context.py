"""Tests for the agent-context layer: .claude/index.md, .claude/hot.md, condition triggers, the PostToolUse
validator (`brain validate --file`, `context.py --post-tool`), `brain find --text` ranking.
All on the temp fixture vault (fixture.Vault); BRAIN_TODAY pins the date."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import BIN, LIB, Vault  # noqa: E402

sys.path.insert(0, str(LIB))
import vault  # noqa: E402

TODAY = "2026-09-24"
CONFIG = {"vendor_dirs": ["40_Knowledge/private/vendor-docs"]}
EXTRA = {
    "20_Projects/work-alpha/migration-notes.md": """---
id: note/migration-notes
type: note
title: Migration notes
context: work
description: Summary from the frontmatter, which wins over the body.
---

# Migration notes

Body text that does not reach the index.
""",
    "40_Knowledge/shared/concepts/data-processing.md": """---
id: concept/data-processing
type: concept
title: Data processing
---

# Data processing

Pipeline for processing records. The second sentence stays out.
""",
    "40_Knowledge/shared/concepts/pipeline.md": """---
id: concept/pipeline
type: concept
title: Pipeline
---

About data in general: processing runs at night.
""",
    "40_Knowledge/private/vendor-docs/vendor-docs-moc.md": "---\nid: map/vendor-docs-moc\ntype: map\ntitle: Vendor MOC\n"
                                                          "---\n\nMap of vendor documentation.\n",
    "40_Knowledge/private/vendor-docs/vendor-loop.md": "---\nid: note/vendor-loop\ntype: note\ntitle: Vendor loop\n"
                                                      "---\n\nProcessing loop.\n",
    "99_Archives/work-old/CLAUDE.md": "---\nid: project/work-old\ntype: project\ntitle: Old\nstatus: done\n---\n\n"
                                      "Processing of old things.\n",
    "10_Daily/2026/2026-09-24.md": """---
id: daily/2026-09-24
type: daily
title: 2026-09-24
tags: [daily]
---

# 2026-09-24

## Top 3
- [ ] Call [[ada-example|Ada]]
- [x] Finished thing
- [ ]

## Log
- with [[Ada]] about [[ada-example|her plan]]
""",
    "00_Inbox/meetings/2026-09-22-a-transcript.md": "---\nprocessed: false\n---\ntext\n",
    "00_Inbox/meetings/2026-09-22-b-transcript.md": "---\nprocessed: true\n---\ntext\n",
    "50_Raw/meetings/2026/2026-09-23-c-transcript.md": "---\ntitle: c\nprocessed: true\n---\ntext\n",
    "00_Inbox/2026-09-01-old-capture.md": "---\ntitle: old\ncreated: 2026-09-01\n---\nx\n",
    "00_Inbox/2026-09-23-new-capture.md": "---\ntitle: new\ncreated: 2026-09-23\n---\nx\n",
    "50_Raw/logs/curator/2026-09-22-2200.md": "## Proposals\n1. older run — pending\n",
    "50_Raw/logs/curator/2026-09-23-2200.md": """## Proposals
1. [cur-0001] something — pending
2. [cur-0002] other — yes
3. [cur-0003] third — pending
""",
}


class ContextCase(unittest.TestCase):
    def setUp(self):
        self.v = Vault(EXTRA, config=CONFIG)
        self.v.env["BRAIN_TODAY"] = TODAY


    def tearDown(self):
        self.v.cleanup()


class Summary(unittest.TestCase):
    def test_frontmatter_description_wins(self):
        self.assertEqual(vault.note_summary({"description": "Text in **bold**."}, "Body."), "Text in bold.")

    def test_first_sentence_skips_headings_and_links(self):
        body = "# Heading\n\n<!-- x -->\n> quote\n\nChief Strategy Officer. Part of [[team-moc|Team MOC]].\n"
        self.assertEqual(vault.note_summary({}, body), "Chief Strategy Officer.")

    def test_truncated(self):
        s = vault.note_summary({}, "word " * 60)
        self.assertLessEqual(len(s), 101)
        self.assertTrue(s.endswith("…"))


class Index(ContextCase):
    def test_index_lines_and_exclusions(self):
        r = self.v.ctx("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        idx = self.v.read(".claude/index.md")
        self.assertIn("- [[work-alpha/CLAUDE|Alpha]] — project · work · active", idx)
        self.assertIn("[[migration-notes|Migration notes]] — note · work · Summary from the frontmatter", idx)
        self.assertIn("[[data-processing|Data processing]] — concept · Pipeline for processing records.", idx)
        self.assertIn("## 20_Projects", idx)
        self.assertIn("### work-alpha", idx)
        self.assertIn("Vendor MOC", idx)             # vendor MOC keeps one line
        self.assertNotIn("Vendor loop", idx)         # vendor docs out
        self.assertNotIn("work-old", idx)            # archives out
        self.assertNotIn("a-transcript", idx)        # transcripts out
        self.assertIn("1 daily notes 2026-09-24", idx)
        # project CLAUDE.md comes first inside its group
        self.assertLess(idx.index("work-alpha/CLAUDE"), idx.index("[[migration-notes|"))

    def test_deterministic_and_only_rewritten_on_change(self):
        self.v.ctx("--write")
        p = self.v.root / ".claude/index.md"
        first, m1 = p.read_text(), p.stat().st_mtime_ns
        r = self.v.ctx("--write")
        self.assertIn("nothing (unchanged)", r.stdout)
        self.assertEqual(p.read_text(), first)
        self.assertEqual(p.stat().st_mtime_ns, m1)


class HotAndTriggers(ContextCase):
    def test_triggers(self):
        out = self.v.ctx("--triggers").stdout
        self.assertIn("▸ 1 transcript waiting → /brain:process-meetings", out)   # b processed, c archived in 50_Raw
        self.assertIn("▸ 1 capture in 00_Inbox older than 7 days → /brain:weekly", out)
        self.assertIn("▸ 2 proposals from curator waiting for an answer (2026-09-23-2200.md)", out)  # newest log only

    def test_hot_and_hook(self):
        r = self.v.ctx("--hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        hot = self.v.read(".claude/hot.md")
        self.assertLessEqual(len(hot), 901)
        self.assertIn("# Hot — 2026-09-24 (Thursday)", hot)
        self.assertIn("Active projects 1: work 1", hot)
        self.assertIn("Top 3 today (1 done): Call Ada", hot)
        self.assertIn("▸ 1 transcript waiting", hot)
        self.assertEqual(r.stdout.strip(), hot.strip())
        self.assertLess(len(r.stdout), 1500)
        self.assertTrue((self.v.root / ".claude/index.md").exists())

    def test_hook_never_fails(self):
        env = dict(self.v.env, BRAIN_ROOT=str(self.v.tmp / "does-not-exist"))
        r = subprocess.run([sys.executable, str(BIN / "context.py"), "--hook"], env=env, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
        self.v.config.write_text("{broken", encoding="utf-8")        # a broken config never blocks the session
        r = self.v.ctx("--hook")
        self.assertEqual((r.returncode, r.stderr), (0, ""))


class ValidateFile(ContextCase):
    def test_validate_file_errors_and_json(self):
        self.v.put("40_Knowledge/shared/concepts/broken.md", "---\nid: concept/broken\ntype: concept\ntitle: Broken\n"
                   "---\n\nLink to [[exists-nowhere]].\n")
        r = self.v.brain("validate", "--file", "40_Knowledge/shared/concepts/broken.md", "--json")
        self.assertEqual(r.returncode, 1)
        d = json.loads(r.stdout)
        self.assertEqual(d["file"], "40_Knowledge/shared/concepts/broken.md")
        self.assertIn("broken-link", [i["code"] for i in d["issues"] if i["severity"] == "error"])
        ok = self.v.brain("validate", "--file", "40_Knowledge/people/ada-example.md")
        self.assertEqual(ok.returncode, 0, ok.stdout)

    def test_validate_file_naming(self):
        self.v.put("40_Knowledge/shared/concepts/Bad Náme.md", "---\nid: concept/bad-name\ntype: concept\ntitle: X\n---\n")
        d = json.loads(self.v.brain("validate", "--file", "40_Knowledge/shared/concepts/Bad Náme.md", "--json").stdout)
        self.assertIn("name-not-kebab", [i["code"] for i in d["issues"]])

    def hook(self, rel):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "cwd": str(self.v.root),
                   "tool_input": {"file_path": str(self.v.root / rel)}}
        return self.v.ctx("--post-tool", stdin=json.dumps(payload))

    def test_post_tool_exit_codes(self):
        self.v.put("40_Knowledge/shared/concepts/broken.md", "---\nid: concept/broken\ntype: concept\ntitle: R\n---\n"
                   "[[nowhere-at-all]]\n")
        r = self.hook("40_Knowledge/shared/concepts/broken.md")
        self.assertEqual(r.returncode, 2)
        self.assertIn("broken-link", r.stderr)
        self.assertEqual(self.hook("40_Knowledge/people/ada-example.md").returncode, 0)
        self.v.put(".claude/foo.md", "[[nowhere-at-all]]\n")
        self.v.put("50_Raw/logs/curator/x.md", "[[nowhere-at-all]]\n")
        self.v.put("docs/guide.md", "[[nowhere-at-all]]\n")
        for rel in (".claude/foo.md", "50_Raw/logs/curator/x.md", "CLAUDE.md", "docs/guide.md"):
            r = self.hook(rel)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), rel)
        r = self.v.ctx("--post-tool", stdin="not json")
        self.assertEqual(r.returncode, 0)


class FindText(ContextCase):
    def test_ranking_diacritics_and_scope(self):
        self.v.put("40_Knowledge/shared/concepts/cafe.md", "---\nid: concept/cafe\ntype: concept\ntitle: Café\n---\n")
        d = json.loads(self.v.brain("find", "--text", "processing", "--json").stdout)
        paths_ = [x["path"] for x in d]
        self.assertEqual(paths_[0], "40_Knowledge/shared/concepts/data-processing.md")   # title hit first
        self.assertIn("40_Knowledge/shared/concepts/pipeline.md", paths_)                # body hit
        self.assertNotIn("99_Archives/work-old/CLAUDE.md", paths_)
        self.assertNotIn("40_Knowledge/private/vendor-docs/vendor-loop.md", paths_)
        all_ = [x["path"] for x in json.loads(self.v.brain("find", "--text", "processing", "--all", "--json").stdout)]
        self.assertIn("99_Archives/work-old/CLAUDE.md", all_)
        self.assertIn("40_Knowledge/private/vendor-docs/vendor-loop.md", all_)
        hits = [x["path"] for x in json.loads(self.v.brain("find", "--text", "cafe", "--json").stdout)]
        self.assertEqual(hits, ["40_Knowledge/shared/concepts/cafe.md"])                 # diacritics folded

    def test_word_boundary_and_all_tokens(self):
        # "data" must not match inside "metadata" (word-start matching)
        self.v.put("40_Knowledge/shared/concepts/meta.md", "---\nid: concept/meta\ntype: concept\ntitle: Meta\n---\n"
                   "metadata\n")
        hits = [x["path"] for x in json.loads(self.v.brain("find", "--text", "data", "--json").stdout)]
        self.assertNotIn("40_Knowledge/shared/concepts/meta.md", hits)
        # any-match, ranked by distinct words hit: both words beat one word; stopwords ("where", "is") ignored
        hits = [x["path"] for x in json.loads(self.v.brain("find", "--text", "where is pipeline night",
                                                           "--json").stdout)]
        self.assertEqual(hits[0], "40_Knowledge/shared/concepts/pipeline.md")
        self.assertIn("40_Knowledge/shared/concepts/data-processing.md", hits)       # "Pipeline" in its body only

    def test_stem_prefix(self):
        # "processed" ~ "processing" through the 5-char stem
        hits = [x["path"] for x in json.loads(self.v.brain("find", "--text", "processed", "--json").stdout)]
        self.assertEqual(hits[0], "40_Knowledge/shared/concepts/data-processing.md")
        r = self.v.brain("find", "--text", "where is it")
        self.assertNotEqual(r.returncode, 0)                                # only stopwords


class IndexCollapse(unittest.TestCase):
    def setUp(self):
        extra = dict(EXTRA)
        for site in ("a", "b"):
            for i in range(15):
                extra[f"40_Knowledge/work/sites/eu/{site}/servers/{site}-srv{i}.md"] = (
                    f"---\nid: system/{site}-srv{i}\ntype: system\nkind: server\ntitle: {site} srv{i}\n---\n")
        for i in range(30):
            extra[f"40_Knowledge/people/person-{i}.md"] = (f"---\nid: person/person-{i}\ntype: person\n"
                                                          f"title: Person {i}\n---\n")
        self.v = Vault(extra, config=CONFIG)
        self.v.env["BRAIN_TODAY"] = TODAY

    def tearDown(self):
        self.v.cleanup()

    def test_family_collapses_registry_stays(self):
        r = self.v.ctx("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        idx = self.v.read(".claude/index.md")
        self.assertIn("- ▸ 40_Knowledge/work/sites/*/*/servers/ — 30 notes in 2 folders · system/server 30", idx)
        self.assertIn("`brain find --kind server --text …`", idx)
        self.assertNotIn("[[a-srv3|", idx)
        self.assertIn("[[person-29|Person 29]]", idx)      # people registry is never collapsed


if __name__ == "__main__":
    unittest.main()
