#!/usr/bin/env python3
"""context.py - generated agent context for the vault (python3 stdlib only). Usually `brain context …`.

  --write               regenerate .claude/index.md (one line per note) and .claude/hot.md (session snapshot);
                        a file is rewritten only when its content changes
  --hook                SessionStart hook: --write, then print hot.md to stdout (< ~1500 chars); never fails
  --post-tool           PostToolUse hook (Write|Edit|MultiEdit): reads the hook JSON on stdin, validates the edited
                        vault note (`brain validate --file`); errors -> stderr + exit 2 (Claude sees them),
                        warnings -> stdout + exit 0; anything else (not .md, outside the vault, .claude/, logs,
                        templates, internal failure) -> silent exit 0

index.md: `- [[target|Title]] — type · context · (person role/org) · aka aliases · summary` grouped by top-level folder and its subfolder;
a folder or `*` family of folders (servers per installation) with more than knowledge.list_max notes is one `▸` line;
summary = frontmatter description/summary or the first meaningful body sentence (vault.note_summary, cached).
Left out: 99_Archives/, _templates/, logs, 00_Inbox/meetings/ (transcripts), graph:false folders and
paths.VENDOR_DIRS (their MOC/README keeps one line); 10_Daily is one summary line.
Triggers (filesystem only, no network): unprocessed transcripts (files in 00_Inbox/meetings/ without
`processed: true`), Inbox captures older than 7 days, numbered proposals still ending in the pending marker
(brain.config.json › pending_marker, default `pending`) in the newest run log of each 50_Raw/logs/<skill>/.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the vault
BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN.parent / "lib"))
import paths  # noqa: E402
import vault  # noqa: E402

HOT_MAX = 900            # chars of hot.md (~150-250 tokens)
HOOK_MAX = 1500
PENDING = paths.CFG.get("pending_marker") or "pending"
INDEX_SKIP = (paths.ARCHIVES, paths.TEMPLATES, paths.MEETINGS, paths.LOGS)
COMPANION_FIRST = ("CLAUDE.md", "README.md")


def root_dir():
    """$BRAIN_ROOT, else the root above $CLAUDE_PROJECT_DIR (hooks) or cwd; None when neither is in a root."""
    env = os.environ.get("BRAIN_ROOT")
    if env:
        return Path(env).resolve()
    try:
        return paths.find_root(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    except SystemExit:
        return None


def today():
    env = os.environ.get("BRAIN_TODAY")  # tests
    return dt.date.fromisoformat(env) if env else dt.date.today()


def frontmatter_of(p):
    fm, _ = vault.frontmatter(vault.read(p) or "") if p.suffix == ".md" else ({}, None)
    return fm


def write_if_changed(path, text):
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


# ---------------------------------------------------------------- index.md
def index_group(r):
    parts = Path(r).parts
    top = parts[0] if len(parts) > 1 else "(root)"
    if len(parts) <= 2:
        return top, ""
    if paths.namespace_of(r) and len(parts) > 3:  # 40_Knowledge/<namespace>/<topic>/… -> "<namespace>/<topic>"
        return top, f"{parts[1]}/{parts[2]}"
    return top, parts[1]


def index_lines(g, r):
    n = g.nodes[r]
    bits = [n["type"] + (f"/{n['kind']}" if n.get("kind") else "")]
    ctx = str(n["fm"].get("context") or "").strip()
    if ctx:
        bits.append(ctx)
    status = str(n["fm"].get("status") or "").strip()
    if status and n["type"] == "project":
        bits.append(status)
    for k in ("role", "org"):  # person identity fields (plain text only)
        v = n["fm"].get(k)
        v = ", ".join(v) if isinstance(v, list) else v
        if isinstance(v, str) and v.strip() and "[[" not in v and n["type"] == "person":
            bits.append(vault.shorten(vault.plain(v), 50))
    seen = {vault.nfc(n["title"]).casefold(), n["stem"].casefold()}
    tl = vault.nfc(n["title"]).casefold()
    aka = [a for a in n.get("aliases") or []  # skip old file names (dated, or the title with a suffix)
           if a.casefold() not in seen and not seen.add(a.casefold()) and not re.match(r"\d{4}-\d{2}", a)
           and tl not in a.casefold()][:4]
    if aka:
        bits.append("aka " + ", ".join(aka))
    summ = n.get("summary") or ""
    if summ and summ != n["title"]:
        bits.append(summ.replace("\n", " "))
    return f"- {g.wikilink(r)} — " + " · ".join(bits)


def family_of(folder):
    """Collapse family of a folder: below the first three path parts the middle folders become `*`
    (`40_Knowledge/acme/sites/eu/berlin/servers` -> `40_Knowledge/acme/sites/*/*/servers`),
    so one generated layout (servers per installation) is one family; shallower folders are their own family."""
    parts = Path(folder).parts
    if len(parts) <= 4:
        return folder
    return "/".join(parts[:3] + ("*",) * (len(parts) - 4) + parts[-1:])


def collapsed_line(g, fam, rs, hubs):
    """One index line for a big folder/family: path, count, type/kind breakdown, 3 best-connected examples, hub."""
    folders = sorted({str(Path(r).parent) for r in rs})
    kinds = Counter(g.nodes[r]["type"] + (f"/{g.nodes[r]['kind']}" if g.nodes[r].get("kind") else "") for r in rs)
    ex = sorted(rs, key=lambda r: (-(len(g.out(r)) + len(g.inc(r))), r))[:3]
    bits = [f"{len(rs)} notes" + (f" in {len(folders)} folders" if len(folders) > 1 else ""),
            ", ".join(f"{k} {c}" for k, c in kinds.most_common(4)),
            "e.g. " + ", ".join(g.wikilink(r) for r in ex)]
    if hubs:
        bits.append("hub " + (g.wikilink(hubs[0]) if len(hubs) == 1 else f"one per folder ({len(hubs)})"))
    top = kinds.most_common(1)[0][0].split("/")
    bits.append("`brain find " + (f"--kind {top[1]} " if len(top) > 1 else f"--type {top[0]} ") + "--text …`")
    return f"- ▸ {fam}/ — " + " · ".join(bits)


def collapse_groups(g, groups, cap):
    """Replace folders/families with more than `cap` notes by one collapsed line (registries and flat
    folders of schema.json › knowledge stay listed: they are the identity lists). Mutates `groups`;
    returns {group key: [collapsed lines]}."""
    kc = vault.knowledge_cfg(g.schema)
    keep = set(paths.REGISTRY_DIRS) | {f"{kc['root']}/{d}" for d in kc.get("flat", [])}
    fams = {}
    for key, rs in groups.items():
        for r in rs:
            folder = str(Path(r).parent)
            name = Path(r).name
            if folder in keep or len(Path(r).parts) < 3 or (vault.is_companion(name, g.schema)
                                                            and not vault.is_folder_hub(r, g.nodes[r]["type"])):
                continue  # MOCs, READMEs, CLAUDE.md stay listed: they are the entry points
            fams.setdefault(family_of(folder), []).append((key, r))
    out = {}
    for fam, items in sorted(fams.items()):
        notes = [r for _, r in items if not vault.is_folder_hub(r, g.nodes[r]["type"])]
        if len(notes) <= cap:
            continue
        hubs = [r for _, r in items if vault.is_folder_hub(r, g.nodes[r]["type"])]
        base = fam.split("/*/")[0] if "/*/" in fam else None
        if base:  # the family's parent folder hub, e.g. sites-hub
            hubs = [r for r in g.nodes if str(Path(r).parent) == base and vault.is_folder_hub(r, g.nodes[r]["type"])] \
                or hubs
        drop = {r for _, r in items}
        keys = {k for k, _ in items}
        for k in keys:
            groups[k] = [r for r in groups[k] if r not in drop]
        out.setdefault(sorted(keys)[0], []).append(collapsed_line(g, fam, notes, hubs))
    return out


def build_index(g):
    root = g.root
    groups, dailies = {}, []
    for r in sorted(g.nodes):
        if paths.in_dirs(r, INDEX_SKIP):
            continue
        if paths.is_daily(r):
            dailies.append(Path(r).stem)
            continue
        name = Path(r).name
        if paths.in_dirs(r, paths.VENDOR_DIRS) and not (name in COMPANION_FIRST or paths.is_moc(name)
                                                        or paths.is_hub(name)):
            continue
        groups.setdefault(index_group(r), []).append(r)
    cap = vault.knowledge_cfg(g.schema)["list_max"]
    collapsed = collapse_groups(g, groups, cap)
    vendor = {d: sum(1 for r in g.nodes if paths.in_dirs(r, [d])) for d in paths.VENDOR_DIRS}
    off = sorted({str(Path(r).parent) for r in g.skipped if Path(r).name == "README.md"})
    out = ["# Agent index",
           "",
           "Generated by `brain context --write` (SessionStart hook); do not edit. One line per note:",
           "`[[link|Title]] — type[/kind] · context · [role · org ·] [aka aliases ·] summary`. Open the note only when the line is not enough;",
           "`brain show <note>` / `brain related <note>` for edges, `brain find --text …` for full text.",
           f"`▸ folder/` lines stand for a folder (or `*` family of folders) with more than {cap} notes: count, "
           "type/kind, 3 best-connected examples, hub; list it with `brain find` or its hub.",
           f"Not listed: {paths.ARCHIVES}/, {paths.TEMPLATES}/, logs, {paths.MEETINGS}/ (transcripts)"
           + "".join(f", {d}/ ({c} vendor notes, see its MOC)" for d, c in vendor.items() if c)
           + "".join(f", {d}/ (graph: false)" for d in off) + "."]
    order = {t: i for i, t in enumerate(("(root)",) + paths.ROOT_TOP + paths.WORKSPACE_TOP)}
    tops = sorted({t for t, _ in groups} | ({paths.DAILY} if dailies else set()), key=lambda t: (order.get(t, 99), t))
    for top in tops:
        out += ["", f"## {top}"]
        if top == paths.DAILY and dailies:
            out.append(f"- {len(dailies)} daily notes {dailies[0]} … {dailies[-1]} — `{paths.DAILY}/YYYY/YYYY-MM-DD.md`"
                       " (briefing, Top 3, log of the day)")
        for (t, sub) in sorted((k for k in groups if k[0] == top and (groups[k] or k in collapsed)),
                               key=lambda k: k[1]):
            if sub:
                out += ["", f"### {sub}"]
            rs = sorted(groups[(t, sub)], key=lambda r: (Path(r).name not in COMPANION_FIRST,
                                                         not (vault.is_folder_hub(r, g.nodes[r]["type"])
                                                              or paths.is_moc(Path(r).name)
                                                              or Path(r).name == paths.RELATION_MAP), r))
            out += collapsed.get((t, sub), []) + [index_lines(g, r) for r in rs]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- triggers
def unprocessed_meetings(root):
    d = root / paths.MEETINGS
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if not p.is_file() or p.name.startswith(".") or p.suffix not in (".md", ".txt", ".vtt"):
            continue
        fm, _ = vault.frontmatter(vault.read(p) or "") if p.suffix == ".md" else ({}, None)
        if str(fm.get("processed", "")).strip().lower() == "true":
            continue
        out.append(p.name)
    return out


def old_inbox(root, days=7):
    """Captures directly in 00_Inbox/ older than `days`: age from frontmatter created/date, else file mtime."""
    d = root / paths.INBOX
    if not d.is_dir():
        return 0
    n = 0
    for p in d.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        fm = frontmatter_of(p)
        age = vault.days_since(str(fm.get("created") or fm.get("date") or ""), today())
        if age is None:
            age = (today() - dt.date.fromtimestamp(p.stat().st_mtime)).days
        n += age > days
    return n


def pending_proposals(root):
    """[(log folder, file name, count)] of numbered proposal lines ending in the pending marker in the newest
    run log (`YYYY-MM-DD…md`) of each 50_Raw/logs/<skill>/."""
    out = []
    base = root / paths.LOGS
    marker = re.compile(re.escape(PENDING) + r"\W*$", re.I)
    for d in sorted(x for x in (base.iterdir() if base.is_dir() else []) if x.is_dir()):
        logs = sorted((f for f in d.glob("*.md") if re.match(r"\d{4}-\d{2}-\d{2}", f.name)), reverse=True)
        if not logs:
            continue
        n = sum(1 for ln in (vault.read(logs[0]) or "").splitlines()
                if re.match(r"^\s*\d+\.\s", ln) and marker.search(ln.strip()))
        if n:
            out.append((d.name, logs[0].name, n))
    return out


def plural(n, word, many=None):
    return word if n == 1 else (many or word + "s")


def triggers(root):
    lines = []
    for fn in (_t_meetings, _t_inbox, _t_proposals):
        try:
            lines += fn(root)
        except Exception:  # noqa: BLE001 - a broken trigger must never break the hook
            continue
    return lines


def _t_meetings(root):
    n = len(unprocessed_meetings(root))
    return [f"▸ {n} {plural(n, 'transcript')} waiting → /brain:process-meetings"] if n else []


def _t_inbox(root):
    n = old_inbox(root)
    return [f"▸ {n} {plural(n, 'capture')} in {paths.INBOX} older than 7 days → /brain:weekly"] if n else []


def _t_proposals(root):
    return [f"▸ {n} {plural(n, 'proposal')} from {skill} waiting for an answer ({name})"
            for skill, name, n in pending_proposals(root)]


# ---------------------------------------------------------------- hot.md
def top3(root):
    """(open items, done count, daily exists) from `## … Top 3` of today's daily note."""
    p = paths.daily_path(today(), root)
    text = vault.read(p)
    if text is None:
        return [], 0, False
    sec = vault.section(text, r"Top 3")
    open_, done = [], 0
    for ln in sec.splitlines():
        m = re.match(r"^\s*[-*]\s+\[( |x|X)\]\s*(.*)$", ln)
        if not m or not m.group(2).strip():
            continue
        if m.group(1) == " ":
            open_.append(vault.plain(m.group(2)))
        else:
            done += 1
    return open_, done, True


def active_projects(root):
    """[{slug, context, status, updated}] of project folders (20_Projects/<slug>/CLAUDE.md) with status active;
    updated = frontmatter `updated`, else the newest file mtime in the folder."""
    out = []
    for d in paths.project_dirs(root):
        fm = frontmatter_of(d / "CLAUDE.md") if (d / "CLAUDE.md").is_file() else {}
        if str(fm.get("status") or "").strip() != "active":
            continue
        upd = vault.DATE_RE.search(str(fm.get("updated") or ""))
        if upd:
            upd = upd.group(0)
        else:
            mt = max((p.stat().st_mtime for p in d.rglob("*") if p.is_file()), default=0)
            upd = dt.date.fromtimestamp(mt).isoformat() if mt else ""
        out.append({"slug": d.name, "context": str(fm.get("context") or "").strip() or paths.folder_context(
            paths.rel(d, root)), "status": "active", "updated": upd})
    return out


def build_hot(root, trig=None):
    t = today()
    wd = vault.WEEKDAYS[t.weekday()]
    out = [f"# Hot — {t.isoformat()} ({wd})"]
    act = active_projects(root)
    by = {}
    for r in act:
        by.setdefault(r.get("context") or "?", []).append(r)
    ctx_order = paths.CONTEXTS
    if act:
        out.append(f"Active projects {len(act)}: " + " · ".join(
            f"{c} {len(by[c])}" for c in sorted(by, key=lambda c: (ctx_order.index(c) if c in ctx_order else 99, c)))
            + " (goals: each project's CLAUDE.md)")
        recent = sorted(act, key=lambda r: (r.get("updated") or "", r["slug"]), reverse=True)[:3]
        out.append("Recently active: " + "; ".join(
            f"{r['slug']} ({r.get('updated') or '?'})" for r in recent))
    else:
        out.append("Active projects: none")
    items, done, exists = top3(root)
    if not exists:
        out.append("Top 3 today: no daily note → /brain:morning")
    elif items:
        out.append(f"Top 3 today ({done} done): " + " | ".join(vault.shorten(i, 60) for i in items))
    else:
        out.append("Top 3 today: " + (f"all done ({done})" if done else "not set"))
    trig = triggers(root) if trig is None else trig
    out.append("Waiting: " + ("nothing" if not trig else ""))
    if trig:
        out[-1] = "Waiting:"
        out += trig
    out.append(f"Navigation: {paths.AGENT_INDEX} (one line per note) · brain find --text …")
    text = "\n".join(out)
    if len(text) > HOT_MAX:  # drop trigger lines from the end, keep the navigation line
        nav = out[-1]
        body = out[:-1]
        while body and len("\n".join(body + ["…", nav])) > HOT_MAX:
            body.pop()
        text = "\n".join(body + ["…", nav])
    return text + "\n"


# ---------------------------------------------------------------- commands
def cmd_write(root, quiet=False):
    g = vault.Graph.load(root)
    idx = build_index(g)
    hot = build_hot(root)
    ch = [name for name, p, text in (("index.md", root / paths.AGENT_INDEX, idx), ("hot.md", root / paths.HOT, hot))
          if write_if_changed(p, text)]
    if not quiet:
        print(f"{paths.AGENT_INDEX}: {idx.count(chr(10) + '- ')} lines, {len(idx)} chars · {paths.HOT}: {len(hot)} chars"
              f" · rewritten: {', '.join(ch) or 'nothing (unchanged)'}")
    return hot


def cmd_hook(root):
    try:
        hot = cmd_write(root, quiet=True)
    except Exception:  # noqa: BLE001 - fall back to the last generated snapshot
        hot = vault.read(root / paths.HOT) or ""
    if hot:
        print(hot[:HOOK_MAX].rstrip())


def cmd_post_tool(root, stdin):
    """-> exit code (0 or 2); prints feedback."""
    try:
        data = json.loads(stdin or "{}")
    except ValueError:
        return 0
    ti = data.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("path") or ""
    if not fp.endswith(".md"):
        return 0
    p = Path(fp)
    if not p.is_absolute():
        p = Path(data.get("cwd") or os.getcwd()) / p
    try:
        r = p.resolve().relative_to(root.resolve()).as_posix() if root else None
    except ValueError:
        r = None
    if r is None:  # edited file in another root (multi-root workspace): validate it against its own root
        try:
            saved = os.environ.pop("BRAIN_ROOT", None)
            try:
                root = paths.find_root(p.resolve().parent)
            finally:
                if saved is not None:
                    os.environ["BRAIN_ROOT"] = saved
            r = p.resolve().relative_to(root).as_posix()
        except (SystemExit, ValueError, OSError):
            return 0
    r = vault.nfc(r)
    if paths.is_skipped(r) or r.startswith(".") or not p.is_file():
        return 0
    sys.path.insert(0, str(BIN))
    import brainkg  # noqa: E402
    g = vault.Graph.load(root)
    old = os.environ.get("BRAIN_ROOT")
    os.environ["BRAIN_ROOT"] = str(root)  # validate_file/find_root helpers see this root
    try:
        _, issues = brainkg.validate_file(g, p)
    finally:
        if old is None:
            os.environ.pop("BRAIN_ROOT", None)
        else:
            os.environ["BRAIN_ROOT"] = old
    errors = [i for i in issues if i["severity"] == "error"]
    warns = [i for i in issues if i["severity"] == "warning"]
    fmt = (lambda i: f"  {i['code']}" + (f" — {i['detail']}" if i["detail"] else ""))
    if errors:
        print(f"brain validate --file {r}: {len(errors)} error(s) (fix them; rules in CLAUDE.md › Conventions)",
              file=sys.stderr)
        print("\n".join(fmt(i) for i in errors[:10]), file=sys.stderr)
        if warns:
            print(f"  (+ {len(warns)} warning(s))", file=sys.stderr)
        return 2
    if warns:
        print(f"brain validate --file {r}: {len(warns)} warning(s)")
        print("\n".join(fmt(i) for i in warns[:5]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="brain context", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--hook", action="store_true")
    g.add_argument("--post-tool", action="store_true")
    g.add_argument("--triggers", action="store_true", help=argparse.SUPPRESS)  # hidden: ▸ lines only (tests)
    a = ap.parse_args(argv)
    root = root_dir()
    if root is None and not a.post_tool:
        if a.hook:
            return 0  # a session outside a vault root: nothing to inject
        raise SystemExit("Brain root not found (20_Projects/ + CLAUDE.md or 00_Inbox/); cd into the vault (or set BRAIN_ROOT)")
    if a.hook:
        try:
            cmd_hook(root)
        except Exception:  # noqa: BLE001 - a hook never blocks the session
            pass
        return 0
    if a.post_tool:
        try:
            return cmd_post_tool(root, sys.stdin.read())
        except Exception:  # noqa: BLE001
            return 0
    if a.write:
        cmd_write(root)
        return 0
    print("\n".join(triggers(root)) or "nothing waiting")  # --triggers
    return 0


if __name__ == "__main__":
    sys.exit(main())
