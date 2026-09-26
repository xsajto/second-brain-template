"""Tests for lib/config.py: defaults, deep merge, per-context/per-root defaults, config checks."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import LIB, REPO  # noqa: E402

sys.path.insert(0, str(LIB))
import config  # noqa: E402


class Config(unittest.TestCase):
    def write(self, data):
        p = Path(tempfile.mkdtemp(prefix="brain-cfg-")) / "brain.config.json"
        p.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
        return p

    def test_missing_file_is_defaults(self):
        cfg = config.load(Path(tempfile.mkdtemp()) / "none.json")
        self.assertEqual(list(cfg["contexts"]), ["work", "private"])
        self.assertEqual(cfg["roots"], {".": {"contexts": ["work", "private"]}})
        self.assertEqual(cfg["folders"]["people"], "40_Knowledge/people")
        self.assertEqual(config.check(cfg), [])

    def test_deep_merge_and_context_defaults(self):
        cfg = config.load(self.write({"folders": {"people": "40_Knowledge/team"},
                                      "contexts": {"client": {}, "home": {"slug": "hm"}}}))
        self.assertEqual(cfg["folders"]["people"], "40_Knowledge/team")
        self.assertEqual(cfg["folders"]["orgs"], "40_Knowledge/orgs")          # other defaults kept
        self.assertEqual(list(cfg["contexts"]), ["client", "home"])             # contexts replace the defaults
        self.assertEqual(cfg["contexts"]["client"], {"slug": "client", "namespace": "client",
                                                     "primary_area": "30_Areas/client"})
        self.assertEqual(cfg["roots"]["."]["contexts"], ["client", "home"])      # root default = every context

    def test_check_reports_problems(self):
        cfg = config.load(self.write({"roots": {"a": {"contexts": ["x"]}},
                                      "contexts": {"one": {"slug": "s"}, "two": {"slug": "s"}},
                                      "folders": {"people": "40_Knowledge/Team Members"}}))
        probs = config.check(cfg)
        self.assertIn("root a: unknown context x", probs)
        self.assertIn("project slug prefix s used by several contexts", probs)
        self.assertTrue(any(p.startswith("folders.people") for p in probs))
        self.assertTrue(config.check(path=self.write("{nope"))[0].startswith("invalid JSON"))

    def test_example_config_is_valid_and_matches_defaults(self):
        ex = REPO / "brain.config.example.json"
        cfg = config.load(ex)
        self.assertEqual(config.check(cfg), [])
        defaults = config.load(Path(tempfile.mkdtemp()) / "none.json")
        self.assertEqual({k: v for k, v in cfg.items() if k != "user"},
                         {k: v for k, v in defaults.items() if k != "user"})


if __name__ == "__main__":
    unittest.main()
