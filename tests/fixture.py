"""Tiny fixture vault for the test suite: a temp dir with git, a few notes (area, project with an area edge, three
people, a system in the `work` knowledge namespace, a daily note) and helpers to run the brain CLI on it.

Layout: <tmp>/ws is the workspace (BRAIN_WORKSPACE; no templates/docs, so the built-in fallbacks run). By default
the vault root is the workspace itself (single root, like a fresh clone of this repo); `name=` puts the root in a
subfolder (multi-root tests). Nothing here touches a real vault: BRAIN_ROOT points the CLI at the fixture,
BRAIN_CACHE / BRAIN_WRITTEN keep the parse cache and the own-write ledger inside the temp dir, BRAIN_SCHEMA points
at a temp copy of lib/schema.json (so `brain schema … --apply` never edits the real one) and BRAIN_CONFIG at
<tmp>/brain.config.json, written only when the test passes `config=` (else the defaults apply).

Importing this module pins BRAIN_CONFIG for the test process too, so a user's brain.config.json never changes
what the in-process tests see.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BIN = REPO / "bin"
LIB = REPO / "lib"

_PIN = Path(tempfile.mkdtemp(prefix="brain-test-cfg-"))
os.environ["BRAIN_CONFIG"] = str(_PIN / "brain.config.json")   # missing file = defaults
os.environ["BRAIN_WORKSPACE"] = str(_PIN)
os.environ.setdefault("BRAIN_CACHE", str(_PIN / "graph.json"))
os.environ.setdefault("BRAIN_WRITTEN", str(_PIN / "written.json"))
for _k in ("BRAIN_ROOT", "BRAIN_GIT_DIR", "BRAIN_SCHEMA", "BRAIN_TODAY"):
    os.environ.pop(_k, None)
# test commits are never signed (a signing agent would block or prompt)
os.environ.update(GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="commit.gpgsign", GIT_CONFIG_VALUE_0="false",
                  GIT_CONFIG_KEY_1="tag.gpgsign", GIT_CONFIG_VALUE_1="false")

NOTES = {
    "CLAUDE.md": "# Fixture vault\n",
    "30_Areas/engineering/engineering-hub.md": """---
id: area/engineering
type: area
kind: role
title: Engineering
aliases: [Engineering - Hub]
context: work
tags: [area, ctx/work]
---

# Engineering

<!-- auto:projection start -->
<!-- auto:projection end -->
""",
    "20_Projects/work-alpha/CLAUDE.md": """---
id: project/work-alpha
type: project
title: Alpha
context: work
area: "[[engineering-hub|Engineering]]"
status: active
stakeholders: ["[[ada-example|Ada Example]]"]
tags: [ctx/work]
---

# Alpha

Led by [[ada-example|Ada Example]], runs on [[Billing System]].
""",
    "40_Knowledge/people/ada-example.md": """---
id: person/ada-example
type: person
title: Ada Example
context: work
aliases: [Ada]
tags: [ctx/work]
---

# Ada Example

## Log
""",
    "40_Knowledge/people/bob-sample.md": """---
id: person/bob-sample
type: person
title: Bob Sample
context: work
tags: [ctx/work]
---

# Bob Sample
""",
    "40_Knowledge/people/carol-demo.md": """---
id: person/carol-demo
type: person
title: Carol Demo
context: work
tags: [ctx/work]
---

# Carol Demo
""",
    "40_Knowledge/work/billing/billing.md": """---
id: system/billing
type: system
kind: internal
title: Billing System
context: work
area: "[[engineering-hub|Engineering]]"
tags: [ctx/work]
---

# Billing System
""",
    "10_Daily/2026/2026-09-24.md": """---
id: daily/2026-09-24
type: daily
title: 2026-09-24
tags: [daily]
---

# 2026-09-24

- with [[Ada]] about [[ada-example|her plan]] and [[ada-example]]; [[work-alpha/CLAUDE|Alpha]]
""",
}


class Vault:
    def __init__(self, extra=None, git=True, name=None, notes=None, config=None):
        self.tmp = Path(tempfile.mkdtemp(prefix="brain-test-")).resolve()
        self.ws = self.tmp / "ws"
        self.root = self.ws / name if name else self.ws
        self.root.mkdir(parents=True, exist_ok=True)
        for rel, text in {**(NOTES if notes is None else notes), **(extra or {})}.items():
            self.put(rel, text)
        self.schema = self.tmp / "schema.json"
        shutil.copyfile(LIB / "schema.json", self.schema)
        self.config = self.tmp / "brain.config.json"
        if config is not None:
            self.config.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
        self.env = dict(os.environ, BRAIN_ROOT=str(self.root), BRAIN_CACHE=str(self.tmp / "graph.json"),
                        BRAIN_WORKSPACE=str(self.ws), BRAIN_SCHEMA=str(self.schema),
                        BRAIN_CONFIG=str(self.config),
                        BRAIN_WRITTEN=str(self.tmp / "written.json"),
                        BRAIN_NO_CACHE="1", PYTHONDONTWRITEBYTECODE="1")
        if git:
            self.git("init", "-q")
            self.git("config", "user.email", "test@example.com")
            self.git("config", "user.name", "brain test")
            self.commit()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True)

    def commit(self, msg="fixture"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)

    def run(self, script, *args, cwd=None, env=None, stdin=None):
        return subprocess.run([sys.executable, str(script), *args], cwd=cwd or self.root, env=env or self.env,
                              capture_output=True, text=True, timeout=60, input=stdin)

    def brain(self, *args, **kw):
        """Run brainkg.py (what `brain <cmd>` dispatches to) on the fixture; -> CompletedProcess."""
        return self.run(BIN / "brainkg.py", *args, **kw)

    def ctx(self, *args, **kw):
        """Run context.py (what `brain context` dispatches to) on the fixture."""
        return self.run(BIN / "context.py", *args, **kw)

    def py(self, code, env=None):
        """Run a python snippet with lib/ importable under the fixture env (config-dependent module state)."""
        return subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(LIB)!r})\n" + code],
                              cwd=self.root, env=env or self.env, capture_output=True, text=True, timeout=60)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
