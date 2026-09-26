#!/usr/bin/env python3
"""sessions.py - read past Claude Code sessions for the onboarding import (python3 stdlib only, read-only).

  sessions.py --list [--base DIR]                       one row per project folder: working dir, sessions, first/last
                                                        date, size (JSON)
  sessions.py --extract PATH [--since YYYY-MM-DD] [--max-chars N] [--out FILE]
                                                        plain text of the user's and Claude's messages of one project
                                                        folder (all its *.jsonl) or one session file, oldest first;
                                                        tool calls, tool results and system reminders are dropped

DIR defaults to $CLAUDE_CONFIG_DIR/projects, else ~/.claude/projects. Nothing is copied into the vault by this
script; the onboarding skill reads the extract and proposes notes.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

SKIP_RE = re.compile(r"^\s*<(system-reminder|command-|local-command|task-notification|user-prompt-submit-hook)")
PER_MSG = 1500


def base_dir(arg=None):
    if arg:
        return Path(arg).expanduser()
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(cfg).expanduser() if cfg else Path.home() / ".claude") / "projects"


def records(f):
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    yield json.loads(ln)
                except ValueError:
                    continue
    except OSError:
        return


def text_of(msg):
    c = (msg or {}).get("content")
    if isinstance(c, str):
        parts = [c]
    elif isinstance(c, list):
        parts = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
    else:
        parts = []
    parts = [p for p in parts if p.strip() and not SKIP_RE.match(p)]
    return re.sub(r"<system-reminder>.*?</system-reminder>", "", "\n".join(parts), flags=re.S).strip()


def cmd_list(base):
    rows = []
    for d in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        files = sorted(d.glob("*.jsonl"))
        if not files:
            continue
        cwd, stamps = "", []
        for f in files:
            for r in records(f):
                cwd = cwd or r.get("cwd", "")
                if r.get("timestamp"):
                    stamps.append(r["timestamp"][:10])
        rows.append({"folder": str(d), "cwd": cwd, "sessions": len(files),
                     "first": min(stamps) if stamps else "", "last": max(stamps) if stamps else "",
                     "kb": sum(f.stat().st_size for f in files) // 1024})
    rows.sort(key=lambda r: r["last"], reverse=True)
    return rows


def cmd_extract(path, since, max_chars):
    p = Path(path).expanduser()
    files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    items = []
    for f in files:
        for r in records(f):
            if r.get("type") not in ("user", "assistant") or r.get("isMeta"):
                continue
            ts = (r.get("timestamp") or "")[:16].replace("T", " ")
            if since and ts[:10] < since:
                continue
            t = text_of(r.get("message"))
            if t:
                items.append((ts, r["type"], f.stem[:8], t[:PER_MSG] + (" …" if len(t) > PER_MSG else "")))
    items.sort()
    out, total = [], 0
    for ts, role, sid, t in items:
        chunk = f"[{ts} {sid} {role}] {t}\n"
        if max_chars and total + len(chunk) > max_chars:
            out.append(f"[… truncated at {max_chars} chars; use --since to narrow]\n")
            break
        out.append(chunk)
        total += len(chunk)
    return "".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--base")
    ap.add_argument("--extract", metavar="PATH")
    ap.add_argument("--since", default="")
    ap.add_argument("--max-chars", type=int, default=200000)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.list:
        print(json.dumps(cmd_list(base_dir(a.base)), ensure_ascii=False, indent=1))
    elif a.extract:
        text = cmd_extract(a.extract, a.since, a.max_chars)
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
            print(json.dumps({"out": a.out, "chars": len(text)}))
        else:
            sys.stdout.write(text)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
