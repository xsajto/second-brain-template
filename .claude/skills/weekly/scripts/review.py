#!/usr/bin/env python3
"""review.py - deterministic scans for /morning and /weekly (python3 stdlib only, read-only unless --write).

Run from the workspace (or set BRAIN_ROOT for a multi-root vault). Output is JSON.

  links    [--since YYYY-MM-DD | --days N] [--all]   link review of notes changed since the date (git + mtime; --all
                                                    = every note): rows for notes with unlinked mentions of entities
                                                    (title/alias, word match) or no edges at all (orphan)
  inbox                                             captures in 00_Inbox/ (age, title) + pending transcripts
  projects                                          active/paused projects: status, days quiet, open and overdue
                                                    next steps, goal, last meeting
  portfolio [--write]                               markdown table of active projects; --write replaces the
                                                    <!-- auto:portfolio --> block in the root CLAUDE.md
  facts                                             ^f- fact lines without source/date, low confidence older than
                                                    180 days, repeated facts, notes with several facts per category
  dupes                                             entity notes sharing a normalized title, alias or e-mail
  friction [--since YYYY-MM-DD | --days N]          `## Friction` lines of skill run logs, grouped and counted
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))
import paths  # noqa: E402
import vault  # noqa: E402

TODAY = dt.date.fromisoformat(os.environ["BRAIN_TODAY"]) if os.environ.get("BRAIN_TODAY") else dt.date.today()
ENTITY_TYPES = {"person", "org", "system", "project", "area", "concept"}
FACT_RE = re.compile(r"^\s*-\s*(?:~~)?\[(?P<cat>[^\]]+)\]\s*(?P<text>.*?)\s*\^(?P<id>f-[0-9a-f]{6})\s*$")
TASK_RE = re.compile(r"^[ \t]*- \[ \][ \t]+(\S.*)$", re.M)
PORT_START, PORT_END = "<!-- auto:portfolio start -->", "<!-- auto:portfolio end -->"
PORT_RE = re.compile(re.escape(PORT_START) + r".*?" + re.escape(PORT_END), re.S)


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip().casefold()


def rel(p, root):
    return paths.rel(p, root)


def since_date(args, default_days):
    if getattr(args, "since", None):
        return dt.date.fromisoformat(args.since)
    return TODAY - dt.timedelta(days=getattr(args, "days", None) or default_days)


def git(root, *a):
    try:
        r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def changed_notes(root, since):
    """Vault-relative notes added or modified since `since` (git history + uncommitted + mtime)."""
    out = set()
    top = git(root, "rev-parse", "--show-toplevel").strip()
    if top:
        prefix = os.path.relpath(root, top)
        names = git(root, "log", f"--since={since.isoformat()}", "--name-only", "--format=", "--diff-filter=AMR", "--", ".")
        names += "\n".join(ln[3:] for ln in git(root, "status", "--porcelain", "-uall", "--", ".").splitlines())
        for n in names.splitlines():
            n = n.strip().strip('"')
            if n.endswith(".md"):
                r = os.path.relpath(Path(top) / n, root) if prefix != "." else n
                out.add(vault.nfc(r))
    cutoff = dt.datetime.combine(since, dt.time()).timestamp()
    for p in paths.iter_notes(root, include_archives=False):
        try:
            if p.stat().st_mtime >= cutoff:
                out.add(rel(p, root))
        except OSError:
            pass
    return sorted(r for r in out if (root / r).is_file() and not r.startswith((paths.ARCHIVES + "/", paths.RESOURCES + "/",
                                                                                paths.MEETINGS + "/"))
                  and not paths.is_skipped(r))


def entity_terms(g):
    """[(term, target rel, link text, type)] for entity notes: title + aliases (>= 4 chars)."""
    out = []
    for r, n in g.nodes.items():
        if n["type"] not in ENTITY_TYPES or r.startswith(paths.ARCHIVES + "/"):
            continue
        stem = Path(r).stem if Path(r).name != "CLAUDE.md" else f"{Path(r).parent.name}/CLAUDE"
        title = n["title"]
        link = f"[[{stem}|{title}]]" if title != stem else f"[[{stem}]]"
        terms = {title} | {a for a in n["aliases"] if a}
        if Path(r).name == "CLAUDE.md":
            terms.add(Path(r).parent.name)
        for t in terms:
            if len(t) >= 4:
                out.append((t, r, link, n["type"]))
    return out


def body_for_matching(text):
    fmo = vault.Frontmatter(text)
    body = vault.LINKS_BLOCK_RE.sub("\n", fmo.body)
    body = re.sub(r"```.*?```", " ", body, flags=re.S)
    body = re.sub(r"`[^`\n]*`|<!--.*?-->|https?://\S+", " ", body, flags=re.S)
    return vault.nfc(vault.LINK_RE.sub(" ", body))


def cmd_links(root, args):
    g = vault.Graph.load(root)
    since = since_date(args, 1)
    notes = sorted(r for r in g.nodes if not r.startswith((paths.ARCHIVES + "/", paths.RESOURCES + "/", paths.MEETINGS + "/"))) \
        if args.all else [r for r in changed_notes(root, since) if r in g.nodes]
    terms = entity_terms(g)
    rows = []
    for r in notes:
        text = vault.read(root / r) or ""
        body = body_for_matching(text)
        linked = {e["dst"] for e in g.out(r)}
        found = {}
        for term, dst, link, typ in terms:
            if dst == r or dst in linked or dst in found:
                continue
            flags = 0 if (" " not in term and term[:1].isupper() and len(term) < 6) else re.I
            hits = len(re.findall(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", body, flags))
            if hits:
                found[dst] = {"target": dst, "link": link, "type": typ, "term": term, "hits": hits}
        n_in, n_out = len(g.inc(r)), len(g.out(r))
        rows.append({"note": r, "type": g.nodes[r]["type"], "in": n_in, "out": n_out,
                     "orphan": n_in == 0 and n_out == 0 and not paths.is_daily(r),
                     "unlinked": sorted(found.values(), key=lambda x: (-x["hits"], x["target"]))[:12]})
    todo = [x for x in rows if x["unlinked"] or x["orphan"]]
    return {"since": None if args.all else since.isoformat(), "notes_checked": len(rows), "rows": todo}


def cmd_inbox(root, args):
    base = root / paths.INBOX
    caps = []
    for p in sorted(base.glob("*")) if base.is_dir() else []:
        if not p.is_file() or p.name.startswith("."):
            continue
        text = vault.read(p) or ""
        fm, _ = vault.frontmatter(text)
        m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        born = dt.date.fromisoformat(m.group(1)) if m else dt.date.fromtimestamp(p.stat().st_mtime)
        caps.append({"path": rel(p, root), "title": fm.get("title", "").strip("\"'") or p.stem,
                     "context": fm.get("context", ""), "age_days": (TODAY - born).days, "empty": not text.strip()})
    mdir = root / paths.MEETINGS
    pending = []
    for p in sorted(mdir.glob("*")) if mdir.is_dir() else []:
        if p.is_file() and not p.name.startswith(".") and p.suffix in (".md", ".txt", ".vtt"):
            fm, _ = vault.frontmatter(vault.read(p) or "")
            if fm.get("processed", "").lower() != "true":
                pending.append(rel(p, root))
    return {"captures": caps, "older_than_7": sum(1 for c in caps if c["age_days"] > 7), "meetings_pending": pending}


def goal_of(fm, body):
    for k in ("goal", "description"):
        if fm.get(k):
            return str(fm[k]).strip().strip("\"'")
    m = re.search(r"^#+\s*Goal\b.*?\n+(.+)", body, re.M | re.I)
    if m and not m.group(1).startswith("#"):
        return m.group(1).strip()
    return ""


def last_activity(root, d, fm):
    dates = [str(fm.get("updated") or "")[:10]]
    dates += [m.group(0) for f in d.rglob("*.md") if (m := re.match(r"\d{4}-\d{2}-\d{2}", f.name))]
    dates.append(git(root, "log", "-1", "--format=%cs", "--", str(d)).strip())
    dates = [x for x in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x or "")]
    if not dates and d.exists():
        dates = [dt.date.fromtimestamp(max(f.stat().st_mtime for f in d.rglob("*"))).isoformat()]
    return max(dates) if dates else ""


def cmd_projects(root, args):
    rows = []
    for d in paths.project_dirs(root):
        p = d / "CLAUDE.md"
        text = vault.read(p)
        if text is None:
            rows.append({"slug": d.name, "path": rel(d, root), "problem": "no CLAUDE.md"})
            continue
        fmo = vault.Frontmatter(text)
        fm = fmo.as_dict()
        last = last_activity(root, d, fm)
        tasks = TASK_RE.findall(fmo.body)
        overdue = [t for t in tasks if any(x < TODAY.isoformat() for x in vault.DATE_RE.findall(t))]
        meetings = vault.DATE_RE.findall(re.search(r"<!-- auto:meetings start -->(.*?)<!-- auto:meetings end -->",
                                                   text, re.S).group(1)) if "auto:meetings start" in text else []
        goal = goal_of(fm, fmo.body)
        rows.append({"slug": d.name, "path": rel(p, root), "title": str(fm.get("title") or d.name),
                     "context": str(fm.get("context") or paths.SLUG_CTX.get(d.name.split("-")[0], "")),
                     "status": str(fm.get("status") or ""), "last_activity": last,
                     "days_quiet": vault.days_since(last, TODAY) if last else None,
                     "open_steps": len(tasks), "overdue_steps": overdue, "goal": goal,
                     "goal_missing": not goal or "{{" in goal, "last_meeting": max(meetings) if meetings else ""})
    return {"projects": rows}


def portfolio_table(root):
    order = {c: i for i, c in enumerate(paths.CONTEXTS)}
    rows = [r for r in cmd_projects(root, None)["projects"] if r.get("status") == "active"]
    rows.sort(key=lambda r: (order.get(r["context"], 99), -(int(r["last_activity"].replace("-", "") or 0))))
    lines = ["| project | context | goal |", "|---|---|---|"]
    for r in rows:
        goal = vault.shorten(r["goal"], 110) if not r["goal_missing"] else "(goal missing)"
        lines.append(f"| [[{r['slug']}/CLAUDE\\|{r['title']}]] | {r['context']} | {goal.replace('|', '/')} |")
    return "\n".join(lines) if rows else "*(no active projects)*"


def cmd_portfolio(root, args):
    table = portfolio_table(root)
    block = f"{PORT_START}\n{table}\n{PORT_END}"
    target = root / "CLAUDE.md"
    written = False
    if args.write:
        text = vault.read(target) or ""
        new = PORT_RE.sub(lambda _: block, text) if PORT_RE.search(text) else \
            text.rstrip("\n") + ("\n\n" if text.strip() else "") + "## Portfolio\n\n" + block + "\n"
        if new != text:
            vault.write(target, new)
            written = True
    return {"table": table, "target": rel(target, root), "written": written}


def fact_lines(root):
    for p in paths.iter_notes(root, include_archives=False):
        r = rel(p, root)
        if r.startswith((paths.RESOURCES + "/", paths.MEETINGS + "/")):
            continue
        for i, ln in enumerate((vault.read(p) or "").splitlines(), 1):
            m = FACT_RE.match(ln)
            if m:
                yield r, i, m, ln


def cmd_facts(root, args):
    no_prov, low_old, repeated, per_cat = [], [], [], defaultdict(list)
    seen = {}
    for r, i, m, ln in fact_lines(root):
        if ln.lstrip("- ").startswith("~~"):
            continue  # struck through = superseded
        text, cat = m.group("text"), fold(m.group("cat"))
        parts = re.split(r"\s+[—–]\s+", text)
        prov = parts[-1] if len(parts) > 1 else ""
        date = vault.DATE_RE.search(prov)
        where = {"note": r, "line": i, "id": m.group("id"), "text": vault.shorten(text, 140)}
        if not date or not re.sub(r"\d{4}-\d{2}-\d{2}.*", "", prov).strip(" ,"):
            no_prov.append(where)
        elif re.search(r"\blow\b", prov, re.I) and (TODAY - dt.date.fromisoformat(date.group(0))).days > 180:
            low_old.append(where)
        key = (r, fold(parts[0]))
        if key in seen:
            repeated.append({**where, "same_as": seen[key]})
        else:
            seen[key] = m.group("id")
        per_cat[(r, cat)].append(m.group("id"))
    multi = [{"note": r, "category": c, "ids": ids} for (r, c), ids in sorted(per_cat.items()) if len(ids) > 1]
    return {"no_provenance": no_prov, "low_confidence_old": low_old, "repeated": repeated, "same_category": multi}


def cmd_dupes(root, args):
    g = vault.Graph.load(root)
    groups = defaultdict(set)
    for r, n in g.nodes.items():
        if n["type"] not in ENTITY_TYPES or r.startswith(paths.ARCHIVES + "/"):
            continue
        keys = {n["title"], *n["aliases"]} | set(vault.as_list(str(n["fm"].get("email") or "")))
        for k in keys:
            if k and len(k) >= 3:
                groups[(n["type"], fold(k))].add(r)
    out = [{"type": t, "key": k, "notes": sorted(v)} for (t, k), v in sorted(groups.items()) if len(v) > 1]
    uniq, seen = [], set()
    for o in out:
        if tuple(o["notes"]) not in seen:
            seen.add(tuple(o["notes"]))
            uniq.append(o)
    return {"groups": uniq}


def cmd_friction(root, args):
    since = since_date(args, 7)
    base = root / paths.LOGS
    groups = defaultdict(list)
    for p in sorted(base.glob("*/*.md")) if base.is_dir() else []:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        if not m or m.group(1) < since.isoformat():
            continue
        sec = re.search(r"^## Friction[^\n]*\n(.*?)(?=^## |\Z)", vault.read(p) or "", re.M | re.S)
        for ln in (sec.group(1).splitlines() if sec else []):
            ln = ln.strip().lstrip("-* ").strip()
            if ln and fold(ln) not in ("none", "-", "nothing", "(none)"):
                groups[(p.parent.name, fold(ln))].append({"log": rel(p, root), "text": ln})
    rows = [{"skill": s, "text": v[0]["text"], "count": len(v), "logs": [x["log"] for x in v]}
            for (s, _), v in groups.items()]
    rows.sort(key=lambda x: (-x["count"], x["skill"]))
    return {"since": since.isoformat(), "items": rows}


def show(data):
    print(json.dumps(data, ensure_ascii=False, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("links", "friction"):
        s = sub.add_parser(name)
        s.add_argument("--since")
        s.add_argument("--days", type=int)
        if name == "links":
            s.add_argument("--all", action="store_true")
    for name in ("inbox", "projects", "facts", "dupes"):
        sub.add_parser(name)
    sub.add_parser("portfolio").add_argument("--write", action="store_true")
    for s in sub.choices.values():
        s.add_argument("--json", action="store_true", help="(output is always JSON; accepted for symmetry)")
    args = ap.parse_args(argv)
    root = paths.find_root()
    fn = {"links": cmd_links, "inbox": cmd_inbox, "projects": cmd_projects, "portfolio": cmd_portfolio,
          "facts": cmd_facts, "dupes": cmd_dupes, "friction": cmd_friction}[args.cmd]
    show(fn(Path(root), args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
