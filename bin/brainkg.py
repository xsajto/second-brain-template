#!/usr/bin/env python3
"""brainkg.py - structural CLI of the vault (python3 stdlib only). Usually called as `brain <cmd>`.

Check:     validate [--json] [--strict] [--file PATH]           (exit 1 on errors; includes type-folder-mismatch, context-area-mismatch,
           project-no-area)
Health:    doctor                                               python, config, folders, git, sync conflict copies
Operate:   create <type> "Title" [--namespace NS --topic a/b | --in NS/a/b] · move <note> <dest-dir> · rename <note> "New"
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


def in_archives(r):
    return r.startswith(paths.ARCHIVES + "/")


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
            add("error", "unknown-type", r, f"{n['type']} (not in schema.json; add it to lib/schema.json › types)")
        allowed = sch["kinds"].get(n["type"], [])
        if n["fm"].get("kind") and allowed and n["kind"] not in allowed:
            add("warning", "unknown-kind", r, f"{n['kind']} not in {allowed} (add it to lib/schema.json › kinds)")
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
            add("warning", "project-no-area", r, "no `area:` edge (add `area: \"[[<role>-hub]]\"` to the frontmatter)")
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
        die(f"unknown type {typ}; one of {known} (new type: add it to lib/schema.json › types)")
    kinds = sch["kinds"].get(typ, [])
    if args.kind and kinds and args.kind not in kinds:
        die(f"kind {args.kind} not allowed for {typ}: {kinds} (new kind: add it to lib/schema.json › kinds)")
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
    else:  # system, concept, note, map, any type added to schema.json: 40_Knowledge/<ns>/<topic>/
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

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
