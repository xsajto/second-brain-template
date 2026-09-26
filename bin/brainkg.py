#!/usr/bin/env python3
"""brainkg.py - knowledge-graph CLI of the vault (python3 stdlib only). Usually called as `brain <cmd>`.

Browse:    index [--json] · find [--type --kind --context --area --text --status] · show <note>
           related <note> [--depth N --rel a,b] · project <role|entity|MOC> [--write] [--all]
Check:     validate [--json] [--strict] [--file PATH]           (exit 1 on errors; includes type-folder-mismatch, context-area-mismatch,
           project-no-area)
Area projection (hub): notes with an explicit area edge + responsible_for/related targets + decisions and
meetings in the area's decisions and meetings folders (config) + one hop from its projects (owner, stakeholders, uses,
affects, their decisions/meetings, attendees). A MOC at the root of a top-level folder projects its subfolders with counts
(knowledge-moc: registries + namespaces with their topics). A folder hub `<folder>-hub.md` (or a `*-hub.md` of type
map) inside 40_Knowledge/ projects its own folder (subfolders + notes by type label; > knowledge.list_max notes -> type
breakdown + 15 best-connected); `project --all --write` also creates missing hubs for folders with >= hub_min_notes
notes (recursively) or >= hub_min_subdirs subfolders (schema.json › knowledge).
Health:    doctor                                               python, config, folders, git, sync conflict copies
Schema:    schema list [--json] · schema add-type <name> [--entity --kinds a,b --label L --required k1,k2]
           · schema add-kind <type> <kind>                       (dry run unless --apply; schema.json, logged)
Operate:   create <type> "Title" [--namespace NS --topic a/b | --in NS/a/b] · link <src> --<rel> <target> · unlink …
           move <note> <dest-dir> · rename <note> "New" · migrate ids (backfill id/type)
Folder names, contexts, roots and project slug prefixes come from brain.config.json (lib/config.py).
Write commands are a dry run (unified diff) unless --apply; --apply refuses files with uncommitted git
changes unless the current content is exactly what brain last wrote (sha256 in ~/.cache/brain/written.json)
or --allow-dirty is given; both cases and every write are logged to 50_Raw/logs/brain/YYYY-MM-DD.jsonl. The graph is rebuilt from Markdown on every call
(per-file parse cache per root in ~/.cache/brain/graph-<root>-<hash>.json; --no-cache or BRAIN_NO_CACHE=1 disables it).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the vault
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import paths  # noqa: E402
import vault  # noqa: E402
from vault import nfc  # noqa: E402

TODAY = dt.date.today()
LINK_RELS = {"links_to", "linked_from", "mentions", "mentioned_in"}
# projection groups: these entity types first (in this order), then any other schema entity type alphabetically;
# labels come from schema.json › labels (unknown -> type name); areas are containers, never a group
GROUP_ORDER = ("project", "system", "org", "person", "decision", "meeting", "concept")
GROUP_SKIP = {"area"}
INLINE_GROUPS = {"person", "concept"}  # rendered as one ` · ` line; every other group as a bulleted list


def groups(schema):
    """OrderedDict type -> label of the entity types projections group by."""
    ent = [t for t in schema["types"]["entity"] if t not in GROUP_SKIP]
    order = [t for t in GROUP_ORDER if t in ent] + sorted(t for t in ent if t not in GROUP_ORDER)
    return OrderedDict((t, vault.type_label(schema, t)) for t in order)


PROJ_START, PROJ_END = "<!-- auto:projection start -->", "<!-- auto:projection end -->"
PROJ_NOTE = "*Generated from the graph (`brain project`); do not edit by hand.*"
PROJ_RE = re.compile(r"<!-- auto:projection start -->.*?<!-- auto:projection end -->", re.S)
# frontmatter keys that may hold wikilinks without being graph relations
LINK_OK_KEYS = {"source", "sources", "up", "down", "next", "prev", "same", "parent", "aliases", "tags", "meeting",
                "cssclasses", "moc", "seen_in", "see_also"}
TEMPLATES = {"person": "person.md", "project": "project-claude.md", "meeting": "meeting-note.md",
             "decision": "decision.md", "system": "system.md", "org": "org.md", "concept": "concept.md",
             "area": "area-hub.md", "daily": "daily.md"}


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load(args):
    return vault.Graph.load(paths.find_root(), use_cache=not getattr(args, "no_cache", False))


def need(g, ref, what="note"):
    r = g.resolve(ref)
    if not r:
        cands = g.resolver.candidates(ref)
        die(f"{what} not found in graph: {ref}" + (f" (candidates outside graph: {cands[:3]})" if cands else ""))
    return r


def label(g, r):
    n = g.nodes.get(r, {})
    return f"{n.get('title') or Path(r).stem} ({n.get('type', '?')})"


# ================================================================ change set (dry-run / apply)
class Changes:
    def __init__(self, g, cmd):
        self.g, self.root, self.cmd = g, g.root, cmd
        self.moves, self.writes, self.notes = [], OrderedDict(), []  # writes: final rel -> (old, new)

    def move(self, src, dst):
        self.moves.append((src, dst))

    def write(self, rel, new, old=None, orig=None):
        if old is None:
            old = vault.read(self.root / (orig or rel))
        if old != new:
            self.writes[rel] = (old, new)

    def empty(self):
        return not self.moves and not self.writes

    def show(self, limit=0):
        for s, d in self.moves:
            print(f"git mv '{s}' '{d}'")
        shown = 0
        for rel, (old, new) in self.writes.items():
            if limit and shown >= limit:
                print(f"… +{len(self.writes) - shown} more diffs (use --limit 0 to show all)")
                break
            print(vault.udiff(rel, old, new), end="")
            shown += 1
        for n in self.notes:
            print(f"# {n}")
        print(f"# dry run: {len(self.moves)} move(s), {len(self.writes)} write(s); add --apply to execute")

    def apply(self, allow_dirty=False):
        git = vault.Git(self.root)
        back = {d: s for s, d in self.moves}
        touched = [s for s, _ in self.moves] + [back.get(r, r) for r, (old, _) in self.writes.items()
                                                if old is not None]
        if not git.available:
            print("warning: no git repository for this vault; dirty check and git mv unavailable", file=sys.stderr)
        else:
            dirty = git.dirty(sorted(set(touched)))
            written = vault.load_written()
            own = [r for r in dirty if vault.written_by_brain(self.root / r, written)]
            foreign = [r for r in dirty if r not in own]
            for r in own:  # uncommitted, but the content is exactly what brain wrote last time
                vault.log(self.root, "dirty-own", r, "uncommitted changes are brain's own last write", cmd=self.cmd)
            if foreign and not allow_dirty:
                die("refusing --apply, uncommitted changes not made by brain in: " + ", ".join(foreign[:10]) +
                    (f" … +{len(foreign) - 10}" if len(foreign) > 10 else "") +
                    " (commit first, or --allow-dirty)", 1)
            for r in foreign:
                vault.log(self.root, "dirty-allowed", r, "foreign uncommitted changes, --allow-dirty", cmd=self.cmd)
            if foreign:
                print(f"warning: --allow-dirty: overwriting {len(foreign)} file(s) with foreign uncommitted changes",
                      file=sys.stderr)
        for rel in self.writes:
            if self.writes[rel][0] is None and (self.root / rel).exists():
                die(f"target exists: {rel}", 1)
        for s, d in self.moves:
            if (self.root / d).exists():
                die(f"move target exists: {d}", 1)
        for s, d in self.moves:
            if git.available:
                git.mv(s, d)
            else:
                (self.root / d).parent.mkdir(parents=True, exist_ok=True)
                os.rename(self.root / s, self.root / d)
            vault.remember_written(self.root / d)
            vault.log(self.root, "move", d, f"from {s}", cmd=self.cmd)
            parent = (self.root / s).parent
            while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        for rel, (old, new) in self.writes.items():
            vault.write(self.root / rel, new)
            vault.log(self.root, "create" if old is None else "write", rel, cmd=self.cmd)
        print(f"applied: {len(self.moves)} move(s), {len(self.writes)} write(s); logged to "
              f"{paths.BRAIN_LOGS}/{TODAY.isoformat()}.jsonl")

    def finish(self, args, limit=0):
        if self.empty():
            print("nothing to change")
            return
        if getattr(args, "apply", False):
            self.apply(getattr(args, "allow_dirty", False))
        else:
            self.show(limit)


# ================================================================ link rewriting (move / rename)
def link_target_text(new, counts):
    """Wikilink target for a (new) vault path: `slug/CLAUDE` for CLAUDE.md, the bare name when it is unique
    vault-wide (case-insensitive, like Obsidian), else the full path without .md."""
    if Path(new).name == "CLAUDE.md":
        return f"{Path(new).parts[-2]}/CLAUDE"
    nk = vault.name_key(new)
    if counts.get(nk.casefold(), 0) == 1:
        return nk
    return vault.strip_ext(new) if new.endswith(".md") else new


def shown_text(t):
    """What the reader saw for an alias-less link: the written target without .md, last path segment only
    (`CTO/CLAUDE` -> `CTO`)."""
    t = vault.strip_ext(t)
    if t.endswith("/CLAUDE"):
        return t[:-len("/CLAUDE")].rsplit("/", 1)[-1]
    return t.rsplit("/", 1)[-1]


def rewrite_text_links(text, src, mapping, resolver, counts, label=True):
    """(new text, n rewritten) with every [[link]] / ![[embed]] whose target resolves to a key of `mapping`
    retargeted to the new path: `[[Old]]` -> `[[new|Old]]`, `[[Old|a]]` -> `[[new|a]]`,
    `[[Old#h]]` -> `[[new#h|Old]]`; embeds keep no label; inside table rows the pipe is escaped (`\\|`)."""
    if not text or "[[" not in text:
        return text, 0
    pieces, pos, n = [], 0, 0
    for t, anchor, alias, s, e, esc, ts, te in vault.parse_links(text):
        old = resolver.resolve(t, src)
        if old not in mapping:
            continue
        newt = link_target_text(mapping[old], counts)
        raw = text[s:e]
        if newt == text[ts:te].strip() and not (t.lower().endswith(".md") and not newt.endswith(".md")):
            continue
        embed = s > 0 and text[s - 1] == "!"
        line_start = text.rfind("\n", 0, s) + 1
        in_table = text[line_start:s].lstrip().startswith("|")
        pipe = "\\|" if ("\\|" in raw or in_table) else "|"
        mm = vault.LINK_RE.match(raw)
        anc = (mm.group(2) or "").rstrip("\\") if mm else anchor
        if alias:
            lab = alias
        elif embed or not label:
            lab = ""
        else:
            lab = shown_text(t)
            if lab == newt and not anc:
                lab = ""
        pieces.append(text[pos:s])
        pieces.append("[[" + newt + anc + (pipe + lab if lab else "") + "]]")
        pos = e
        n += 1
    if not n:
        return text, 0
    pieces.append(text[pos:])
    return "".join(pieces), n


def rewrite_links(g, mapping, label=True):
    """{containing note old rel: new text} for every note whose wikilinks resolve to a moved/renamed file.
    mapping: old rel -> new rel. Links resolved by any route (name, path, alias, title) are retargeted."""
    new_files = (set(g.all_files) - set(mapping)) | set(mapping.values())
    counts = Counter(vault.name_key(f).casefold() for f in new_files)
    out = {}
    for f in g.all_files:
        if not f.endswith(".md") or paths.is_skipped(f):
            continue
        text = vault.read(g.root / f)
        new, n = rewrite_text_links(text, f, mapping, g.resolver, counts, label)
        if n:
            out[f] = new
    return out


def add_alias(text, alias):
    fmo = vault.Frontmatter(text)
    cur = fmo.get("aliases")
    items = cur if isinstance(cur, list) else vault.as_list(cur) if cur else []
    if nfc(alias) not in [nfc(a) for a in items]:
        items.append(alias)
        fmo.set("aliases", items, after=["title", "context"])
    return fmo.render()


# ================================================================ index / find / show / related
def cmd_index(args):
    g = load(args)
    types = Counter(n["type"] for n in g.nodes.values())
    rels = Counter(e["rel"] for e in g.edges)
    origins = Counter(e["origin"] for e in g.edges)
    d = {"root": str(g.root), "notes": len(g.nodes), "skipped": len(g.skipped), "files": len(g.all_files),
         "types": dict(types.most_common()), "edges": len(g.edges), "relations": dict(rels.most_common()),
         "origins": dict(origins.most_common()),
         "missing_id": sum(1 for n in g.nodes.values() if not n["id"]),
         "missing_type": sum(1 for n in g.nodes.values() if not n["type_explicit"]),
         "unresolved_relations": len(g.unresolved)}
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return
    print(f"# Brain graph: {d['notes']} notes ({d['skipped']} skipped graph:false), {d['edges']} edges")
    print("types:     " + ", ".join(f"{k} {v}" for k, v in types.most_common()))
    print("relations: " + ", ".join(f"{k} {v}" for k, v in rels.most_common()))
    print("origins:   " + ", ".join(f"{k} {v}" for k, v in origins.most_common()))
    print(f"missing id: {d['missing_id']} · type only inferred: {d['missing_type']} · "
          f"unresolved relation values: {d['unresolved_relations']}")


def area_members(g, area):
    """Everything an area holds: notes with an area edge (also by location), responsible_for targets and the
    whole hub projection (projects, their people, systems, orgs, decisions, meetings)."""
    members = {e["src"] for e in g.inc(area, {"area"})} | {e["dst"] for e in g.out(area, {"responsible_for"})}
    for items in area_projection(g, area).values():
        members |= items
    return members


def fold(s):
    """casefold + strip diacritics (NFC in, ascii-ish out) so `cafe` finds `café`."""
    import unicodedata
    s = unicodedata.normalize("NFKD", nfc(s).casefold())
    return "".join(c for c in s if not unicodedata.combining(c))


# stopwords dropped from `find --text` queries: English + brain.config.json › stopwords (the note language)
STOPWORDS = set("""
the and or of to in on for is are was were be been what who how why when where which with from by at as it its
this that these those an a not but if then than so do does did can could will would should about into over
""".split()) | {fold(w) for w in paths.CFG.get("stopwords") or []}
STEM = 5  # tokens of >= 5 chars match by their first 5 chars (inflected forms: "planning" ~ "planned")


def query_tokens(text):
    """Folded query words without stopwords and 1-2 letter noise (numbers kept), deduplicated, in order."""
    out = []
    for w in re.split(r"[^\w]+", fold(text)):
        if w and (len(w) >= 3 or w.isdigit()) and w not in STOPWORDS and w not in out:
            out.append(w)
    return out


def token_res(t):
    """(whole-word regex, word-start stem regex) for a folded token."""
    stem = t[:STEM] if len(t) >= STEM and not t.isdigit() else t
    return (re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)"), re.compile(r"(?<!\w)" + re.escape(stem)))


def text_score(tokens, head, body, idf=None):
    """Rank a note for `find --text` (any-match): per token hit at a word start — title/stem/alias 3 (whole
    word) / 2 (stem prefix), body 1 + log-damped occurrence count — weighted by the token's idf; notes hitting
    more distinct tokens rank first. -> (hits, score); hits 0 = no match."""
    import math
    hits, score = 0, 0.0
    for t in tokens:
        whole, pre = token_res(t)
        hs = 3 if whole.search(head) else 2 if pre.search(head) else 0
        nb = len(pre.findall(body))
        bs = (1 + math.log(nb)) if nb else 0
        if hs or bs:
            hits += 1
            score += (hs + bs) * ((idf or {}).get(t, 1.0))
    return hits, round(hits * 10 + score, 2) if hits else 0.0


def cmd_find(args):
    g = load(args)
    area = None
    if args.area:
        area = resolve_area(g, args.area) or die(f"area not found: {args.area} (roles: " + ", ".join(
            sorted(n["title"] for n in g.nodes.values() if n["type"] == "area")) + ")")
    members = area_members(g, area) if area else None
    tokens = query_tokens(args.text) if args.text else []
    if args.text and not tokens:
        die(f"--text: no searchable words in {args.text!r} (only stopwords / too short)")
    pool = dict(g.nodes)
    if args.all and tokens:  # graph:false folders too (not typed: their notes are outside the graph)
        for r in g.skipped:
            m = g.metas[r]
            pool[r] = dict(m, type=nfc(str(m["fm"].get("type") or "")) or "note", kind=nfc(str(m["fm"].get("kind") or "")))
    rows, scores, texts = [], {}, {}
    for r, n in sorted(pool.items()):
        if args.type and n["type"] != args.type:
            continue
        if args.kind and n["kind"] != args.kind:
            continue
        if args.context and str(n["fm"].get("context", "")) != args.context:
            continue
        if args.status and str(n["fm"].get("status", "")) != args.status:
            continue
        if members is not None and r not in members and r != area:
            continue
        if tokens:
            if not args.all and (in_archives(r) or paths.in_dirs(r, paths.VENDOR_DIRS)):
                continue
            texts[r] = (fold(" ".join([n["title"], n["stem"].replace("-", " "), " ".join(n["aliases"])])),
                        fold(vault.read(g.root / r) or ""))
        rows.append(r)
    if tokens:
        import math
        df = {t: sum(1 for h, b in texts.values() if token_res(t)[1].search(h) or token_res(t)[1].search(b))
              for t in tokens}
        idf = {t: math.log(1 + len(texts) / (1 + df[t])) for t in tokens}
        for r in rows:
            hits, sc = text_score(tokens, *texts[r], idf)
            if hits:
                scores[r] = sc
        rows = sorted((r for r in rows if r in scores), key=lambda x: (-scores[x], x))
        if args.limit:
            rows = rows[:args.limit]
    if args.json:
        print(json.dumps([{"path": r, "id": pool[r]["id"], "type": pool[r]["type"], "kind": pool[r]["kind"],
                           "title": pool[r]["title"], **({"score": scores[r]} if tokens else {})} for r in rows],
                         ensure_ascii=False, indent=1))
        return
    for r in rows if tokens else sorted(rows, key=lambda x: (pool[x]["type"], x)):
        n = pool[r]
        st = f" [{n['fm'].get('status')}]" if n["fm"].get("status") else ""
        sc = f"{scores[r]:>5.1f}  " if tokens else ""
        print(f"{sc}{n['type']:<9} {n['kind'] or '-':<8} {r}  — {n['title']}{st}")
    print(f"# {len(rows)} note(s)" + ("" if args.all or not tokens else
                                      f" (without {paths.ARCHIVES}/ and vendor docs; --all to include)"))


def note_areas(g, r):
    """[(area rel, how)] for a note: its own area edge (frontmatter / location), else via its project,
    else the areas that list it in responsible_for, else the area projections it appears in."""
    out = [(e["dst"], "location" if e["origin"] == "location" else "area") for e in g.out(r, {"area"})]
    if not out:
        for pe in g.out(r, {"project"}):
            out += [(e["dst"], f"via {g.nodes[pe['dst']]['title']}") for e in g.out(pe["dst"], {"area"})]
    if not out:
        out = [(e["src"], "responsible_for") for e in g.inc(r, {"responsible_for"})
               if g.nodes[e["src"]]["type"] == "area"]
    if not out and g.nodes[r]["type"] in groups(g.schema):  # derived: hub projections that contain the note
        out = [(a, "projection") for a, m in sorted(g.nodes.items()) if m["type"] == "area" and not in_archives(a)
               and r in area_projection(g, a).get(g.nodes[r]["type"], set())]
    return out


def areas_text(g, r):
    a = note_areas(g, r)
    return ", ".join(f"{g.nodes[x]['title']} ({how})" for x, how in a) if a else "—"


def cmd_show(args):
    g = load(args)
    r = need(g, args.note)
    n = g.nodes[r]
    fmo = vault.Frontmatter(vault.read(g.root / r) or "")
    out = {"path": r, "id": n["id"], "type": n["type"], "type_explicit": n["type_explicit"], "kind": n["kind"],
           "title": n["title"], "areas": [{"path": x, "title": g.nodes[x]["title"], "how": how}
                                          for x, how in note_areas(g, r)], "outgoing": {}, "incoming": {}}
    for lab, other, e, d in g.neighbors(r):
        out["outgoing" if d == "out" else "incoming"].setdefault(lab, []).append(
            {"path": other, "title": g.nodes[other]["title"], "type": g.nodes[other]["type"], "origin": e["origin"]})
    if args.json:
        out["frontmatter"] = n["fm"]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print(f"# {n['title']}  ({r})")
    print(f"id: {n['id'] or '—'} · type: {n['type']}{'' if n['type_explicit'] else ' (inferred)'}"
          f" · kind: {n['kind'] or '—'}" + ("" if n["type"] == "area" else f" · area: {areas_text(g, r)}"))
    if fmo.present:
        print("\n## frontmatter")
        for k, ls in fmo.entries:
            for ln in ls:
                print("  " + ln)
    for side, title in (("outgoing", "outgoing"), ("incoming", "incoming (computed inverses)")):
        if not out[side]:
            continue
        print(f"\n## {title}")
        for lab in sorted(out[side], key=lambda x: (x in LINK_RELS, x)):
            items = out[side][lab]
            lim = items if lab not in LINK_RELS or args.all else items[:15]
            print(f"  {lab} ({len(items)}): " + " · ".join(
                f"{i['title']}" + (f" [{i['origin']}]" if i["origin"] not in ("fm", "body", "auto:links") else "")
                for i in lim) + (" …" if len(lim) < len(items) else ""))
    unres = [u for u in g.unresolved if u["src"] == r]
    if unres:
        print("\n## unresolved relation values")
        for u in unres:
            print(f"  {u['rel']}: {u['raw']}")


def parse_rels(s):
    return {x.strip() for x in s.split(",") if x.strip()} if s else None


def cmd_related(args):
    g = load(args)
    r = need(g, args.note)
    rels = parse_rels(args.rel)
    seen = {r}

    def grouped(node, depth):
        allowed = rels if rels else None
        nb = g.neighbors(node, allowed)
        if depth > 1 and not rels:
            nb = [x for x in nb if x[0] not in LINK_RELS]
        groups = OrderedDict()
        for lab, other, e, d in sorted(nb, key=lambda x: (x[0] in LINK_RELS, x[0], g.nodes[x[1]]["type"], x[1])):
            groups.setdefault(lab, [])
            if other not in [o for o, _ in groups[lab]]:
                groups[lab].append((other, e))
        return groups

    tree = {"path": r, "title": g.nodes[r]["title"], "type": g.nodes[r]["type"], "relations": {}}

    def walk(node, depth, prefix, holder, path=()):
        path = path + (node,)
        groups = grouped(node, depth)
        for lab in list(groups):
            groups[lab] = [(o, e) for o, e in groups[lab] if o not in path]
            if not groups[lab]:
                del groups[lab]
        keys = list(groups)
        for gi, lab in enumerate(keys):
            last_g = gi == len(keys) - 1
            items = groups[lab]
            if not args.json:
                print(f"{prefix}{'└─' if last_g else '├─'} {lab} ({len(items)})")
            holder["relations"][lab] = []
            for ii, (other, e) in enumerate(items):
                last_i = ii == len(items) - 1
                mark = "" if e["origin"] in ("fm", "body", "auto:links") else f" [{e['origin']}]"
                ended = " (ended)" if g.nodes[other]["fm"].get("valid_to") else ""
                child = {"path": other, "title": g.nodes[other]["title"], "type": g.nodes[other]["type"],
                         "origin": e["origin"], "relations": {}}
                holder["relations"][lab].append(child)
                if not args.json:
                    print(f"{prefix}{'   ' if last_g else '│  '}{'└─' if last_i else '├─'} "
                          f"{label(g, other)}{mark}{ended}  {other}")
                if depth < args.depth and other not in seen:
                    seen.add(other)
                    walk(other, depth + 1, prefix + ("   " if last_g else "│  ") + ("   " if last_i else "│  "), child, path)

    tree["areas"] = [{"path": x, "title": g.nodes[x]["title"], "how": how} for x, how in note_areas(g, r)]
    if not args.json:
        print(f"{label(g, r)}  {r}" + ("" if g.nodes[r]["type"] == "area" else f"  · area: {areas_text(g, r)}"))
    walk(r, 1, "", tree)
    if args.json:
        print(json.dumps(tree, ensure_ascii=False, indent=1))


# ================================================================ projection
STATUS_ORDER = {"active": 0, "paused": 1}


def in_archives(r):
    return r.startswith(paths.ARCHIVES + "/")


def area_of_path(g, r):
    """The area note (30_Areas/<role>/<role>-hub.md) for a note physically inside an area folder, else None."""
    parts = Path(r).parts
    return paths.rel(paths.area_hub(g.root / paths.AREAS / parts[1]), g.root) \
        if len(parts) >= 3 and parts[0] == paths.AREAS else None


def resolve_area(g, ref, loose=True):
    """An area note from a role name: folder name, title, id, path, then (loose) alias or any ref resolving
    to the area or its hub. None if no area."""
    key = nfc(str(ref)).strip().rstrip("/")
    key = key[len(paths.AREAS) + 1:] if key.startswith(paths.AREAS + "/") else key
    areas = {r: n for r, n in g.nodes.items() if n["type"] == "area" and not in_archives(r)}
    ck = key.casefold()
    tests = [lambda r, n: len(Path(r).parts) > 2 and nfc(Path(r).parts[1]).casefold() in (ck, paths.kebab(key)),
             lambda r, n: n["title"].casefold() == ck or n["id"] == key or r == key]
    if loose:
        tests.append(lambda r, n: ck in [x.casefold() for x in n["aliases"]])
    for test in tests:
        hits = [r for r, n in areas.items() if test(r, n)]
        if len(hits) == 1:
            return hits[0]
    if not loose:
        return None
    r = g.resolve(ref)
    if r and g.nodes[r]["type"] == "area":
        return r
    if r and area_of_path(g, r) in areas:  # any note inside an area folder
        return area_of_path(g, r)
    return None


def area_projection(g, area):
    """{type: set(rel)} for an area (role): direct members + 1-hop derivations from its projects."""
    found = OrderedDict((t, set()) for t in groups(g.schema))

    def add(x):
        if x != area and not in_archives(x) and g.nodes[x]["type"] in found:
            found[g.nodes[x]["type"]].add(x)

    # direct: explicit area edge (frontmatter), responsible_for, related; decisions/meetings in the area folder
    for e in g.inc(area, {"area"}):
        if e["origin"] != "location":
            add(e["src"])
        elif len(Path(e["src"]).parts) >= 4 and Path(e["src"]).parts[2] in (paths.DECISIONS_SUB, paths.MEETINGS_SUB):
            add(e["src"])
    for e in g.out(area, {"responsible_for", "related"}):
        add(e["dst"])
    # derived, one hop from the area's projects
    for p in list(found["project"]):
        for e in g.out(p, {"owner", "stakeholders", "uses", "affects"}):
            if g.nodes[e["dst"]]["type"] in ("person", "system", "org"):
                add(e["dst"])
        for e in g.inc(p, {"project"}):
            if g.nodes[e["src"]]["type"] in ("decision", "meeting"):
                add(e["src"])
    for m in list(found["meeting"]):
        for e in g.out(m, {"attendees"}):
            add(e["dst"])
    return found


def projection(g, r):
    """(target, {type: set(rel)}) of entities around r, grouped for hubs; areas use area_projection."""
    n = g.nodes[r]
    target = r
    if g.nodes[target]["type"] == "area":
        return target, area_projection(g, target)
    found = OrderedDict((t, set()) for t in groups(g.schema))

    def add(x):
        typ = g.nodes[x]["type"]
        if typ in found and x != target and not in_archives(x):
            found[typ].add(x)

    for lab, other, e, d in g.neighbors(target):
        if lab not in LINK_RELS:
            add(other)
    if g.nodes[target]["type"] == "map":
        for lab, other, e, d in g.neighbors(target, {"links_to", "mentions"}):
            if d == "out":
                add(other)
    for p in list(found["project"]):
        for lab, other, e, d in g.neighbors(p):
            if lab in ("owner", "stakeholders", "uses", "affects", "depends_on", "part_of") or \
                    (lab == "notes" and g.nodes[other]["type"] in ("decision", "meeting")):
                add(other)
    return target, found


def folder_moc(g, r):
    """True for a MOC sitting at the root of a top-level folder that has subfolders (e.g. knowledge-moc)."""
    p = Path(r)
    return (g.nodes[r]["type"] == "map" and len(p.parts) == 2 and paths.is_moc(p.name)
            and any(d.is_dir() and not d.name.startswith(".") for d in (g.root / p.parts[0]).iterdir()))


def render_folder_projection(g, r, folders=None):
    """Folders under the MOC's folder with note counts (by type); small entity folders list notes. For 40_Knowledge/
    (knowledge-moc): the registries (people, orgs) first, then every namespace with its top-level topics."""
    top = Path(r).parts[0]
    lines = [PROJ_START, PROJ_NOTE, ""]
    listable = set(groups(g.schema)) - {"person", "project", "decision", "meeting"}
    dirs = [d for d in sorted((g.root / top).iterdir(), key=lambda x: nfc(x.name).casefold())
            if d.is_dir() and not d.name.startswith(".")]

    def under(pre):
        return sorted((x for x in g.nodes if x.startswith(pre)), key=lambda x: nfc(g.nodes[x]["title"]).casefold())

    def content(pre):  # notes below a folder without hubs / MOCs / READMEs (stable across hub creation)
        return [x for x in under(pre) if content_note(g, x)]

    def folder_line(d):
        pre = f"{top}/{nfc(d.name)}/"
        notes = under(pre)
        types = Counter(g.nodes[x]["type"] for x in notes)
        desc = ", ".join(f"{t} {c}" for t, c in types.most_common())
        out = [f"- **{nfc(d.name)}/** ({len(notes)})" + (f" — {desc}" if desc else "")]
        entity = [x for x in notes if g.nodes[x]["type"] in listable]
        if entity and len(entity) == len([x for x in notes if g.nodes[x]["type"] != "map"]) and len(entity) <= 12:
            out.append("  " + " · ".join(g.wikilink(x) for x in entity))
        return out

    if top != paths.KNOWLEDGE:
        for d in dirs:
            lines += folder_line(d)
    else:
        folders = folders if folders is not None else vault.knowledge_folders(g)
        reg = [d for d in dirs if f"{top}/{nfc(d.name)}" in paths.REGISTRY_DIRS]
        if reg:
            lines += ["**Registry**"] + [ln for d in reg for ln in folder_line(d)] + [""]
        spaces = [d for d in dirs if d not in reg]
        if spaces:
            lines.append("**Namespaces**")
        for d in spaces:
            ns = f"{top}/{nfc(d.name)}"
            e = folders.get(ns, {"hubs": [], "subdirs": [], "notes": []})
            hub = f" · [[{vault.strip_ext(Path(e['hubs'][0]).name)}|Hub]]" if e["hubs"] else ""
            types = Counter(g.nodes[x]["type"] for x in content(ns + "/"))
            desc = ", ".join(f"{t} {c}" for t, c in types.most_common(4))
            lines.append(f"- **{nfc(d.name)}/** ({sum(types.values())})" + (f" — {desc}" if desc else "") + hub)
            topics = []
            for t in e["subdirs"]:
                sub = f"{ns}/{t}"
                n = len(content(sub + "/"))
                th = folders.get(sub, {}).get("hubs") or []
                topics.append((f"[[{vault.strip_ext(Path(th[0]).name)}|{t}/]]" if th else f"{t}/") + f" ({n})")
            if topics:
                lines.append("  " + " · ".join(topics))
    lines += ["", PROJ_END]
    return "\n".join(lines)


def content_note(g, x):
    """Not a companion (hub, MOC, README …); a note that only ends in -hub (repo-infra-mcp-hub) is content."""
    name = Path(x).name
    return not vault.is_companion(name, g.schema) or (paths.is_hub(name)
                                                       and not vault.is_folder_hub(x, g.nodes[x]["type"]))


def knowledge_hub(g, r):
    """True for a folder hub inside 40_Knowledge/ (`<folder>-hub.md` or type map; not any note ending in -hub)."""
    p = Path(r)
    return len(p.parts) >= 3 and p.parts[0] == paths.KNOWLEDGE and \
        vault.is_folder_hub(r, (g.nodes.get(r) or {}).get("type"))


def render_knowledge_hub(g, r, folders=None):
    """The hub's folder: subfolders (with their hub and note count) and the notes directly inside, grouped by type
    label, one line each with kind and summary. `folders`: vault.knowledge_folders(g) (+ hubs planned this run)."""
    folder = str(Path(r).parent)
    folders = folders if folders is not None else vault.knowledge_folders(g)
    e = folders.get(folder, {"notes": [], "subdirs": []})
    lines = [PROJ_START, PROJ_NOTE, ""]
    if e["subdirs"]:
        lines.append(f"**Folders ({len(e['subdirs'])})**")
        for t in e["subdirs"]:
            sub = f"{folder}/{t}"
            n = vault.folder_note_count(folders, sub)
            th = folders.get(sub, {}).get("hubs") or []
            lines.append("- " + (f"[[{vault.strip_ext(Path(th[0]).name)}|{t}/]]" if th else f"**{t}/**") + f" ({n})")
        lines.append("")
    cap = vault.knowledge_cfg(g.schema)["list_max"]
    if len(e["notes"]) > cap:  # big generated families (servers, repositories): breakdown + best-connected notes
        kinds = Counter(g.nodes[x]["type"] + (f"/{g.nodes[x]['kind']}" if g.nodes[x]["kind"] else "")
                        for x in e["notes"])
        top = sorted(e["notes"], key=lambda x: (-(len(g.out(x)) + len(g.inc(x))), nfc(g.nodes[x]["title"]).casefold()))
        show = min(15, cap)
        lines.append(f"**Notes ({len(e['notes'])})** — " + ", ".join(f"{k} {c}" for k, c in kinds.most_common(6)))
        lines.append(f"*{show} most connected:*")
        lines += [f"- {g.wikilink(x)}" + (f" — {vault.shorten(g.nodes[x]['summary'], 100)}" if g.nodes[x].get("summary")
                                          and g.nodes[x]["summary"] != g.nodes[x]["title"] else "")
                  for x in top[:show]]
        lines += [f"- … +{len(e['notes']) - show} more: `brain find --text \"…\"` or `ls {folder}/`", "",
                  PROJ_END]
        return "\n".join(lines)
    by = OrderedDict()
    for x in e["notes"]:
        by.setdefault(g.nodes[x]["type"], []).append(x)
    order = list(groups(g.schema)) + sorted(t for t in by if t not in groups(g.schema))
    for typ in [t for t in order if t in by]:
        items = sorted(by[typ], key=lambda x: nfc(g.nodes[x]["title"]).casefold())
        lines.append(f"**{vault.type_label(g.schema, typ)} ({len(items)})**")
        for x in items:
            m = g.nodes[x]
            extra = [m["kind"], "ended" if m["fm"].get("valid_to") else "", m.get("summary") or ""]
            extra = [str(t) for t in extra if t and t != m["title"]]
            lines.append(f"- {g.wikilink(x)}" + (f" — {' · '.join(extra)}" if extra else ""))
        lines.append("")
    if len(lines) == 3:
        lines += ["*(folder is empty so far)*", ""]
    lines.append(PROJ_END)
    return "\n".join(lines)


def humanize(name):
    """Folder name -> title: `acme-corp` -> `Acme corp`."""
    s = nfc(name).replace("-", " ").strip()
    return s[:1].upper() + s[1:]


def new_knowledge_hub(g, folder, taken):
    """(rel, text) of a missing `<folder>-hub.md`; the stem gets the namespace as prefix when `<folder>-hub` is
    already taken anywhere in the vault (two `ideas/` folders)."""
    name = Path(folder).name
    ns = paths.namespace_of(folder)
    stem = f"{name}-hub"
    if stem.casefold() in taken and ns and ns != name:
        stem = f"{ns}-{name}-hub"
    base, k = stem, 2
    while stem.casefold() in taken:
        stem, k = f"{base[:-4]}-{k}-hub", k + 1
    taken.add(stem.casefold())
    title = f"{humanize(name)} - Hub"
    ctx = vault.namespace_context(g.schema, ns) if ns else None
    if not ctx and paths.is_split_root(g.root):  # topic folders straight under 40_Knowledge/: the root's main context
        ctx = paths.root_contexts(g.root)[0]
    fm = [f"id: map/{stem}", "type: map", "kind: hub", f"title: {title}"]
    if ctx:
        fm.append(f"context: {ctx}")
    fm.append("tags: [moc" + (f", ctx/{ctx}" if ctx else "") + "]")
    text = "---\n" + "\n".join(fm) + f"\n---\n\n# {humanize(name)} — Hub\n"
    return f"{folder}/{stem}.md", text


def note_date(g, x):
    m = g.nodes[x]
    d = str(m["fm"].get("date") or "")
    mm = vault.DATE_RE.search(d) or vault.DATE_RE.match(Path(x).name)
    return mm.group(0) if mm else ""


def render_projection(g, found):
    lines = [PROJ_START, PROJ_NOTE, ""]
    for typ, title in groups(g.schema).items():
        if typ == "project":
            key = lambda x: (STATUS_ORDER.get(str(g.nodes[x]["fm"].get("status", "")), 9),
                             nfc(g.nodes[x]["title"]).casefold())
        elif typ in ("decision", "meeting"):
            key = lambda x: ("~" if not note_date(g, x) else "", note_date(g, x), nfc(g.nodes[x]["title"]).casefold())
        else:
            key = lambda x: nfc(g.nodes[x]["title"]).casefold()
        items = sorted(found[typ], key=key)
        if typ in ("decision", "meeting"):  # newest first, undated last
            items = sorted([x for x in items if note_date(g, x)], key=lambda x: note_date(g, x), reverse=True) + \
                [x for x in items if not note_date(g, x)]
        if not items:
            continue
        lines.append(f"**{title} ({len(items)})**")
        if typ not in INLINE_GROUPS:
            for x in items:
                m = g.nodes[x]
                extra = [str(m["fm"].get("status") or "") if typ in ("project", "decision") else "",
                         m["kind"] if typ != "project" else "",
                         "ended" if m["fm"].get("valid_to") else ""]
                extra = [e for e in extra if e]
                lines.append(f"- {g.wikilink(x)}" + (f" — {', '.join(extra)}" if extra else ""))
        else:
            lines.append(" · ".join(g.wikilink(x) for x in items))
        lines.append("")
    if len(lines) == 3:
        lines.append("*(nothing in the graph yet)*")
        lines.append("")
    lines.append(PROJ_END)
    return "\n".join(lines)


def projection_file(g, r):
    return r  # areas: the hub is the area note itself


def after_first_heading_paragraph(text):
    """Offset right after the first `# ` heading and the paragraph that follows it (None if no heading)."""
    fmo = vault.Frontmatter(text)
    off = len(text) - len(fmo.body)
    m = re.search(r"^# .*$", fmo.body, re.M)
    if not m:
        return None
    pos = off + m.end()
    rest = text[pos:]
    lines = rest.split("\n")
    i, consumed = 1, len(lines[0])  # lines[0] is the tail of the heading line ("")
    while i < len(lines) and not lines[i].strip():
        consumed += 1 + len(lines[i])
        i += 1
    if i < len(lines) and not re.match(r"^(#|\||<!--|```|---)", lines[i]):
        while i < len(lines) and lines[i].strip():
            consumed += 1 + len(lines[i])
            i += 1
        return pos + consumed
    return pos


def put_block(text, block):
    if PROJ_RE.search(text):
        return PROJ_RE.sub(lambda _: block, text, count=1)
    at = after_first_heading_paragraph(text)
    if at is not None:
        head, tail = text[:at].rstrip("\n"), text[at:].lstrip("\n")
        return head + "\n\n" + block + "\n" + ("\n" + tail if tail else "")
    m = vault.LINKS_BLOCK_RE.search(text)
    if m and text[m.end():].strip() == "":
        return text[:m.start()].rstrip("\n") + "\n\n" + block + "\n" + text[m.start():]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def cmd_project(args):
    g = load(args)
    targets, create = [], {}  # create: new hub rel -> skeleton text (40_Knowledge folders without a hub)
    folders = vault.knowledge_folders(g)
    taken = {k for k in g.resolver.by_stem_ci}
    if args.all:
        for a in paths.area_dirs(g.root):
            c = paths.rel(paths.area_hub(a), g.root)
            if c in g.nodes:
                targets.append(c)
        for r, n in g.nodes.items():
            if knowledge_hub(g, r) or ((paths.is_moc(r) or vault.is_folder_hub(r, n["type"]))
                                       and PROJ_START in (vault.read(g.root / r) or "")):
                if not (paths.is_hub(r) and Path(r).parts[0] == paths.AREAS):
                    targets.append(r)
        if args.write:  # folders with >= hub_min_notes notes (recursive) or >= hub_min_subdirs subfolders get a hub
            for d, hub in sorted(vault.knowledge_hub_folders(g, folders=folders).items()):
                if not hub:
                    rel, text = new_knowledge_hub(g, d, taken)
                    create[rel] = text
    elif args.target:
        t = nfc(args.target).strip().rstrip("/")
        t = paths.rel(t, g.root) if Path(t).is_absolute() else t
        if t.startswith(paths.KNOWLEDGE + "/") and (g.root / t).is_dir() and t not in paths.REGISTRY_DIRS:
            hubs = folders.get(t, {}).get("hubs") or []
            if hubs:
                targets = [hubs[0]]
            else:
                rel, text = new_knowledge_hub(g, t, taken)
                create[rel] = text
        else:
            # role folder/title wins, then any note (entity or MOC), then an area alias
            targets = [resolve_area(g, args.target, loose=False) or g.resolve(args.target)
                       or resolve_area(g, args.target) or need(g, args.target)]
    else:
        die("give <area|entity|40_Knowledge folder> or --all")
    for rel in create:  # planned hubs count as existing for the parent hubs' folder lists
        folders.setdefault(str(Path(rel).parent), {"notes": [], "hubs": [], "subdirs": []})["hubs"].append(rel)
    ch = Changes(g, "project")
    for r in targets + list(create):
        if r in create:
            target, block = r, render_knowledge_hub(g, r, folders)
        elif folder_moc(g, r):
            target, block = r, render_folder_projection(g, r, folders)
        elif knowledge_hub(g, r):
            target, block = r, render_knowledge_hub(g, r, folders)
        else:
            target, found = projection(g, r)
            block = render_projection(g, found)
        f = projection_file(g, target) if r == target and r not in create else r
        if not args.write:
            print(f"# projection of {label(g, target) if target in g.nodes else target} -> {f}"
                  + (" (new hub; --write to create)" if r in create else ""))
            print(block)
            print()
            continue
        old = vault.read(g.root / f)
        if r in create:
            ch.write(f, put_block(create[r], block), old=None)
        elif old is None:
            title = g.nodes[target]["title"] + (" - Hub" if paths.is_hub(f) else " MOC")
            old_new = f"---\ntitle: {title}\ncontext: {g.nodes[target]['fm'].get('context', '')}\ntags: [moc]\n---\n\n# {title}\n"
            ch.write(f, put_block(old_new, block), old=None)
        else:
            ch.write(f, put_block(old, block), old=old)
    if args.write:
        ch.finish(args)


# ================================================================ validate
def validate(g, strict=False):
    sch = g.schema
    types = set(sch["types"]["entity"]) | set(sch["types"]["structural"])
    issues = []

    def add(sev, code, path, detail=""):
        issues.append({"severity": "error" if strict else sev, "code": code, "path": path, "detail": detail})

    ids, aliases = {}, {}
    for r, n in g.nodes.items():
        archived = r.startswith(paths.ARCHIVES + "/")
        if not n["id"]:
            add("warning", "missing-id", r)
        else:
            ids.setdefault(n["id"], []).append(r)
            if not ID_RE.match(n["id"]):
                add("warning", "bad-id-format", r, f"{n['id']} (expected <type>/<ascii-kebab>)")
            elif n["type_explicit"] and n["id"].split("/")[0] != n["type"]:  # ids never change, types may: info
                issues.append({"severity": "info", "code": "id-type-mismatch", "path": r,
                               "detail": f"{n['id']} vs type {n['type']}"})
        exp = expected_types(r, sch)
        if exp and n["type"] not in exp:
            add("error", "type-folder-mismatch", r, f"type {n['type']}{'' if n['type_explicit'] else ' (inferred)'}"
                f", folder expects {'/'.join(sorted(exp))}")
        if not n["type_explicit"]:
            add("warning", "missing-type", r, f"inferred {n['type']}")
        elif n["type"] not in types:
            add("error", "unknown-type", r, f"{n['type']} (not in schema.json; register it: "
                f"`brain schema add-type {n['type']} [--entity]`)")
        allowed = sch["kinds"].get(n["type"], [])
        if n["fm"].get("kind") and allowed and n["kind"] not in allowed:
            add("warning", "unknown-kind", r, f"{n['kind']} not in {allowed} (register it: "
                f"`brain schema add-kind {n['type']} {n['kind']}`)")
        if n["type_explicit"]:
            req = sch["required"].get("*", []) + sch["required"].get(n["type"], [])
            miss = [k for k in req if not n["fm"].get(k)]
            if miss:
                add("warning", "missing-required", r, ", ".join(miss))
        tt = vault.tag_types(n["tags"], sch, r)
        if n["type_explicit"] and tt and n["type"] not in tt:
            add("warning", "type-tag-mismatch", r, f"type {n['type']} vs tags {sorted(tt)}")
        elif not n["type_explicit"] and len(tt) > 1:
            add("warning", "type-tag-conflict", r, f"tags imply {sorted(tt)}")
        for k in n["keys"]:
            if k in g.rels or k in LINK_OK_KEYS:
                continue
            v = n["fm"].get(k)
            if not isinstance(v, dict) and vault.link_targets(v):
                add("error", "unknown-relation-key", r, k)
        for a in n["aliases"]:
            aliases.setdefault(nfc(a).casefold(), set()).add(r)
        # relations
        for e in g.out(r):
            if e["origin"] not in ("fm", "fm-string") or e["rel"] not in g.rels:
                continue
            spec = g.rels[e["rel"]]
            st, dt_ = n["type"], g.nodes[e["dst"]]["type"]
            if "*" not in spec["from"] and st not in spec["from"]:
                add("error" if n["type_explicit"] else "warning", "relation-source-type", r,
                    f"{e['rel']}: {st} not in {spec['from']}")
            if "*" not in spec["to"] and dt_ not in spec["to"]:
                add("error", "relation-target-type", r, f"{e['rel']} -> {e['dst']} is {dt_}, allowed {spec['to']}")
            elif spec.get("same_type") and st in spec["to"] and dt_ != st:
                add("error", "relation-target-type", r, f"{e['rel']} must link {st}->{st}, got {dt_}")
            if e["origin"] == "fm-string":
                add("warning", "relation-not-wikilink", r, f"{e['rel']}: {e['raw']} -> [[{g.link_for(e['dst'])}]]")
            if g.nodes[e["dst"]]["fm"].get("valid_to") and not archived:
                add("warning", "link-to-ended", r, f"{e['rel']} -> {e['dst']} (valid_to {g.nodes[e['dst']]['fm']['valid_to']})")
        # context must match the area the entity belongs to; a live project needs an area
        if n["type"] in ("project", "system", "org"):
            ctx = str(n["fm"].get("context") or "").strip()
            for e in g.out(r, {"area"}):
                if e["origin"] not in ("fm", "fm-string"):
                    continue
                actx = str(g.nodes[e["dst"]]["fm"].get("context") or "").strip()
                if ctx and actx and ctx != actx:
                    add("warning", "context-area-mismatch", r, f"context {ctx}, area {e['dst']} has context {actx}")
        if n["type"] == "project" and Path(r).name == "CLAUDE.md" and r.startswith(paths.PROJECTS + "/") \
                and not g.out(r, {"area"}):
            add("warning", "project-no-area", r, "no `area:` edge (brain link <project> --area <role>)")
        # broken wikilinks (body + auto:links); Archives only warn
        for t in dict.fromkeys(n["links"] + n["mentions"]):
            c = g.resolver.candidates(t)
            if not c:
                ext = g.external(t)
                if ext:  # resolves in a sibling root / workspace docs: fine in Obsidian, not in this graph
                    issues.append({"severity": "info", "code": "cross-root-link", "path": r,
                                   "detail": f"[[{t}]] -> {ext}"})
                else:
                    add("warning" if archived else "error", "broken-link", r, f"[[{t}]]")
            elif "/" in t and not any(vault.strip_ext(x).endswith(vault.strip_ext(t)) or
                                      (x.endswith("/CLAUDE.md") and t.endswith("CLAUDE")) for x in c):
                ext = g.external(t)
                if ext and vault.strip_ext(ext).endswith("/" + vault.strip_ext(vault.Resolver.clean(t))):
                    issues.append({"severity": "info", "code": "cross-root-link", "path": r,
                                   "detail": f"[[{t}]] -> {ext}"})
                else:
                    add("warning", "stale-path-link", r, f"[[{t}]] -> {c[0]}")
    for u in g.unresolved:
        ext = [x for x in (g.external(t) for t in vault.link_targets(u["raw"])) if x]
        if ext:
            add("warning", "relation-cross-root", u["src"], f"{u['rel']}: {u['raw']} -> {ext[0]} (relations stay "
                "inside one root; use a plain body link)")
        elif u["origin"] == "fm":
            add("error", "relation-unresolved", u["src"], f"{u['rel']}: {u['raw']}")
        else:  # a plain name without a note (placeholder for a person/thing): no link breaks -> info
            issues.append({"severity": "info", "code": "relation-unresolved-string", "path": u["src"],
                           "detail": f"{u['rel']}: {u['raw']}"})
    for i, rs in ids.items():
        if len(rs) > 1:
            for r in rs:
                add("error", "duplicate-id", r, f"{i} also in {[x for x in rs if x != r]}")
    stems = {}
    for f in g.all_files:
        if f.endswith(".md"):
            stems.setdefault(Path(f).stem.casefold(), set()).add(f)
    for a, rs in aliases.items():
        owners = stems.get(a, set())  # notes whose file is named like the alias
        foreign = sorted(x for x in rs if Path(x).stem.casefold() != a)
        if owners and foreign:  # identity: note A calls itself X while note X exists -> duplicate entity or bad alias
            add("warning", "duplicate-alias", foreign[0], f"'{a}' is the file name of {sorted(owners)}, alias of "
                f"{foreign} (same thing twice? merge or drop the alias)")
        elif len(rs) > 1:  # a shared alternative name (hostname in several installations): resolution only
            issues.append({"severity": "info", "code": "duplicate-alias", "path": sorted(rs)[0],
                           "detail": f"'{a}' used by {sorted(rs)}"})
    # 40_Knowledge/: depth below a namespace, loose notes at the root, one file stem per note
    kcfg = vault.knowledge_cfg(sch)
    for r in g.nodes:
        parts = Path(r).parts
        if parts[0] != paths.KNOWLEDGE:
            continue
        if len(parts) == 2 and parts[1] != Path(paths.KNOWLEDGE_MOC).name and not is_companion(parts[1], sch):
            add("warning", "knowledge-loose", r, f"a note directly in {paths.KNOWLEDGE}/ belongs to a namespace "
                f"({paths.KNOWLEDGE}/<ns>/…) or a registry ({paths.PEOPLE_DIR}/, {paths.ORGS_DIR}/)")
        depth = len(paths.topic_parts(r))
        if paths.namespace_of(r) and depth > kcfg["max_depth"]:
            add("warning", "knowledge-depth", r, f"{depth} folder levels below namespace "
                f"{paths.namespace_of(r)}/ (max {kcfg['max_depth']})")
    by_stem = {}
    for r in g.nodes:
        name = Path(r).name
        if name in paths.NAME_EXCEPTIONS or name in sch["companions"]["names"] or raw_exempt(r):
            continue
        by_stem.setdefault(Path(r).stem.casefold(), []).append(r)
    for stem, rs in by_stem.items():
        if len(rs) > 1:
            for r in rs:
                add("warning", "stem-collision", r, f"'{stem}' also {[x for x in rs if x != r]} (bare [[{stem}]] "
                    "is ambiguous; `brain rename` one of them)")
    # multi-root workspace: a note's context must belong to this root (50_Raw/ holds shared material)
    if paths.is_split_root(g.root):
        allowed = paths.root_contexts(g.root)
        for r, n in g.nodes.items():
            ctx = nfc(str(n["fm"].get("context") or "")).strip()
            if ctx and ctx in paths.CONTEXTS and ctx not in allowed and not r.startswith(paths.RESOURCES + "/"):
                other = paths.contexts_root(ctx)
                add("warning", "context-wrong-root", r, f"context {ctx} belongs to {'/'.join(other) or '?'}/, "
                    f"this root holds {'/'.join(allowed)}")
    # stems stay unique across the whole workspace (bare [[stem]] links resolve by name in Obsidian)
    ext = g.external_names
    if ext.by_stem_ci:
        for stem, rs in by_stem.items():
            r0 = rs[0]
            name = Path(r0).name
            if name in CROSS_STEM_SKIP or paths.is_hub(name) or paths.is_daily(r0) or name == "README.md":
                continue
            others = [x for x in ext.by_stem_ci.get(stem, []) if Path(x).name not in CROSS_STEM_SKIP
                      and f"/{paths.RESOURCES}/" not in f"/{x}"]
            if others:
                for r in rs:
                    add("warning", "cross-root-stem-collision", r, f"'{stem}' also {others[:3]} (stems stay unique "
                        "across roots; `brain rename` one of them)")
    for d, subdirs, docs in branch_leaf(g.root, sch):  # 50_Raw/ is skipped inside branch_leaf
        add("warning", "branch-leaf", d, f"{len(subdirs)} folder(s) + documents: {', '.join(docs[:4])}"
            + (f" … +{len(docs) - 4}" if len(docs) > 4 else ""))
    return issues


def raw_exempt(r):
    """50_Raw/ holds material we did not write, kept as-is: no structural checks (depth, branch/leaf, naming,
    name length, stem collisions) apply below it."""
    return paths.in_dirs(r, [paths.RESOURCES])


CROSS_STEM_SKIP = {"CLAUDE.md", "README.md", "AGENTS.md", "SKILL.md", paths.RELATION_MAP, Path(paths.KNOWLEDGE_MOC).name}
ID_RE = re.compile(r"^[a-z][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")  # <type>/<ascii-kebab>; kebab type names allowed
# folder -> allowed types (validate: type-folder-mismatch); companions (README, MOC, Hub, …) are skipped. Only the
# Knowledge registries (schema.json › knowledge.registries), project CLAUDE.md and area <role>-hub.md fix a type; any other
# 40_Knowledge/ folder is a namespace/topic and holds any type.
TYPE_FOLDERS = [
    (re.compile("^" + re.escape(paths.PROJECTS) + r"/[^/]+/CLAUDE\.md$"), {"project"}),
    (re.compile("^" + re.escape(paths.AREAS) + r"/([^/]+)/\1-hub\.md$"), {"area"}),
]


def type_folders(sch):
    kc = vault.knowledge_cfg(sch)
    return [(re.compile("^" + re.escape(f"{kc['root']}/{d}") + "/"), {t}) for d, t in kc["registries"].items()] \
        + TYPE_FOLDERS


def expected_types(r, sch):
    if Path(r).name != "CLAUDE.md" and is_companion(Path(r).name, sch):
        return None
    for rx, types in type_folders(sch):
        if rx.search(r):
            return types
    return None


def is_companion(name, sch):
    return vault.is_companion(name, sch)


def branch_leaf(root, sch):
    """[(dir, [subdirs], [non-companion docs])] for folders under the branch/leaf roots holding both."""
    out = []
    tops = sch["branch_leaf_roots"]
    files = [paths.rel(p, root) for top in tops for p in paths.iter_files(root, top)]
    dirs = {}
    for f in files:
        parts = Path(f).parts
        if not parts or parts[0] not in tops or paths.is_skipped(f) or raw_exempt(f):
            continue
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            dirs.setdefault(d, [set(), []])
            if i < len(parts) - 1:
                dirs[d][0].add(parts[i])
        dirs.setdefault("/".join(parts[:-1]), [set(), []])[1].append(parts[-1])
    for d in sorted(dirs):
        subdirs, docs = dirs[d]
        docs = [x for x in docs if not is_companion(x, sch)]
        if subdirs and docs:
            out.append((d, sorted(subdirs), sorted(docs)))
    return out


def validate_file(g, path, strict=False):
    """Issues of one note (the full validation filtered to it, + naming and parse checks) and its vault-relative
    path. Also covers a note outside the graph (graph:false folder, skipped path): then only naming/frontmatter."""
    p = Path(path)
    r = paths.rel(p if p.is_absolute() else (Path.cwd() / p), g.root)
    if r.startswith("..") or Path(r).is_absolute():
        return r, [{"severity": "error", "code": "outside-vault", "path": str(path), "detail": str(g.root)}]
    sev = (lambda s: "error" if strict else s)
    issues = [i for i in validate(g, strict) if i["path"] == r or (i["code"] == "branch-leaf" and i["path"] ==
                                                                   str(Path(r).parent))]
    if not (g.root / r).is_file():
        issues.append({"severity": sev("warning"), "code": "missing-file", "path": r, "detail": ""})
        return r, issues
    bad = [x for x in Path(r).parts[1:] if not paths.is_kebab_name(x)]
    if bad and Path(r).parts[0] in paths.TOP_LEVEL and not raw_exempt(r):  # ROOT_TOP + templates/system of a single-root vault
        issues.append({"severity": sev("warning"), "code": "name-not-kebab", "path": r,
                       "detail": f"{', '.join(bad)} (ascii kebab-case; `brain rename` -> "
                                 f"{paths.kebab(Path(r).stem)}.md)"})
    text = vault.read(g.root / r) or ""
    if text.startswith("---") and not vault.FM2_RE.match(text):
        issues.append({"severity": "error", "code": "frontmatter-unclosed", "path": r, "detail": "no closing ---"})
    if r not in g.nodes:
        why = "graph:false folder" if r in g.skipped else "skipped path (template, log, root instructions)"
        issues.append({"severity": "info", "code": "not-in-graph", "path": r, "detail": why})
    return r, [i for i in issues if i["code"] != "branch-leaf" or i["path"] != r]


def cmd_validate(args):
    g = load(args)
    if args.file:
        r, issues = validate_file(g, args.file, args.strict)
        errors = [i for i in issues if i["severity"] == "error"]
        warns = [i for i in issues if i["severity"] == "warning"]
        if args.json:
            print(json.dumps({"file": r, "errors": len(errors), "warnings": len(warns), "issues": issues},
                             ensure_ascii=False, indent=1))
        else:
            print(f"# validate {r}: {len(errors)} error(s), {len(warns)} warning(s)")
            for i in sorted(issues, key=lambda i: (i["severity"] != "error", i["code"])):
                print(f"  {i['severity']}: {i['code']}" + (f"  — {i['detail']}" if i["detail"] else ""))
        sys.exit(1 if errors else 0)
    issues = validate(g, args.strict)
    errors = [i for i in issues if i["severity"] == "error"]
    infos = [i for i in issues if i["severity"] == "info"]
    nwarn = len(issues) - len(errors) - len(infos)
    if args.json:
        print(json.dumps({"errors": len(errors), "warnings": nwarn, "infos": len(infos), "issues": issues},
                         ensure_ascii=False, indent=1))
    else:
        by = OrderedDict()
        for i in sorted(issues, key=lambda i: (i["severity"] != "error", i["code"], i["path"])):
            by.setdefault((i["severity"], i["code"]), []).append(i)
        print(f"# validate: {len(errors)} error(s), {nwarn} warning(s) in {len(g.nodes)} notes"
              + (f", {len(infos)} info" if infos else "") + (" [strict]" if args.strict else ""))
        for (sev, code), items in by.items():
            print(f"\n## {sev}: {code} ({len(items)})")
            for i in items if args.all else items[:args.limit]:
                print(f"  {i['path']}" + (f"  — {i['detail']}" if i["detail"] else ""))
            if not args.all and len(items) > args.limit:
                print(f"  … +{len(items) - args.limit} (use --all)")
    sys.exit(1 if errors else 0)


# ================================================================ create
BUILTIN_TEMPLATE = "---\ntitle: {{TITLE}}\n---\n\n# {{TITLE}}\n"


def template_for(typ, root=None):
    """Template file name for a type: TEMPLATES map, else _templates/<type>.md when it exists, else None
    (built-in skeleton)."""
    if typ in TEMPLATES:
        return TEMPLATES[typ]
    root = root or paths.find_root()
    return f"{typ}.md" if (paths.templates_dir(root) / f"{typ}.md").is_file() else None


def fill_template(name, values):
    text = (vault.read(paths.templates_dir(paths.find_root()) / name) if name else None) or BUILTIN_TEMPLATE
    if not values.get("CONTEXT"):
        text = re.sub(r",\s*ctx/\{\{CONTEXT\}\}", "", text)
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v or "")
    if values.get("DATE"):  # Obsidian tokens ({{date:YYYY-MM-DD}}, {{date:dddd}}) in the daily template
        text = vault.render_template(text, values["DATE"])
    return text


KNOWLEDGE_TYPES_FIXED = {"person", "org", "project", "area", "decision", "meeting", "daily"}  # own destinations


def knowledge_dest(g, args, ctx):
    """(folder rel, namespace) for a knowledge note: --in <path under 40_Knowledge>, else --namespace (default from
    --context via knowledge.context_namespaces, else the shared namespace) + --topic a/b. Enforces kebab names and
    knowledge.max_depth; refuses the registries and the 40_Knowledge/ root."""
    kc = vault.knowledge_cfg(g.schema)
    if args.into:
        raw = nfc(args.into).strip().strip("/")
        raw = raw[len(paths.KNOWLEDGE) + 1:] if raw.startswith(paths.KNOWLEDGE + "/") else raw
        segs = [x for x in raw.split("/") if x]
        if not segs:
            die(f"--in needs a namespace folder below {paths.KNOWLEDGE}/")
        ns, topic = segs[0], segs[1:]
    else:
        ns = args.namespace or kc["context_namespaces"].get(ctx or "") or kc["shared_namespace"]
        topic = [x for x in nfc(args.topic or "").strip("/").split("/") if x]
    for seg in [ns] + topic:
        if not paths.KEBAB_RE.match(seg):
            die(f"folder name {seg!r} is not ascii kebab-case (try {paths.kebab(seg)!r})")
    if ns in kc["registries"]:
        die(f"{paths.KNOWLEDGE}/{ns}/ is the {kc['registries'][ns]} registry; use `brain create "
            f"{kc['registries'][ns]}` or another namespace")
    if len(topic) > kc["max_depth"]:
        die(f"{len(topic)} topic levels below namespace {ns}/ (max {kc['max_depth']}, schema.json › knowledge)")
    return "/".join([paths.KNOWLEDGE, ns] + topic), ns


def free_stem(g, stem, ns):
    """A file stem unique in the whole vault: `stem`, else `<ns>-stem`, else `<ns>-stem-2` …"""
    taken = g.resolver.by_stem_ci
    if stem.casefold() not in taken:
        return stem
    base = paths.kebab(f"{ns}-{stem}")
    cand, k = base, 2
    while cand.casefold() in taken:
        cand, k = f"{base}-{k}", k + 1
    return cand


def cmd_create(args):
    g = load(args)
    typ, title = args.type, nfc(args.title).strip()
    sch = g.schema
    known = vault.all_types(sch)
    if typ not in known:
        die(f"unknown type {typ}; one of {known} (new type: `brain schema add-type {typ} [--entity]`)")
    kinds = sch["kinds"].get(typ, [])
    if args.kind and kinds and args.kind not in kinds:
        die(f"kind {args.kind} not allowed for {typ}: {kinds} (new kind: `brain schema add-kind {typ} {args.kind}`)")
    area = need(g, args.area, "area") if args.area else None
    if area and g.nodes[area]["type"] != "area":
        die(f"--area must be an area note, got {label(g, area)}")
    proj = need(g, args.project, "project") if args.project else None
    ctx = args.context or (g.nodes[area]["fm"].get("context") if area else None) or \
        (paths.folder_context(proj) if proj else None)
    knowledge = typ not in KNOWLEDGE_TYPES_FIXED
    if (args.namespace or args.topic or args.into) and not knowledge:
        die(f"--namespace/--topic/--in are for knowledge notes; {typ} has its own place")
    if knowledge and not ctx and (args.namespace or args.into):  # a namespace implies its context (private/ -> private)
        ctx = vault.namespace_context(sch, knowledge_dest(g, args, None)[1])
    if ctx and ctx not in paths.CONTEXTS:
        die(f"unknown context {ctx}; one of {paths.CONTEXTS}")
    if ctx and ctx not in paths.root_contexts(g.root):
        other = paths.contexts_root(ctx)
        die(f"context {ctx} does not belong to this root ({g.root.name}/: {', '.join(paths.root_contexts(g.root))}); "
            f"create it in root {other[0] if other else '?'}/ (cd there)")
    if typ in ("person", "project", "area") and not ctx:
        die(f"{typ} needs --context (or --area)")
    date = TODAY.isoformat()
    slug = args.slug or ""
    root = g.root
    dated = f"{date} {title}"
    fname = paths.kebab(title)  # ascii kebab file names; the human name stays in `title:`
    if slug and typ != "project":  # --slug picks the file stem (and id) instead of the title
        fname = paths.kebab(slug)

    def branch_sub(folder, sub):
        return folder / sub if any(d.is_dir() for d in folder.iterdir()) else folder

    renamed = None
    if typ == "project":
        slug = slug or f"{paths.CTX_SLUG[ctx]}-" + "-".join(vault.slugify(title).split("-")[:4])
        if not paths.SLUG_RE.match(slug):
            die(f"bad project slug {slug}")
        dest = root / paths.PROJECTS / slug / "CLAUDE.md"
        idslug = slug
    elif typ == "area":
        dest = root / paths.AREAS / fname / f"{fname}{paths.HUB_SUFFIX}"  # the area note is its hub
        idslug = vault.slugify(slug or title)
    elif typ == "person":
        dest = paths.people_dir(root, ctx) / f"{fname}.md"
        idslug = vault.slugify(slug or title)
    elif typ == "org":
        dest = root / paths.ORGS_DIR / f"{fname}.md"
        idslug = vault.slugify(slug or title)
    elif typ in ("decision", "meeting"):
        sub = paths.DECISIONS_SUB if typ == "decision" else paths.MEETINGS_SUB
        dname = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", slug) or title  # --slug without a duplicate date
        dfile = f"{date}-{paths.kebab(dname, paths.MAX_STEM - 11)}.md"
        if proj:
            dest = branch_sub(root / Path(proj).parent, sub) / dfile
        elif area:
            dest = root / Path(area).parent / sub / dfile
        elif typ == "meeting":
            dest = root / paths.MEETINGS / dfile
        else:  # decision with only a context: the primary area of that context, else 00_Inbox/
            prim = [r for r, m in g.nodes.items() if m["type"] == "area" and not in_archives(r) and ctx
                    and m["fm"].get("context") == ctx and str(m["fm"].get("primary", "")).lower() == "true"]
            dest = (root / Path(prim[0]).parent / sub / dfile) if len(prim) == 1 else root / paths.INBOX / dfile
        idslug = vault.slugify(dated)
    elif typ == "daily":
        date = title if re.match(r"^\d{4}-\d{2}-\d{2}$", title) else date
        dest = paths.daily_path(date, root)
        idslug = date
    else:  # system, concept, note, map, any type added with `brain schema add-type`: 40_Knowledge/<ns>/<topic>/
        folder, ns = knowledge_dest(g, args, ctx)
        stem = free_stem(g, fname, ns)
        if stem != fname:
            renamed = f"'{fname}' already exists ({g.resolver.by_stem_ci[fname.casefold()][0]}); file named '{stem}'"
        dest = root / folder / f"{stem}.md"
        idslug = vault.slugify(slug or title)
    rel = paths.rel(dest, root)
    if dest.exists():
        die(f"exists: {rel}")
    stem = dest.stem if dest.name != "CLAUDE.md" else None
    if stem and g.resolver.by_stem_ci.get(stem.casefold()) and not args.force:
        die(f"a note named '{stem}' already exists ({g.resolver.by_stem_ci[stem.casefold()][0]}); wikilinks would be ambiguous (--force)")
    nid = f"{typ}/{idslug}"
    existing = {n["id"] for n in g.nodes.values() if n["id"]}
    base, k = nid, 2
    while nid in existing:
        nid, k = f"{base}-{k}", k + 1
    d = dt.date.fromisoformat(date)
    values = {"NAME": title, "TITLE": title, "FILE": Path(rel).stem if Path(rel).name != "CLAUDE.md" else Path(rel).parent.name,
              "DATE": date, "CONTEXT": ctx or "", "ID": nid, "KIND": args.kind or "",
              "SLUG": slug, "PROJECT_SLUG": Path(proj).parts[1] if proj else "", "SOURCE": "manual",
              "WEEKDAY": vault.WEEKDAYS[d.weekday()], "AREA": f"[[{g.link_for(area)}]]" if area else ""}
    text = fill_template(template_for(typ, root), values)
    fmo = vault.Frontmatter(text)
    fmo.remove("id").remove("type")  # drop template hints on these two lines
    fmo.set("type", typ, first=True)
    fmo.set("id", nid, first=True)
    if args.kind:
        fmo.remove("kind").set("kind", args.kind, after=["type"])
    if ctx and "context" not in fmo:
        fmo.set("context", ctx, after=["title"])
    if area and typ in g.rels["area"]["from"]:
        fmo.set("area", g.wikilink(area), after=["context", "title"])
    if proj and typ in g.rels["project"]["from"]:
        fmo.set("project", g.wikilink(proj), after=["context", "title"])
    ch = Changes(g, "create")
    ch.write(rel, fmo.render(), old=None)
    if renamed:
        ch.notes.append(renamed)
    ch.finish(args)


# ================================================================ link / unlink
def rel_arg(args, g):
    chosen = [(k, getattr(args, k)) for k in g.rels if getattr(args, k, None)]
    if len(chosen) != 1:
        die("give exactly one --<relation> <target>; relations: " + ", ".join(g.rels))
    return chosen[0]


def item_hits(g, items, tgt, src):
    """Indexes of items (str) that resolve to tgt."""
    hits = []
    for i, v in enumerate(items):
        ts = vault.link_targets(v) or [v]
        if any(g.resolver.resolve(t, src) == tgt for t in ts):
            hits.append(i)
    return hits


def rel_after(fmo, g):
    present = [k for k in fmo.keys() if k in g.rels]
    return list(reversed(present)) + ["kind", "type", "context", "title", "id"]


def cmd_link(args):
    g = load(args)
    key, tref = rel_arg(args, g)
    src, tgt = need(g, args.note), need(g, tref, "target")
    spec = g.rels[key]
    st, tt = g.nodes[src]["type"], g.nodes[tgt]["type"]
    problems = []
    if "*" not in spec["from"] and st not in spec["from"]:
        problems.append(f"{key}: source type {st} not in {spec['from']}")
    if "*" not in spec["to"] and tt not in spec["to"]:
        problems.append(f"{key}: target type {tt} not in {spec['to']}")
    if spec.get("same_type") and st != tt:
        problems.append(f"{key}: must link {st}->{st}, got {tt}")
    if problems and not args.force:
        die("; ".join(problems) + " (--force to override)")
    text = vault.read(g.root / src)
    fmo = vault.Frontmatter(text)
    link = g.wikilink(tgt)
    cur = fmo.get(key)
    ended_line = None
    if spec["cardinality"] == "one":
        if isinstance(cur, list):
            cur = cur[0] if len(cur) == 1 else (die(f"{key} holds several values: {cur}") or "")
        if cur:
            if item_hits(g, [cur], tgt, src):
                if cur == link:
                    print("nothing to change (already linked)")
                    return
            elif not args.replace:
                die(f"{src} already has {key}: {cur}; unlink it first or pass --replace")
            else:
                ended_line = f"- {TODAY.isoformat()} — ended: {key} {cur if '[[' in cur else '[[' + cur + ']]'} " \
                             f"(replaced by {link}, brain link --replace)"
        fmo.set(key, link, after=rel_after(fmo, g))
    else:
        items = cur if isinstance(cur, list) else [cur] if cur else []
        hits = item_hits(g, items, tgt, src)
        if hits and items[hits[0]] == link:
            print("nothing to change (already linked)")
            return
        if hits:
            items[hits[0]] = link  # upgrade a legacy string to a wikilink
        else:
            items.append(link)
        fmo.set(key, items, after=rel_after(fmo, g))
    new = fmo.render()
    if ended_line:
        new = append_log(new, ended_line)
    ch = Changes(g, "link")
    ch.write(src, new, old=text)
    ch.finish(args)


def append_log(text, line):
    """Append `line` at the end of the `## Log` section (created before a trailing auto:links block if missing)."""
    m = re.search(r"^## Log[ \t]*$", text, re.M)
    if m:
        rest = text[m.end():]
        nxt = re.search(r"^(## |<!-- auto:links start)", rest, re.M)
        end = m.end() + (nxt.start() if nxt else len(rest))
        tail = text[end:]
        return text[:m.end()] + text[m.end():end].rstrip("\n") + "\n" + line + "\n" + ("\n" + tail if tail else "")
    lm = vault.LINKS_BLOCK_RE.search(text)
    if lm and text[lm.end():].strip() == "":
        return text[:lm.start()].rstrip("\n") + f"\n\n## Log\n{line}\n\n" + text[lm.start():].lstrip("\n")
    return text.rstrip("\n") + f"\n\n## Log\n{line}\n"


def cmd_unlink(args):
    g = load(args)
    key, tref = rel_arg(args, g)
    src, tgt = need(g, args.note), need(g, tref, "target")
    text = vault.read(g.root / src)
    fmo = vault.Frontmatter(text)
    cur = fmo.get(key)
    items = cur if isinstance(cur, list) else [cur] if cur else []
    hits = item_hits(g, items, tgt, src)
    if not hits:
        die(f"{src} has no {key} -> {tgt}")
    removed = [items[i] for i in hits]
    items = [v for i, v in enumerate(items) if i not in hits]
    if g.rels[key]["cardinality"] == "one" and not isinstance(cur, list):
        fmo.set(key, "")
    else:
        fmo.set(key, items)
    ended = args.ended or TODAY.isoformat()
    line = f"- {ended} — ended: {key} {g.wikilink(tgt)} ({args.source or 'brain unlink'})"
    new = append_log(fmo.render(), line)
    ch = Changes(g, "unlink")
    ch.write(src, new, old=text)
    ch.notes.append(f"removed {key}: {', '.join(removed)}")
    ch.finish(args)


# ================================================================ move / rename
def cmd_move(args):
    g = load(args)
    src = need(g, args.note)
    if Path(src).name in ("CLAUDE.md", "AGENTS.md", "README.md"):
        die(f"refusing to move {Path(src).name} alone; move the whole folder (git mv) instead")
    dest_dir = nfc(args.dest).strip("/")
    if Path(dest_dir).is_absolute():
        dest_dir = paths.rel(dest_dir, g.root)
    dst = f"{dest_dir}/{Path(src).name}"
    if dst == src:
        die("already there")
    if (g.root / dst).exists():
        die(f"exists: {dst}")
    ch = Changes(g, "move")
    same = [f for f in g.resolver.by_stem.get(Path(src).stem, []) if f != src]
    if same:
        ch.notes.append(f"warning: filename '{Path(src).stem}' is not unique ({same}); bare links may resolve elsewhere")
    ch.move(src, dst)
    for f, new in rewrite_links(g, {src: dst}).items():
        ch.write(dst if f == src else f, new, orig=f)
    ch.finish(args)


def sibling_links(g, stem):
    """Workspace-relative notes in sibling roots whose text contains a wikilink to `stem` (names-only scan)."""
    pat = re.compile(r"\[\[(?:[^\]|#^]*/)?" + re.escape(stem) + r"(?:\.md)?(?:[#^|][^\]]*)?\]\]")
    out = []
    for sib in paths.sibling_roots(g.root):
        for p in paths.iter_notes(sib):
            if pat.search(vault.read(p) or ""):
                out.append(f"{sib.name}/{paths.rel(p, sib)}")
    return out


def cmd_rename(args):
    """The file name becomes ascii kebab-case; a human name ("Ada Example") becomes the `title:` and the
    previous title / file stem go to `aliases`. `id` never changes."""
    g = load(args)
    src = need(g, args.note)
    if Path(src).name == "CLAUDE.md":
        die("rename the project folder (git mv) instead of CLAUDE.md")
    raw = vault.strip_ext(nfc(args.new).strip())
    if "/" in raw or not raw:
        die("new name must be a plain filename (use `move` for folders)")
    new_stem = raw if paths.KEBAB_RE.match(raw) else paths.kebab(raw)
    new_title = raw if raw != new_stem else None
    old_stem = Path(src).stem
    dst = str(Path(src).with_name(new_stem + ".md"))
    if dst == src and not new_title:
        die("nothing to rename")
    if dst != src and nfc(dst).casefold() != nfc(src).casefold() and (g.root / dst).exists():
        die(f"exists: {dst}")
    if g.resolver.by_stem_ci.get(new_stem.casefold(), []) not in ([], [src]):
        die(f"a note named '{new_stem}' already exists: {g.resolver.by_stem_ci.get(new_stem.casefold())}")
    rewrites = rewrite_links(g, {src: dst}) if dst != src else {}
    ch = Changes(g, "rename")
    if dst != src:
        ch.move(src, dst)
    for f, new in rewrites.items():
        if f != src:
            ch.write(f, new, orig=f)
    text = rewrites.get(src, vault.read(g.root / src))
    fmo = vault.Frontmatter(text)
    old_title = nfc(str(fmo.get("title") or ""))
    if new_title:
        fmo.set("title", new_title, after=["type", "id"])
    elif old_title in ("", old_stem) and "title" in fmo:
        fmo.set("title", new_stem)
    title = nfc(str(fmo.get("title") or ""))
    text = fmo.render()
    for a in (old_stem, old_title):
        if a and a not in (title, new_stem):
            text = add_alias(text, a)
    ch.write(dst, text, old=vault.read(g.root / src))
    ch.notes.append(f"{len([f for f in rewrites if f != src])} note(s) with rewritten links; id kept: "
                    f"{g.nodes[src]['id'] or '(none)'}")
    if dst != src:
        for f in sibling_links(g, old_stem):
            ch.notes.append(f"link to [[{old_stem}]] in the sibling root, not rewritten (fix by hand): {f}")
    ch.finish(args)


# ================================================================ migrate ids
def cmd_migrate(args):
    g = load(args)
    if args.action == "ids":
        existing = {n["id"] for n in g.nodes.values() if n["id"]}
        ch = Changes(g, "migrate-ids")
        added = Counter()
        for r in sorted(g.nodes):
            n = g.nodes[r]
            if n["id"] and n["type_explicit"]:
                continue
            typ = n["type"]
            p = Path(r)
            if p.name == "CLAUDE.md" and len(p.parts) >= 2:
                slug = p.parts[-2] if typ == "project" else vault.slugify(p.parts[-2])
            elif typ == "daily":
                slug = p.stem
            else:
                slug = vault.slugify(p.stem)
            text = vault.read(g.root / r)
            fmo = vault.Frontmatter(text)
            if not n["type_explicit"]:
                fmo.set("type", typ, first=True)
            if not n["id"]:
                nid, k = f"{typ}/{slug}", 2
                base = nid
                while nid in existing:
                    nid, k = f"{base}-{k}", k + 1
                existing.add(nid)
                fmo.set("id", nid, first=True)
            added[typ] += 1
            new = fmo.render()
            assert new.endswith(fmo.body)
            ch.write(r, new, old=text)
        ch.notes.append("ids/types to add: " + ", ".join(f"{k} {v}" for k, v in added.most_common()))
        ch.finish(args, args.limit)


# ================================================================ schema registry
TYPE_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def schema_usage(g):
    """(Counter type, Counter (type, kind), off-schema types, off-schema kinds) over the graph."""
    sch = g.schema
    known = set(vault.all_types(sch))
    types = Counter(n["type"] for n in g.nodes.values())
    kinds = Counter((n["type"], n["kind"]) for n in g.nodes.values() if n["kind"])
    off_t = Counter({t: c for t, c in types.items() if t not in known})
    off_k = Counter({(t, k): c for (t, k), c in kinds.items()
                     if t in known and sch["kinds"].get(t) and k not in sch["kinds"][t]})
    return types, kinds, off_t, off_k


def cmd_schema(args):
    path = vault.schema_path()
    if args.action == "list":
        g = load(args)
        sch = g.schema
        types, kinds, off_t, off_k = schema_usage(g)
        if args.json:
            print(json.dumps({"path": str(path), "version": sch.get("version"),
                              "types": {grp: [{"type": t, "label": vault.type_label(sch, t), "notes": types.get(t, 0),
                                               "kinds": {k: kinds.get((t, k), 0) for k in sch["kinds"].get(t, [])}}
                                              for t in ts] for grp, ts in sch["types"].items()},
                              "off_schema_types": dict(off_t.most_common()),
                              "off_schema_kinds": {f"{t}/{k}": c for (t, k), c in off_k.most_common()}},
                             ensure_ascii=False, indent=1))
            return
        print(f"# schema v{sch.get('version')} ({paths.rel(path, g.root)}): " +
              ", ".join(f"{len(ts)} {grp}" for grp, ts in sch["types"].items()) + " types")
        for grp, ts in sch["types"].items():
            print(f"\n## {grp}")
            for t in ts:
                ks = sch["kinds"].get(t, [])
                kd = ", ".join(f"{k} {kinds.get((t, k), 0)}" for k in ks) if ks else "(any)"
                print(f"  {t:<10} {vault.type_label(sch, t):<12} {types.get(t, 0):>5} notes · kinds: {kd}")
        print("\n## off-schema values in the vault")
        print("  types: " + (", ".join(f"{t} {c}" for t, c in off_t.most_common()) or "—")
              + ("   (`brain schema add-type <name> [--entity]`)" if off_t else ""))
        print("  kinds: " + (", ".join(f"{t}/{k} {c}" for (t, k), c in off_k.most_common()) or "—")
              + ("   (`brain schema add-kind <type> <kind>`)" if off_k else ""))
        return
    root = paths.find_root()
    raw = vault.load_schema_raw(path)
    old = path.read_text(encoding="utf-8")
    known = [t for grp in raw["types"].values() for t in grp]
    if args.action == "add-type":
        name = args.name
        if not TYPE_NAME_RE.match(name):
            die(f"type name {name!r} must be ascii kebab-case starting with a letter (e.g. {paths.kebab(name)!r})")
        if name in known:
            die(f"type {name} already exists in schema.json")
        ks = [k.strip() for k in (args.kinds or "").split(",") if k.strip()]
        bad = [k for k in ks if not paths.KEBAB_RE.match(k)]
        if bad or len(set(ks)) != len(ks):
            die(f"kinds must be distinct ascii kebab names: {bad or ks}")
        req = [k.strip() for k in (args.required or "").split(",") if k.strip()]
        raw["types"]["entity" if args.entity else "structural"].append(name)
        raw["kinds"][name] = ks
        if args.label:
            raw.setdefault("labels", {})[name] = nfc(args.label).strip()
        if req:
            raw["required"][name] = req
        detail = f"{'entity' if args.entity else 'structural'} type {name}" + (f", kinds {ks}" if ks else "") + \
            (f", label {args.label}" if args.label else "") + (f", required {req}" if req else "")
    else:
        typ, kind = args.type, args.kind
        if typ not in known:
            die(f"unknown type {typ}; one of {known} (`brain schema add-type {typ}` first)")
        if not paths.KEBAB_RE.match(kind):
            die(f"kind {kind!r} must be ascii kebab-case (e.g. {paths.kebab(kind)!r})")
        cur = raw["kinds"].setdefault(typ, [])
        if kind in cur:
            die(f"kind {kind} already exists for {typ}")
        if not cur:
            print(f"# note: kinds[{typ}] was empty (= any kind accepted); from now on only the listed kinds are",
                  file=sys.stderr)
        cur.append(kind)
        detail = f"kind {typ}/{kind}"
    new = vault.dump_schema(raw)
    rel = paths.rel(path, root)
    if not args.apply:
        print(vault.udiff(rel, old, new), end="")
        print(f"# dry run: schema.json {detail}; add --apply to write")
        return
    vault.write(path, new)
    vault.log(root, f"schema-{args.action}", rel, detail, cmd="schema")
    print(f"applied: {detail}; logged to {paths.BRAIN_LOGS}/{TODAY.isoformat()}.jsonl")


# ================================================================ doctor
def cmd_doctor(args):
    """Generic health checks, offline: python, config, vault folders, schema, git, sync conflict copies."""
    import shutil
    import subprocess
    import config
    bad = []

    def line(ok, msg, level="error"):
        mark = "ok  " if ok else ("FAIL" if level == "error" else "warn")
        print(f"  {mark} {msg}")
        if not ok and level == "error":
            bad.append(msg)

    print("== python ==")
    line(sys.version_info >= (3, 10), f"python {sys.version.split()[0]} (3.10+ required)")
    print("== config ==")
    cp = config.config_path()
    line(cp.is_file(), f"{cp.name} " + ("present" if cp.is_file() else "missing: defaults in use (run onboarding)"),
         "warning")
    line(config.ERROR is None, f"config parses{'' if config.ERROR is None else ': ' + config.ERROR}")
    for problem in config.check(paths.CFG):
        line(False, f"config: {problem}")
    print("== vault ==")
    try:
        root = paths.find_root()
    except SystemExit as e:
        line(False, str(e))
        root = None
    roots = paths.all_roots(root) or ([root] if root else [])
    for r in roots:
        missing = [t for t in paths.ROOT_TOP if not (r / t).is_dir()]
        line(not missing, f"root {paths.rel(r, paths.workspace()) if r != paths.workspace() else '.'}: "
             + ("numbered folders present" if not missing else "missing " + ", ".join(missing)),
             "error" if paths.PROJECTS in missing else "warning")
        conflicts = paths.conflict_copies(r)
        line(not conflicts, "no sync conflict copies" if not conflicts else
             f"{len(conflicts)} sync conflict copies: " + ", ".join(conflicts[:5]), "warning")
    line(paths.templates_dir(root).is_dir(), f"templates: {paths.TEMPLATES}/", "warning")
    try:
        vault.load_schema()
        line(True, f"schema: {paths.rel(vault.schema_path(), paths.workspace())}")
    except (OSError, ValueError) as e:
        line(False, f"schema: {e}")
    print("== git ==")
    if not shutil.which("git"):
        line(False, "git not installed", "warning")
    else:
        v = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
        line(True, v)
        if root:
            line(vault.Git(root).available, "vault is in a git repository (history, `--apply` safety net)",
                 "warning")
    print(f"# doctor: {len(bad)} problem(s)")
    sys.exit(1 if bad else 0)


# ================================================================ main
def main(argv=None):
    ap = argparse.ArgumentParser(prog="brain", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-cache", action="store_true", help="rebuild without the parse cache")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)

    def w(p):
        p.add_argument("--apply", action="store_true", help="execute (default: dry run with diff)")
        p.add_argument("--allow-dirty", action="store_true",
                       help="--apply even over foreign uncommitted changes (logged as dirty-allowed)")
        return p

    p = sub.add_parser("index", help="graph statistics")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("find", help="filter notes")
    for o in ("type", "kind", "context", "area", "status"):
        p.add_argument(f"--{o}")
    p.add_argument("--text", help="words (stopwords dropped, diacritics ignored, word-start / 5-char stem "
                                  "match); ranked by distinct words hit, title/alias > body, rare words weigh more")
    p.add_argument("--all", action="store_true", help="with --text: also 99_Archives/, vendor docs and "
                                                      "graph:false folders")
    p.add_argument("--limit", type=int, default=30, help="with --text: best N notes (0 = all; default 30)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_find)

    p = sub.add_parser("show", help="frontmatter, outgoing and computed inverse edges")
    p.add_argument("note")
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="list every link, not the first 15")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("related", help="neighbourhood tree grouped by relation")
    p.add_argument("note")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--rel", help="comma list of relations (canonical or inverse names)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_related)

    p = w(sub.add_parser("project", help="render (and --write) the auto:projection block"))
    p.add_argument("target", nargs="?")
    p.add_argument("--write", action="store_true")
    p.add_argument("--all", action="store_true", help="every area hub and every MOC/hub holding the block")
    p.set_defaults(fn=cmd_project)

    p = sub.add_parser("validate", help="schema, relations, links, ids, branch/leaf rule")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="warnings become errors")
    p.add_argument("--all", action="store_true", help="list every issue")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--file", metavar="PATH", help="only this note (+ naming/frontmatter checks); exit 1 on errors")
    p.set_defaults(fn=cmd_validate)

    p = w(sub.add_parser("create", help="new note from template"))
    p.add_argument("type")
    p.add_argument("title")
    for o in ("kind", "context", "area", "project", "slug"):
        p.add_argument(f"--{o}")
    p.add_argument("--namespace", help="knowledge types: 40_Knowledge/<ns>/ (default from --context, else shared)")
    p.add_argument("--topic", help="knowledge types: topic folders below the namespace, e.g. infrastructure/sites")
    p.add_argument("--in", dest="into", metavar="PATH", help="knowledge types: folder below 40_Knowledge/ "
                                                           "(<ns>/<topic>…), overrides --namespace/--topic")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_create)

    p = sub.add_parser("schema", help="type/kind registry: list, add-type, add-kind (schema.json)")
    ss = p.add_subparsers(dest="action", required=True)
    q = ss.add_parser("list", help="types, kinds, labels, note counts, off-schema values seen in the vault")
    q.add_argument("--json", action="store_true")
    q.add_argument("--no-cache", action="store_true")
    q = w(ss.add_parser("add-type", help="register a new type (dry run unless --apply)"))
    q.add_argument("name")
    q.add_argument("--entity", action="store_true", help="entity type (joins the graph relations via @entity); "
                                                         "default structural")
    q.add_argument("--kinds", help="comma list of allowed kinds (empty = any kind)")
    q.add_argument("--label", help="plural label for projections, e.g. \"Sites\"")
    q.add_argument("--required", help="comma list of required frontmatter keys besides id/type/title")
    q = w(ss.add_parser("add-kind", help="register a new kind of an existing type (dry run unless --apply)"))
    q.add_argument("type")
    q.add_argument("kind")
    p.set_defaults(fn=cmd_schema)

    schema = vault.load_schema()
    for name, fn in (("link", cmd_link), ("unlink", cmd_unlink)):
        p = w(sub.add_parser(name, help=f"{name} a typed relation (frontmatter)"))
        p.add_argument("note")
        for rel in schema["relations"]:
            p.add_argument(f"--{rel}", dest=rel, metavar="TARGET")
        p.add_argument("--force", action="store_true", help="ignore type rules (link)")
        p.add_argument("--replace", action="store_true", help="overwrite a single-valued relation (link)")
        p.add_argument("--ended", help="date for the Log line (unlink, default today)")
        p.add_argument("--source", help="source for the Log line (unlink)")
        p.set_defaults(fn=fn)

    p = w(sub.add_parser("move", help="git mv a note into another folder"))
    p.add_argument("note")
    p.add_argument("dest")
    p.set_defaults(fn=cmd_move)

    p = w(sub.add_parser("rename", help="git mv + rewrite [[links]] + keep old name as alias"))
    p.add_argument("note")
    p.add_argument("new")
    p.set_defaults(fn=cmd_rename)

    p = sub.add_parser("doctor", help="generic health checks (python, config, folders, schema, git)")
    p.set_defaults(fn=cmd_doctor)

    p = w(sub.add_parser("migrate", help="ids: backfill id/type frontmatter on every note"))
    p.add_argument("action", choices=["ids"])
    p.add_argument("--limit", type=int, default=10, help="diffs / rows to print in a dry run (0 = all)")
    p.set_defaults(fn=cmd_migrate)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
