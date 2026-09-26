#!/usr/bin/env python3
"""daily.py - today's daily note for /morning (python3 stdlib only). Run from the workspace (BRAIN_ROOT for multi-root).

  daily.py [--date YYYY-MM-DD]                    ensure 10_Daily/YYYY/YYYY-MM-DD.md exists (`brain create daily`),
                                                  carry unchecked Top 3 items of the previous daily note over as
                                                  `- [ ] (from YYYY-MM-DD) …` (idempotent), print JSON: path, created,
                                                  carried, cursor (last /morning run log) and the Inbox state
  daily.py --briefing FILE [--date YYYY-MM-DD]    replace the <!-- auto:briefing --> block of the daily note with the
                                                  file's text (block created after the Top 3 section when missing)

Sections are found by content, not language: the Top 3 section is the first `## ` heading containing "Top 3"
(created as `## Top 3` when missing); the briefing is a managed block, so it can sit under any heading.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "lib"))
import paths  # noqa: E402
import vault  # noqa: E402

TODAY = dt.date.fromisoformat(os.environ["BRAIN_TODAY"]) if os.environ.get("BRAIN_TODAY") else dt.date.today()
TOP_RE = re.compile(r"^## [^\n]*Top 3[^\n]*\n(.*?)(?=^## |\Z)", re.M | re.S)
OPEN_RE = re.compile(r"^\s*- \[ \]\s+(?:\(from (\d{4}-\d{2}-\d{2})\)\s*)?(.+?)\s*$")
ANY_RE = re.compile(r"^\s*- \[[ xX]\]\s+(?:\(from [\d-]+\)\s*)?(.+?)\s*$")
B_START, B_END = "<!-- auto:briefing start -->", "<!-- auto:briefing end -->"
B_RE = re.compile(re.escape(B_START) + r".*?" + re.escape(B_END), re.S)


def ensure(root, date):
    p = paths.daily_path(date, root)
    if p.exists():
        return p, False
    r = subprocess.run([sys.executable, str(REPO / "bin" / "brainkg.py"), "create", "daily", date.isoformat(),
                        "--apply", "--allow-dirty"], cwd=root, capture_output=True, text=True, timeout=60)
    if not p.exists():  # CLI unavailable or refused: minimal note, same shape
        sys.stderr.write(r.stderr)
        vault.write(p, f"---\ntype: daily\ntitle: {date.isoformat()}\n---\n\n# {date.isoformat()}\n\n## Top 3\n\n## Log\n")
    return p, True


def ensure_top(text):
    if TOP_RE.search(text):
        return text
    m = re.search(r"^## ", text, re.M)
    block = "## Top 3\n\n"
    return text[:m.start()] + block + text[m.start():] if m else text.rstrip("\n") + "\n\n" + block


def carry_over(root, p, date):
    prev = [d for d in paths.iter_dailies(root) if d.stem < date.isoformat()]
    if not prev:
        return []
    src = vault.read(prev[-1]) or ""
    m = TOP_RE.search(src)
    items = []
    for ln in (m.group(1).splitlines() if m else []):
        om = OPEN_RE.match(ln)
        if om:
            items.append((om.group(1) or prev[-1].stem, om.group(2)))
    text = ensure_top(vault.read(p) or "")
    have = {vault.nfc(x.group(1)).casefold() for x in map(ANY_RE.match, TOP_RE.search(text).group(1).splitlines()) if x}
    new = [f"- [ ] (from {d}) {t}" for d, t in items if vault.nfc(t).casefold() not in have]
    if new:
        m = TOP_RE.search(text)
        lines, rest = m.group(1).rstrip("\n").split("\n"), list(new)
        for i, ln in enumerate(lines):  # fill the template's empty `- [ ]` placeholders first
            if rest and re.fullmatch(r"\s*- \[ \]\s*", ln):
                lines[i] = rest.pop(0)
        body = "\n".join(lines).strip("\n")
        body = "\n" + (body + "\n" if body else "") + "".join(x + "\n" for x in rest) + "\n"
        text = text[:m.start(1)] + body + text[m.end(1):]
    if text != vault.read(p):
        vault.write(p, text)
    return new


def cursor(root):
    logs = sorted((root / paths.LOGS / "morning").glob("[0-9]*.md")) if (root / paths.LOGS / "morning").is_dir() else []
    if not logs:
        return (TODAY - dt.timedelta(days=1)).isoformat()
    return logs[-1].name[:10]


def inbox(root):
    caps = [p for p in sorted((root / paths.INBOX).glob("*.md"))] if (root / paths.INBOX).is_dir() else []
    old = 0
    for p in caps:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        born = dt.date.fromisoformat(m.group(1)) if m else dt.date.fromtimestamp(p.stat().st_mtime)
        old += (TODAY - born).days > 7
    pending = []
    mdir = root / paths.MEETINGS
    for p in sorted(mdir.glob("*")) if mdir.is_dir() else []:
        if p.is_file() and p.suffix in (".md", ".txt", ".vtt"):
            fm, _ = vault.frontmatter(vault.read(p) or "")
            if fm.get("processed", "").lower() != "true":
                pending.append(paths.rel(p, root))
    return {"captures": len(caps), "older_than_7": old, "meetings_pending": pending}


def write_briefing(p, src):
    inner = Path(src).read_text(encoding="utf-8").strip("\n")
    block = f"{B_START}\n{inner}\n{B_END}"
    text = ensure_top(vault.read(p) or "")
    if B_RE.search(text):
        text = B_RE.sub(lambda _: block, text)
    else:
        m = TOP_RE.search(text)
        text = text[:m.end()].rstrip("\n") + "\n\n" + block + "\n\n" + text[m.end():].lstrip("\n")
    vault.write(p, text.rstrip("\n") + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=TODAY.isoformat())
    ap.add_argument("--briefing", metavar="FILE")
    args = ap.parse_args(argv)
    root = Path(paths.find_root())
    date = dt.date.fromisoformat(args.date)
    p, created = ensure(root, date)
    if args.briefing:
        write_briefing(p, args.briefing)
        print(json.dumps({"path": paths.rel(p, root), "briefing": "written"}))
        return 0
    carried = carry_over(root, p, date)
    print(json.dumps({"path": paths.rel(p, root), "created": created, "carried": carried,
                      "cursor": cursor(root), "inbox": inbox(root)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
