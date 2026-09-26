"""vault.py - shared library for the vault (python3 stdlib only).

  * vault root discovery (paths.find_root)
  * frontmatter: a simple flat parser (frontmatter/as_list/fix_frontmatter/add_tag) and a
    round-trip editor (Frontmatter) that preserves unknown keys, key order, comments and nested blocks
  * wikilink parsing with code masked out, note resolution by id / path / filename / slug / aliases
  * the knowledge graph (Graph.load): nodes + typed edges from frontmatter relations, location, body
    links, auto:links and source:, with computed inverses (schema.json)
  * jsonl logging to 50_Raw/logs/brain/YYYY-MM-DD.jsonl, git helpers (dirty check, git mv) for the git
    repository holding the root (or $BRAIN_GIT_DIR, a separate git dir whose work tree contains the root)

Import:  sys.path.insert(0, "<repo>/lib"); import vault, paths
"""
import datetime as dt
import difflib
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import paths  # noqa: E402

LIB = Path(__file__).resolve().parent
SCHEMA_PATH = LIB / "schema.json"
def cache_path(root):
    """Per-root parse cache: $BRAIN_CACHE, else ~/.cache/brain/graph-<root name>-<sha1(root)[:8]>.json (the two
    roots of a multi-root workspace never share or overwrite one cache)."""
    env = os.environ.get("BRAIN_CACHE")
    if env:
        return Path(env)
    r = str(Path(root).resolve())
    h = hashlib.sha1(r.encode("utf-8")).hexdigest()[:8]
    return Path.home() / ".cache" / "brain" / f"graph-{Path(r).name}-{h}.json"


CACHE_VERSION = 4  # 4: + summary
# sha256 of every file brain wrote (abs path -> hash): lets --apply tell brain's own uncommitted edits
# from foreign ones (Changes.apply). Outside the vault, never synced.
WRITTEN_PATH = Path(os.environ.get("BRAIN_WRITTEN", Path.home() / ".cache" / "brain" / "written.json"))
TODAY = dt.date.today()

# ---------------------------------------------------------------- regexes
FM_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n", re.S)
FM2_RE = re.compile(r"\A(---[ \t]*\n)(?:(.*?)\n)?(---[ \t]*(?:\n|\Z))", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]\|#\^]+)(?:[#\^][^\]\|]*)?(?:\|[^\]]*)?\]\]")
LINK_RE = re.compile(r"\[\[([^\]\|#\^\n]+)((?:[#\^][^\]\|\n]*)?)((?:\|[^\]\n]*)?)\]\]")
LINKS_BLOCK_RE = re.compile(r"\n?<!-- auto:links start -->.*?<!-- auto:links end -->\n?", re.S)
AUTO_LINKS_INNER_RE = re.compile(r"<!-- auto:links start -->(.*?)<!-- auto:links end -->", re.S)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
KEY_RE = re.compile(r"^([A-Za-z_][\w.-]*)[ \t]*:(?:[ \t]+|$)(.*)$")


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".brain-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    remember_written(path)


def sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _written_key(path):
    return nfc(str(Path(path).resolve()))


def load_written():
    try:
        d = json.loads(WRITTEN_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def remember_written(path):
    """Record the current sha256 of `path` as the last content brain wrote there."""
    h = sha256_file(path)
    if not h:
        return
    d = load_written()
    d[_written_key(path)] = {"sha256": h, "ts": dt.datetime.now().isoformat(timespec="seconds")}
    try:
        WRITTEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = WRITTEN_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=0), encoding="utf-8")
        os.replace(tmp, WRITTEN_PATH)
    except OSError:
        pass


def written_by_brain(path, written=None):
    """True when the file's current content is exactly what brain last wrote there."""
    rec = (written if written is not None else load_written()).get(_written_key(path))
    return bool(rec) and rec.get("sha256") == sha256_file(path)


def root(start=None):
    return paths.find_root(start)


def schema_path():
    """schema.json in use: $BRAIN_SCHEMA (tests, a fixture vault) or lib/schema.json."""
    return Path(os.environ.get("BRAIN_SCHEMA") or SCHEMA_PATH)


def load_schema_raw(path=None):
    """schema.json exactly as stored (wildcards such as "@entity" unexpanded) — for `brain schema` edits."""
    return json.loads(Path(path or schema_path()).read_text(encoding="utf-8"), object_pairs_hook=dict)


# placeholders in schema.json strings: `{{people}}`, `{{decisions}}` … -> the configured folder names
# (regex-escaped inside `inference` regexes, plain elsewhere)
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def folder_values(cfg=None):
    """Placeholder -> folder name/path from the config (`folders` + shared_namespace)."""
    cfg = cfg or config.CONFIG
    return {**cfg["folders"], "shared_namespace": cfg["shared_namespace"]}


def fill_placeholders(s, values, regex=False):
    def sub(m):
        if m.group(1) not in values:
            return m.group(0)
        v = str(values[m.group(1)])
        return re.escape(v) if regex else v
    return PLACEHOLDER_RE.sub(sub, s)


def expand_schema(raw, cfg=None):
    """Schema ready for use: relation `from`/`to` wildcards resolved ("@entity" -> every type in types.entity,
    "@structural" -> types.structural; "*" stays "*"), order kept, duplicates dropped; `{{folder}}` placeholders
    filled from the config; config `labels` and `companions` merged in. `raw` is not modified."""
    cfg = cfg or config.CONFIG
    sch = json.loads(json.dumps(raw))
    vals = folder_values(cfg)
    for rule in sch.get("inference", []):
        for k in ("regex", "glob"):
            if k in rule:
                rule[k] = fill_placeholders(rule[k], vals, regex=(k == "regex"))
    comp = sch.setdefault("companions", {"names": [], "globs": []})
    comp["names"] = [fill_placeholders(n, vals) for n in comp.get("names", [])] + \
        [n for n in cfg.get("companions", []) if n not in comp.get("names", [])]
    sch["labels"] = {**(sch.get("labels") or {}), **(cfg.get("labels") or {})}
    groups = {"@" + k: v for k, v in sch.get("types", {}).items()}
    for spec in sch.get("relations", {}).values():
        for side in ("from", "to"):
            out = []
            for t in spec.get(side, []):
                for x in groups.get(t, [t]):
                    if x not in out:
                        out.append(x)
            spec[side] = out
    return sch


def load_schema(path=None):
    return expand_schema(load_schema_raw(path))


def dump_schema(raw):
    """schema.json text in the file's house style: top-level keys one per line (2-space indent); second-level
    objects one key per line (inline values, aligned when every value is an object), second-level lists of
    objects one item per line; everything deeper inline."""
    inline = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    out = ["{"]
    items = list(raw.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if isinstance(v, dict) and v:
            sub = list(v.items())
            pad = max(len(inline(sk)) + 1 for sk, _ in sub) if all(isinstance(sv, dict) for _, sv in sub) else 0
            out.append(f"  {inline(k)}: {{")
            for j, (sk, sv) in enumerate(sub):
                key = (inline(sk) + ":").ljust(pad) if pad else inline(sk) + ":"
                out.append(f"    {key} {inline(sv)}" + ("," if j < len(sub) - 1 else ""))
            out.append("  }" + comma)
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            out.append(f"  {inline(k)}: [")
            out += [f"    {inline(x)}" + ("," if j < len(v) - 1 else "") for j, x in enumerate(v)]
            out.append("  ]" + comma)
        else:
            out.append(f"  {inline(k)}: {inline(v)}{comma}")
    return "\n".join(out + ["}"]) + "\n"


KNOWLEDGE_DEFAULTS = {"root": paths.KNOWLEDGE, "max_depth": 6,
                      "split_threshold": 15, "cluster_threshold": 5, "namespace_threshold": 3,
                      "hub_min_notes": 10, "hub_min_subdirs": 2, "list_max": 25}


def knowledge_cfg(schema, cfg=None):
    """schema["knowledge"] thresholds with defaults, plus the config-driven parts: registries (folder name ->
    fixed type), shared namespace, context -> namespace, flat folders."""
    cfg = cfg or config.CONFIG
    out = {**KNOWLEDGE_DEFAULTS, **(schema.get("knowledge") or {})}
    root = out["root"] + "/"
    out["registries"] = {d[len(root):]: t for d, t in ((paths.PEOPLE_DIR, "person"), (paths.ORGS_DIR, "org"))
                         if d.startswith(root)}
    out["shared_namespace"] = cfg["shared_namespace"]
    out["context_namespaces"] = {**{c: s["namespace"] for c, s in cfg["contexts"].items()},
                                 "shared": cfg["shared_namespace"]}
    out["flat"] = list(cfg.get("flat_knowledge") or [])
    return out


def type_label(schema, typ):
    """Plural label of a type for projections (schema["labels"] + config labels), else the type name."""
    return (schema.get("labels") or {}).get(typ) or typ


def all_types(schema):
    return [t for group in schema["types"].values() for t in group]


def namespace_context(schema, ns):
    """Context of a Knowledge namespace (reverse of knowledge.context_namespaces) when it is a real context."""
    rev = {v: k for k, v in knowledge_cfg(schema)["context_namespaces"].items()}
    ctx = rev.get(ns)
    return ctx if ctx in paths.CONTEXTS else None


def days_since(s, today=None):
    m = DATE_RE.search(s or "")
    if not m:
        return None
    try:
        return ((today or TODAY) - dt.date.fromisoformat(m.group(0))).days
    except ValueError:
        return None


def slugify(s, maxlen=80):
    """ASCII kebab-case: 'Ada Example' -> 'ada-example', 'Acme — CRM' -> 'acme-crm'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen].rstrip("-") or "x"


# ---------------------------------------------------------------- flat frontmatter API
def frontmatter(text):
    """Flat key -> raw string (comments stripped). Returns ({}, None) when there is no frontmatter."""
    m = FM_RE.match(text or "")
    if not m:
        return {}, None
    fm, key = {}, None
    for ln in m.group(1).splitlines():
        km = re.match(r"^([\w.-]+):\s*(.*?)\s*$", ln)
        if km:
            key = km.group(1)
            fm[key] = re.sub(r"\s+#.*$", "", km.group(2)).strip()
            continue
        im = re.match(r"^[ \t]+-\s*(.*?)\s*$", ln)
        if im and key is not None:
            item = re.sub(r"\s+#.*$", "", im.group(1)).strip().strip("\"'")
            fm[key] = "[" + item + "]" if not fm[key] else fm[key][:-1] + ", " + item + "]"
    return fm, m


def as_list(raw):
    if isinstance(raw, list):
        return [str(x) for x in raw]
    raw = (raw or "").strip()
    if raw.startswith("[") and raw.endswith("]") and not (raw.startswith("[[") and raw.endswith("]]") and raw.count("[[") == 1):
        raw = raw[1:-1]
    return [x.strip().strip("\"'") for x in _split_flow(raw) if x.strip()]


def fix_frontmatter(text, m, key, value):
    block = m.group(1)
    if re.search(rf"^{key}:", block, re.M):
        block = re.sub(rf"^{key}:.*$", f"{key}: {value}", block, count=1, flags=re.M)
    elif re.search(r"^title:", block, re.M):
        block = re.sub(r"^(title:.*)$", rf"\1\n{key}: {value}", block, count=1, flags=re.M)
    else:
        block = f"{key}: {value}\n" + block
    return text[:m.start(1)] + block + text[m.end(1):]


def add_tag(text, tag):
    fm, m = frontmatter(text)
    block = m.group(1)
    tm = re.search(r"^tags:\s*\[(.*?)\]\s*$", block, re.M)
    if tm:
        items = as_list("[" + tm.group(1) + "]") + [tag]
        block = block[:tm.start()] + "tags: [" + ", ".join(items) + "]" + block[tm.end():]
    elif re.search(r"^tags:", block, re.M):
        block = re.sub(r"^(tags:.*(?:\n[ \t]+-.*)*)$", rf"\1\n  - {tag}", block, count=1, flags=re.M)
    else:
        block = block + f"\ntags: [{tag}]"
    return text[:m.start(1)] + block + text[m.end(1):]


def section(text, title_re):
    m = re.search(r"^## [^\n]*" + title_re + r"[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- round-trip frontmatter
def _split_flow(s):
    """Split a flow-list interior on commas outside quotes and [[ ]]."""
    out, cur, depth, q = [], "", 0, None
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            cur += c
            if c == "\\" and q == '"' and i + 1 < len(s):
                cur += s[i + 1]
                i += 1
            elif c == q:
                q = None
        elif c in "\"'":
            q = c
            cur += c
        elif c == "[":
            depth += 1
            cur += c
        elif c == "]":
            depth -= 1
            cur += c
        elif c == "," and depth <= 0:
            out.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip():
        out.append(cur)
    return out


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return re.sub(r'\\(["\\])', r"\1", v[1:-1])
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def _strip_comment(v):
    v = v.strip()
    if v and v[0] in "\"'":
        q = v[0]
        end = v.find(q, 1)
        while q == '"' and end > 0 and v[end - 1] == "\\":
            end = v.find(q, end + 1)
        if end > 0:
            return v[:end + 1]
    return re.sub(r"(^|\s+)#.*$", "", v).strip()


def _scalar(v):
    v = _strip_comment(v)
    if v in ("", "~", "null"):
        return ""
    return _unquote(v)


def _needs_quote(s):
    return (s == "" or "[[" in s or ": " in s or " #" in s or s[0] in "[]{}>|*&!%@#`'\",?-" and s not in ("-",)
            or s.strip() != s or s.lower() in ("true", "false", "yes", "no", "null", "~"))


def yaml_scalar(s):
    s = str(s)
    if _needs_quote(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


class Frontmatter:
    """Line-preserving frontmatter editor. Only keys you set/remove change; everything else (unknown keys,
    order, comments, nested blocks such as `meeting:`) is kept byte-for-byte."""

    def __init__(self, text):
        self.text = text or ""
        m = FM2_RE.match(self.text)
        self.present = bool(m)
        if m:
            self.open, block, self.close = m.group(1), m.group(2), m.group(3)
            self.body = self.text[m.end():]
            lines = block.split("\n") if block is not None else []
        else:
            self.open, self.close, self.body, lines = "---\n", "---\n", self.text, []
        self.entries = []  # [key or None, [lines]]
        for ln in lines:
            km = KEY_RE.match(ln)
            if km and not ln[:1].isspace():
                self.entries.append([km.group(1), [ln]])
            elif self.entries:
                self.entries[-1][1].append(ln)
            else:
                self.entries.append([None, [ln]])

    # -- read
    def keys(self):
        return [k for k, _ in self.entries if k]

    def _entry(self, key):
        for e in self.entries:
            if e[0] == key:
                return e
        return None

    def __contains__(self, key):
        return self._entry(key) is not None

    def raw(self, key):
        e = self._entry(key)
        return "\n".join(e[1]) if e else None

    def style(self, key):
        e = self._entry(key)
        if not e:
            return None
        first = KEY_RE.match(e[1][0]).group(2).strip()
        cont = [ln for ln in e[1][1:] if ln.strip() and not ln.strip().startswith("#")]
        if not _strip_comment(first) and cont and all(re.match(r"^\s*-\s", ln) or ln.strip() == "-" for ln in cont):
            return "block"
        if _strip_comment(first).startswith("[") and not _strip_comment(first).startswith("[["):
            return "flow"
        if cont and not _strip_comment(first):
            return "nested"
        return "scalar"

    def get(self, key, default=None):
        """str for scalars, list[str] for flow/block lists, {"_raw": text} for nested blocks."""
        e = self._entry(key)
        if not e:
            return default
        first = KEY_RE.match(e[1][0]).group(2)
        v = _strip_comment(first)
        cont = [ln for ln in e[1][1:] if ln.strip() and not ln.strip().startswith("#")]
        if v in ("|", ">", "|-", ">-", "|+", ">+"):
            return ("\n" if v[0] == "|" else " ").join(ln.strip() for ln in cont)
        if not v:
            if not cont:
                return ""
            if all(re.match(r"^\s*-(\s|$)", ln) for ln in cont):
                items = [re.sub(r"^\s*-\s?", "", ln) for ln in cont]
                if all(not KEY_RE.match(i.strip()) for i in items):
                    return [_scalar(i) for i in items if _scalar(i) != ""]
            return {"_raw": "\n".join(e[1][1:])}
        if v.startswith("[[") and v.endswith("]]") and v.count("[[") == 1:
            return v  # unquoted single wikilink (YAML would read a nested list; Obsidian users mean a link)
        if v.startswith("[") and v.endswith("]"):
            return [_unquote(x) for x in _split_flow(v[1:-1]) if _unquote(x) != ""]
        return _unquote(v)

    def as_dict(self):
        return {k: self.get(k) for k in self.keys()}

    # -- write
    def _render(self, key, value, old_lines=None, style=None):
        comment = ""
        if old_lines:
            cm = re.search(r"(\s+#[^\"']*)$", old_lines[0])
            if cm and not isinstance(value, list) and style == "scalar":
                comment = cm.group(1)
        if value is None or value == "":
            return [f"{key}:{comment}"]
        if isinstance(value, (list, tuple)):
            if style == "block":
                indent = "  "
                if old_lines and len(old_lines) > 1:
                    im = re.match(r"^(\s*)-", old_lines[1])
                    indent = im.group(1) if im else indent
                return [f"{key}:"] + [f"{indent}- {yaml_scalar(v)}" for v in value] if value else [f"{key}: []"]
            return [f"{key}: [" + ", ".join(yaml_scalar(v) for v in value) + "]"]
        return [f"{key}: {yaml_scalar(value)}{comment}"]

    def set(self, key, value, after=None, first=False, style=None):
        e = self._entry(key)
        if e:
            st = style or self.style(key)
            if st == "nested":
                st = "block" if isinstance(value, list) else "scalar"
            e[1] = self._render(key, value, e[1], st)
            return self
        lines = self._render(key, value, None, style)
        idx = len(self.entries)
        if first:
            idx = 0
            while idx < len(self.entries) and self.entries[idx][0] is None:
                idx += 1  # keep leading comments on top
        elif after:
            for a in ([after] if isinstance(after, str) else after):
                for i, (k, _) in enumerate(self.entries):
                    if k == a:
                        idx = i + 1
                        break
                else:
                    continue
                break
        self.entries.insert(idx, [key, lines])
        return self

    def remove(self, key):
        self.entries = [e for e in self.entries if e[0] != key]
        return self

    def render(self):
        lines = [ln for _, ls in self.entries for ln in ls]
        if not self.present and not lines:
            return self.body
        block = "\n".join(lines)
        close = self.close if self.close.endswith("\n") or self.body or self.present else self.close + "\n"
        return self.open + (block + "\n" if lines else "") + close + self.body


# ---------------------------------------------------------------- wikilinks
def mask_code(text):
    """Replace fenced and inline code with spaces (offsets and newlines preserved)."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    text = re.sub(r"```.*?```", blank, text, flags=re.S)
    return re.sub(r"`[^`\n]*`", blank, text)


def parse_links(text, masked=None):
    """[(target, anchor, alias, start, end, escaped_pipe, tstart, tend)] for every [[...]] outside code.
    target is NFC with a trailing `\\` (escaped table pipe) removed; tstart/tend = span of the target text
    in the original string (for in-place rewriting)."""
    masked = mask_code(text) if masked is None else masked
    out = []
    for m in LINK_RE.finditer(masked):
        raw = text[m.start():m.end()]
        mm = LINK_RE.match(raw)
        if not mm:
            continue
        g1 = mm.group(1)
        core = g1.rstrip()
        esc = core.endswith("\\")
        core = core.rstrip("\\").rstrip()
        lead = len(g1) - len(g1.lstrip())
        tstart = m.start() + 2 + lead
        tend = m.start() + 2 + len(core)
        target = nfc(core.strip())
        anchor = mm.group(2).rstrip("\\") if mm.group(2) else ""
        alias = mm.group(3)[1:] if mm.group(3) else ""
        out.append((target, anchor, alias, m.start(), m.end(), esc, tstart, tend))
    return out


def link_targets(value):
    """Wikilink targets inside a frontmatter value (str or list)."""
    vals = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    out = []
    for v in vals:
        out += [t for t, *_ in parse_links(str(v), masked=str(v))]
    return out


def strip_ext(t):
    return t[:-3] if t.lower().endswith(".md") else t


def name_key(rel):
    """What a bare wikilink uses for a file: the stem for notes, the full name for attachments."""
    p = Path(rel)
    return p.stem if p.suffix == ".md" else p.name


# ---------------------------------------------------------------- resolver
class Resolver:
    """Resolve a reference (id, vault path, filename, `slug/CLAUDE`, project slug, alias, title) to a
    vault-relative path. Ambiguous filenames prefer the source note's folder, then the shortest path."""

    def __init__(self, files, notes=None):
        self.files = set(files)
        self.by_stem, self.by_stem_ci, self.by_path, self.by_id, self.by_alias, self.by_slug = {}, {}, {}, {}, {}, {}
        self.by_title = {}
        for f in sorted(self.files):
            p = Path(f)
            stem = p.stem if p.suffix == ".md" else p.name
            self.by_stem.setdefault(stem, []).append(f)
            self.by_stem_ci.setdefault(stem.casefold(), []).append(f)
            self.by_path[strip_ext(f) if f.endswith(".md") else f] = f
            self.by_path[f] = f
            if p.name == "CLAUDE.md" and len(p.parts) == 3 and p.parts[0] in (paths.PROJECTS, paths.ARCHIVES):
                self.by_slug[p.parts[1]] = f
        for r, n in (notes or {}).items():
            if n.get("id"):
                self.by_id.setdefault(n["id"], []).append(r)
            for a in n.get("aliases") or []:
                self.by_alias.setdefault(nfc(a).casefold(), []).append(r)
            t = n.get("title")
            if t:
                self.by_title.setdefault(nfc(t).casefold(), []).append(r)

    @staticmethod
    def clean(ref):
        ref = nfc(str(ref)).strip().strip("\"'")
        m = LINK_RE.fullmatch(ref) if ref.startswith("[[") else None
        if m:
            ref = m.group(1).rstrip("\\").strip()
        return ref

    def _pick(self, cands, src):
        if not cands:
            return None
        if len(cands) == 1 or not src:
            return sorted(cands, key=lambda c: (len(Path(c).parts), c))[0]
        folder = str(Path(src).parent)
        same = [c for c in cands if str(Path(c).parent) == folder]
        return (same or sorted(cands, key=lambda c: (len(Path(c).parts), c)))[0]

    def candidates(self, ref):
        ref = self.clean(ref)
        if not ref:
            return []
        if ref in self.by_id:
            return self.by_id[ref]
        base = strip_ext(ref)
        if base in self.by_path and self.by_path[base] in self.files:
            return [self.by_path[base]]
        if ref in self.by_path:
            return [self.by_path[ref]]
        if "/" not in base and base in self.by_stem:
            return self.by_stem[base]
        if "/" not in ref and ref in self.by_stem:  # attachments: [[file.pdf]]
            return self.by_stem[ref]
        if "/" in base:
            suf = [f for f in self.files if strip_ext(f).endswith("/" + base) or f.endswith("/" + ref)]
            if suf:
                return suf
            slug, _, rest = base.partition("/")
            if rest == "CLAUDE" and slug in self.by_slug:
                return [self.by_slug[slug]]
        if base in self.by_slug:
            return [self.by_slug[base]]
        if "/" in base and base.rsplit("/", 1)[1] in self.by_stem:  # stale folder prefix
            return self.by_stem[base.rsplit("/", 1)[1]]
        key = base.casefold()
        for table in (self.by_alias, self.by_stem_ci, self.by_title):
            if key in table:
                return table[key]
        return []

    def resolve(self, ref, src=None):
        return self._pick(self.candidates(ref), src)


class ExternalNames:
    """Names-only index of files outside this root (sibling roots of a multi-root workspace + the workspace's
    docs/): lets validate tell a cross-root link from a broken one. Entries are (display, rel-in-its-root)
    where display is workspace-relative (`home/20_Projects/priv-x/CLAUDE.md`, `docs/routines.md`)."""

    def __init__(self, entries):
        self.by_stem, self.by_stem_ci, self.by_path, self.by_slug = {}, {}, {}, {}
        self.rels = []
        for display, r in entries:
            p = Path(r)
            stem = p.stem if p.suffix == ".md" else p.name
            self.by_stem.setdefault(stem, []).append(display)
            self.by_stem_ci.setdefault(stem.casefold(), []).append(display)
            for key in (r, strip_ext(r), display, strip_ext(display)):
                self.by_path.setdefault(key, display)
            self.rels.append((display, r))
            if p.name == "CLAUDE.md" and len(p.parts) == 3 and p.parts[0] in (paths.PROJECTS, paths.ARCHIVES):
                self.by_slug.setdefault(p.parts[1], display)

    @classmethod
    def for_root(cls, root):
        root = Path(root).resolve()
        entries = []
        ws = paths.workspace().resolve()
        bases = [(d, paths.rel(d, ws) + "/") for d in paths.sibling_roots(root)]
        sysdir = ws / paths.SYSTEM
        if sysdir.is_dir() and ws != root and not (root / paths.SYSTEM).is_dir():
            bases.append((sysdir, paths.SYSTEM + "/"))
        for base, prefix in bases:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in paths.SKIP_PARTS]
                rd = paths.rel(dirpath, base)
                for f in filenames:
                    if f.startswith("."):
                        continue
                    r = nfc(f"{rd}/{f}" if rd != "." else f)
                    in_root = f"{paths.SYSTEM}/{r}" if base == sysdir else r
                    entries.append((nfc(prefix + r), in_root))
        return cls(entries)

    def lookup(self, ref):
        """Workspace-relative path of the external file a reference points to, or None."""
        ref = Resolver.clean(ref)
        if not ref:
            return None
        base = strip_ext(ref)
        if "/" not in base:
            hit = self.by_stem.get(base) or self.by_stem.get(ref) or self.by_stem_ci.get(base.casefold())
            return sorted(hit)[0] if hit else self.by_slug.get(base)
        if base in self.by_path or ref in self.by_path:
            return self.by_path.get(base) or self.by_path.get(ref)
        suf = sorted(d for d, r in self.rels if strip_ext(r).endswith("/" + base) or strip_ext(d).endswith("/" + base))
        if suf:
            return suf[0]
        slug, _, rest = base.partition("/")
        if rest == "CLAUDE" and slug in self.by_slug:
            return self.by_slug[slug]
        last = base.rsplit("/", 1)[1]
        hit = self.by_stem.get(last)
        return sorted(hit)[0] if hit else None


# ---------------------------------------------------------------- note parsing + graph
SUMMARY_LEN = 100
_SKIP_LINE_RE = re.compile(r"^(#|>|\||<!--|-->|---|```|\*\*\*|!\[|\^f-)")


def plain(s):
    """Markdown line -> plain text: [[t|Label]] -> Label, [x](url) -> x, **b**/`c` markers dropped, ^f- ids out."""
    s = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]#^]*)[^\]]*\]\]", lambda m: Path(m.group(1)).name, s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\s\^f-[0-9a-z]+\s*$", "", s)
    s = re.sub(r"<!--.*?-->", "", s)
    s = s.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def shorten(s, n=SUMMARY_LEN):
    s = s.strip()
    if len(s) <= n:
        return s
    cut = s[:n + 1].rsplit(" ", 1)[0].rstrip(" ,;:—–-")
    return (cut if len(cut) > n // 2 else s[:n]) + "…"


def note_summary(fm, body, n=SUMMARY_LEN):
    """One-line summary: frontmatter `description` / `summary`, else the first meaningful body sentence
    (headings, quotes, tables, comments, code, managed-block markers and empty checkboxes skipped)."""
    for k in ("description", "summary"):
        v = fm.get(k)
        if isinstance(v, str) and v.strip():
            return shorten(plain(v), n)
    in_code = False
    for ln in (body or "").splitlines():
        s = ln.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s or _SKIP_LINE_RE.match(s):
            continue
        s = re.sub(r"^(?:[-*+]|\d+\.)\s+(?:\[[ xX]\]\s*)?", "", s)
        t = plain(s)
        if len(t) < 3 or not re.search(r"\w", t):
            continue
        for m in re.finditer(r"(?<=[.!?])\s+(?=\w)", t[12:]):  # sentence end: next word starts uppercase
            if t[12 + m.end()].isupper():
                t = t[:12 + m.start()]
                break
        return shorten(t, n)
    return ""


def note_meta(rel, text, mtime=0, size=0):
    """JSON-able summary of one note used by the graph (and cached)."""
    fmo = Frontmatter(text)
    fm = fmo.as_dict()
    body = fmo.body
    masked = mask_code(body)
    auto = [(m.start(1), m.end(1)) for m in AUTO_LINKS_INNER_RE.finditer(masked)]
    links, mentions = [], []
    for t, anchor, alias, s, e, *_ in parse_links(body, masked):
        (mentions if any(a <= s < b for a, b in auto) else links).append(t)
    tags = [nfc(t).lstrip("#") for t in (fm.get("tags") if isinstance(fm.get("tags"), list)
                                         else as_list(fm.get("tags") or ""))]
    aliases = fm.get("aliases")
    aliases = aliases if isinstance(aliases, list) else as_list(aliases) if aliases else []
    return {"rel": rel, "stem": Path(rel).stem, "has_fm": fmo.present, "fm": fm, "keys": fmo.keys(),
            "title": nfc(str(fm.get("title") or "")).strip() or Path(rel).stem, "tags": tags,
            "aliases": [nfc(a) for a in aliases], "id": nfc(str(fm.get("id") or "")),
            "links": links, "mentions": mentions, "mtime": mtime, "size": size,
            "summary": note_summary(fm, body),
            "graph": str(fm.get("graph", "")).lower() not in ("false", "no", "0")}


def _in_project(rel):
    parts = Path(rel).parts
    return len(parts) >= 3 and parts[0] in (paths.PROJECTS, paths.ARCHIVES) and bool(paths.SLUG_RE.match(parts[1]))


def infer_type(rel, tags, schema):
    """(type, kind) from folder + tags per schema.inference. The `project` tag on a note inside a
    project folder means "belongs to the project", not "is a project"."""
    tagset = {t.split("/")[-1] if t.startswith("type/") else t for t in tags}
    if _in_project(rel):
        tagset.discard("project")
    for rule in schema["inference"]:
        how = rule["match"]
        if how == "path":
            if "glob" in rule and fnmatch.fnmatch(rel, rule["glob"]):
                return rule["type"], rule.get("kind")
            if "regex" in rule and re.search(rule["regex"], rel):
                return rule["type"], rule.get("kind")
        elif how == "tags":
            for tag, typ in schema["type_tags"].items():
                if tag in tagset:  # a tag that is also a kind of its type sets the kind (idea -> note/idea)
                    return typ, (tag if tag in schema["kinds"].get(typ, []) else None)
        elif how == "default":
            return rule["type"], rule.get("kind")
    return "note", None


def tag_types(tags, schema, rel=""):
    skip = {"project"} if rel and _in_project(rel) and Path(rel).name != "CLAUDE.md" else set()
    return {schema["type_tags"][t] for t in tags if t in schema["type_tags"] and t not in skip}


class Graph:
    """Knowledge graph built from Markdown. nodes: rel -> meta (+type/kind/id_explicit);
    edges: dicts {src, rel, dst, origin, raw}; unresolved: relation values that did not resolve."""

    def __init__(self, root, schema=None):
        self.root = Path(root)
        self.schema = schema or load_schema()
        self.rels = self.schema["relations"]
        self.inverse = {k: v["inverse"] for k, v in self.rels.items()}
        self.inverse.update({k: v["inverse"] for k, v in self.schema["index_edges"].items()})
        self.nodes, self.edges, self.unresolved, self.skipped = {}, [], [], []
        self.all_files, self.metas = [], {}
        self._out, self._in = {}, {}
        self._external = None

    @property
    def external_names(self):
        """ExternalNames of sibling roots + workspace docs (built lazily, names only)."""
        if self._external is None:
            self._external = ExternalNames.for_root(self.root)
        return self._external

    def external(self, ref):
        """Workspace-relative path when `ref` does not resolve here but names a file in a sibling root or the
        workspace's docs/; else None."""
        return self.external_names.lookup(ref)

    # -- loading
    @classmethod
    def load(cls, root=None, use_cache=True):
        g = cls(root or paths.find_root())
        g._scan(use_cache and not os.environ.get("BRAIN_NO_CACHE"))
        g._build()
        return g

    def _scan(self, use_cache):
        cache = {}
        CACHE_PATH = cache_path(self.root)  # noqa: N806 (per root)
        if use_cache and CACHE_PATH.exists():
            try:
                c = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                if c.get("version") == CACHE_VERSION and c.get("root") == str(self.root):
                    cache = c.get("files", {})
            except (OSError, ValueError):
                cache = {}
        files = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            rd = paths.rel(dirpath, self.root)
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in paths.SKIP_PARTS)
            for f in filenames:
                if not f.startswith(".") and not f.endswith((".brain-tmp", ".pyc")):
                    files.append(nfc(f"{rd}/{f}" if rd != "." else f))
        self.all_files = sorted(files)
        new_cache, changed = {}, False
        for r in self.all_files:
            if not r.endswith(".md") or paths.is_skipped(r):
                continue
            p = self.root / r
            try:
                st = p.stat()
            except OSError:
                continue
            hit = cache.get(r)
            if hit and hit["mtime"] == st.st_mtime_ns and hit["size"] == st.st_size:
                meta = hit
            else:
                meta = note_meta(r, read(p) or "", st.st_mtime_ns, st.st_size)
                changed = True
            new_cache[r] = meta
            self.metas[r] = meta
        if use_cache and (changed or len(new_cache) != len(cache)):
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp = CACHE_PATH.with_suffix(".tmp")
                tmp.write_text(json.dumps({"version": CACHE_VERSION, "root": str(self.root), "files": new_cache},
                                          ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, CACHE_PATH)
            except OSError:
                pass

    def _build(self):
        off_dirs = [str(Path(r).parent) for r, m in self.metas.items() if Path(r).name == "README.md" and not m["graph"]]
        for r, m in self.metas.items():
            if not m["graph"] or any(r.startswith(d + "/") for d in off_dirs if d != "."):
                self.skipped.append(r)
                continue
            n = dict(m)
            ftype = nfc(str(m["fm"].get("type") or "")).strip()
            itype, ikind = infer_type(r, m["tags"], self.schema)
            n["type"] = ftype or itype
            n["type_explicit"] = bool(ftype)
            n["kind"] = nfc(str(m["fm"].get("kind") or "")) or ikind or ""
            self.nodes[r] = n
        self.resolver = Resolver(self.all_files, self.nodes)
        legacy = set(self.schema.get("legacy_relation_strings", []))
        for r, n in self.nodes.items():
            fm = n["fm"]
            explicit_project = False
            for key in self.rels:
                if key not in fm:
                    continue
                val = fm[key]
                if isinstance(val, dict):
                    continue
                vals = val if isinstance(val, list) else [val] if val else []
                for v in vals:
                    v = nfc(str(v)).strip()
                    if not v:
                        continue
                    targets = link_targets(v)
                    origin = "fm"
                    if not targets:
                        if key not in legacy:
                            self.unresolved.append({"src": r, "rel": key, "raw": v, "origin": "fm-string"})
                            continue
                        targets, origin = [v], "fm-string"
                    for t in targets:
                        dst = self.resolver.resolve(t, r)
                        if dst and dst in self.nodes and dst != r:
                            self._add(r, key, dst, origin, v)
                            explicit_project |= key == "project"
                        elif not dst or dst not in self.nodes:
                            self.unresolved.append({"src": r, "rel": key, "raw": v, "origin": origin,
                                                    "found": dst or ""})
            parts = Path(r).parts
            if not explicit_project and len(parts) >= 3 and parts[0] in (paths.PROJECTS, paths.ARCHIVES) \
                    and parts[-1] != "CLAUDE.md":
                dst = f"{parts[0]}/{parts[1]}/CLAUDE.md"
                if dst in self.nodes:
                    self._add(r, "project", dst, "location", "")
            if len(parts) >= 3 and parts[0] == paths.AREAS and "area" not in fm:
                dst = paths.rel(paths.area_hub(self.root / parts[0] / parts[1]), self.root)  # the area note = its hub
                if dst in self.nodes and dst != r:
                    self._add(r, "area", dst, "location", "")
            for kind, lst in (("links_to", n["links"]), ("mentions", n["mentions"])):
                seen = set()
                for t in lst:
                    dst = self.resolver.resolve(t, r)
                    if dst and dst in self.nodes and dst != r and dst not in seen:
                        seen.add(dst)
                        self._add(r, kind, dst, "body" if kind == "links_to" else "auto:links", t)
            for t in link_targets(fm.get("source")):
                dst = self.resolver.resolve(t, r)
                if dst and dst in self.nodes and dst != r:
                    self._add(r, "provenance", dst, "fm", t)

    def _add(self, src, rel, dst, origin, raw):
        e = {"src": src, "rel": rel, "dst": dst, "origin": origin, "raw": raw}
        self.edges.append(e)
        self._out.setdefault(src, []).append(e)
        self._in.setdefault(dst, []).append(e)

    # -- queries
    def out(self, r, rels=None):
        return [e for e in self._out.get(r, []) if not rels or e["rel"] in rels]

    def inc(self, r, rels=None):
        return [e for e in self._in.get(r, []) if not rels or e["rel"] in rels]

    def neighbors(self, r, rels=None):
        """[(label, other, edge, direction)] with inverse labels for incoming edges."""
        out = []
        for e in self._out.get(r, []):
            if not rels or e["rel"] in rels:
                out.append((e["rel"], e["dst"], e, "out"))
        for e in self._in.get(r, []):
            label = self.inverse.get(e["rel"], e["rel"] + "_of")
            if not rels or e["rel"] in rels or label in rels:
                out.append((label, e["src"], e, "in"))
        return out

    def resolve(self, ref, src=None):
        """Resolve a CLI argument: note ref, vault path, directory (-> its CLAUDE.md / hub)."""
        ref = nfc(str(ref)).strip()
        p = Path(ref)
        if p.is_absolute():
            ref = paths.rel(p, self.root)
        ref = ref.rstrip("/")
        if (self.root / ref).is_dir():
            for cand in (f"{ref}/CLAUDE.md", paths.rel(paths.area_hub(self.root / ref), self.root)):  # project / area
                if cand in self.nodes:
                    return cand
        hit = self.resolver.resolve(ref, src)
        return hit if hit in self.nodes else None

    def link_for(self, r):
        """Shortest unambiguous wikilink target for a note (`slug/CLAUDE` for project CLAUDE.md)."""
        p = Path(r)
        if p.name == "CLAUDE.md" and len(p.parts) >= 2:
            return f"{p.parts[-2]}/CLAUDE"
        stem = p.stem
        return stem if len(self.resolver.by_stem.get(stem, [])) == 1 else strip_ext(r)

    def wikilink(self, r, label=True):
        """`[[target|Title]]` (file names are kebab, the human name is the label) or `[[target]]` when the
        title equals the target."""
        t = self.link_for(r)
        n = self.nodes.get(r, {})
        if label and n.get("title") and n["title"] != t:
            return f"[[{t}|{n['title']}]]"
        return f"[[{t}]]"


def is_companion(name, schema):
    c = schema.get("companions") or {"names": [], "globs": []}
    return name in c["names"] or any(fnmatch.fnmatch(name, pat) for pat in c["globs"])


def is_folder_hub(rel, typ=None):
    """True for a folder hub: `<folder>-hub.md` (also `<prefix>-<folder>[-N]-hub.md`, the forms new hubs get on a
    stem collision) or any `*-hub.md` of type map. A note that merely ends in `-hub` (repo `infra/mcp-hub` ->
    `repo-infra-mcp-hub.md`, type system) is an ordinary note."""
    p = Path(nfc(str(rel)))
    if not paths.is_hub(p.name):
        return False
    if typ == "map":
        return True
    folder = p.parent.name
    return bool(folder) and re.fullmatch(r"(?:.+-)?" + re.escape(folder) + r"(?:-\d+)?-hub", p.stem) is not None


def knowledge_folders(g):
    """{folder rel: {"notes": [graph notes directly inside, companions excluded], "hubs": [folder hubs inside],
    "subdirs": [child folder names], "ns": namespace or None}} for every folder below 40_Knowledge/ (graph:false
    folders and hidden files skipped)."""
    top = paths.KNOWLEDGE + "/"
    out = {}

    def entry(d):
        return out.setdefault(d, {"notes": [], "hubs": [], "mocs": [], "subdirs": [], "ns": paths.namespace_of(d)})

    for f in g.all_files:
        if not f.startswith(top) or paths.is_skipped(f):
            continue
        parts = Path(f).parts
        for i in range(2, len(parts)):
            d = "/".join(parts[:i])
            e = entry(d)
            if i < len(parts) - 1 and parts[i] not in e["subdirs"]:
                e["subdirs"].append(parts[i])
        if len(parts) < 3 or f not in g.nodes:
            continue
        e = entry("/".join(parts[:-1]))
        if is_folder_hub(f, g.nodes[f]["type"]):
            e["hubs"].append(f)
        elif paths.is_moc(parts[-1]):
            e["mocs"].append(f)
        elif paths.is_hub(parts[-1]) or not is_companion(parts[-1], g.schema):
            e["notes"].append(f)
    for e in out.values():
        e["subdirs"].sort()
    return out


def folder_note_count(folders, d):
    """Notes (hubs and companions excluded) in folder `d` and every folder below it."""
    return sum(len(e["notes"]) for k, e in folders.items() if k == d or k.startswith(d + "/"))


def knowledge_hub_folders(g, min_notes=None, min_subdirs=None, folders=None):
    """Folders that should carry a `<folder>-hub.md`: namespace or topic folders with >= min_notes notes
    (recursively) or >= min_subdirs subfolders holding notes (schema.json › knowledge.hub_min_notes /
    hub_min_subdirs; small folders need no index). A folder with its own hand-made `*-moc.md` is already indexed
    and needs no generated hub. -> {folder: existing hub rel or None}."""
    cfg = knowledge_cfg(g.schema)
    min_notes = cfg["hub_min_notes"] if min_notes is None else min_notes
    min_subdirs = cfg["hub_min_subdirs"] if min_subdirs is None else min_subdirs
    folders = folders if folders is not None else knowledge_folders(g)
    out = {}
    for d, e in folders.items():
        if not e["ns"]:
            continue
        if e["mocs"]:
            continue
        subs = sum(1 for t in e["subdirs"] if folder_note_count(folders, f"{d}/{t}"))
        if subs >= min_subdirs or folder_note_count(folders, d) >= min_notes:
            out[d] = e["hubs"][0] if e["hubs"] else None
    return out


# ---------------------------------------------------------------- logging
def log(root, action, path="", detail="", cmd="brain", **extra):
    """Append one JSON line to 50_Raw/logs/brain/YYYY-MM-DD.jsonl."""
    d = paths.logs_dir(root, "brain")
    try:
        d.mkdir(parents=True, exist_ok=True)
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "cmd": cmd, "action": action,
               "path": str(path), "detail": detail}
        rec.update(extra)
        with (d / f"{dt.date.today().isoformat()}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"WARN: could not write log: {e}", file=sys.stderr)


def udiff(rel, old, new):
    return "".join(difflib.unified_diff((old or "").splitlines(True), (new or "").splitlines(True),
                                        fromfile=f"a/{rel}" if old is not None else "/dev/null",
                                        tofile=f"b/{rel}" if new is not None else "/dev/null"))


# ---------------------------------------------------------------- git
class Git:
    """Git access for the vault: $BRAIN_GIT_DIR (a separate git dir whose core.worktree is this root or an
    ancestor of it) when set, else the repository that holds the root (`git rev-parse --show-toplevel`; the
    root may be a subfolder of it in a multi-root workspace). `prefix` is the root relative to the work tree
    ('' when equal); git runs with -C <root>, so pathspecs are root-relative."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.args = None
        self.prefix = ""
        gd = os.environ.get("BRAIN_GIT_DIR")
        if gd:
            gd = Path(gd).expanduser()
            if gd.is_dir():
                wt = subprocess.run(["git", f"--git-dir={gd}", "config", "--get", "core.worktree"],
                                    capture_output=True, text=True).stdout.strip()
                wtp = Path(wt).expanduser().resolve() if wt else None
                if wtp and (wtp == self.root or wtp in self.root.parents):
                    self.prefix = nfc(self.root.relative_to(wtp).as_posix()) if wtp != self.root else ""
                    self.args = ["git", f"--git-dir={gd}", f"--work-tree={wtp}", "-C", str(self.root)]
            return
        try:
            top = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True).stdout.strip()
        except OSError:  # git not installed
            return
        if top:
            topp = Path(top).resolve()
            if topp == self.root or topp in self.root.parents:
                self.prefix = nfc(self.root.relative_to(topp).as_posix()) if topp != self.root else ""
                self.args = ["git", "-C", str(self.root)]

    @property
    def available(self):
        return self.args is not None

    def run(self, *a, check=True, input=None):
        if not self.args:
            raise RuntimeError("no git repository for this vault")
        return subprocess.run(self.args + ["-c", "core.quotepath=false"] + list(a), capture_output=True,
                              text=True, check=check, input=input)

    def dirty(self, rels):
        """Subset of rels with uncommitted changes (modified, staged or untracked)."""
        if not self.args or not rels:
            return []
        out = self.run("status", "--porcelain", "-z", "--untracked-files=all", "--", *rels, check=False).stdout
        bad = set()
        pre = self.prefix + "/" if self.prefix else ""
        for ent in out.split("\0"):
            if len(ent) > 3:
                p = nfc(ent[3:])
                bad.add(p[len(pre):] if pre and p.startswith(pre) else p)
        return [r for r in rels if nfc(r) in bad]

    def is_tracked(self, rel):
        if not self.args:
            return False
        return self.run("ls-files", "--error-unmatch", "--", rel, check=False).returncode == 0

    def mv(self, src, dst, tracked=None):
        """git mv when tracked, plain rename otherwise; creates parent dirs. Case-only or NFC/NFD-only renames
        (the same path on APFS) go through a temporary name in two steps."""
        tracked = self.is_tracked(src) if tracked is None else tracked
        if nfc(src).casefold() == nfc(dst).casefold() and src != dst:
            tmp = f"{src}.brain-mv-tmp"
            self.mv(src, tmp, tracked)
            src = tmp
        (self.root / dst).parent.mkdir(parents=True, exist_ok=True)
        if tracked:
            self.run("mv", "--", src, dst)
        else:
            os.rename(self.root / src, self.root / dst)


# ---------- template date tokens (brain create, daily notes) ----------
WEEKDAYS = list(config.CONFIG["weekdays"])  # Monday first; note language from the config
# Obsidian core Templates / Daily notes tokens: {{date}}, {{date:FMT}}, {{time}}, {{time:FMT}}, {{title}} with a
# moment.js format subset (YYYY, MM, DD, M, D, dddd = weekday name, HH, mm, [literal]); legacy {{DATE}}/{{WEEKDAY}}.
TOKEN_RE = re.compile(r"\{\{\s*(date|time|title|DATE|WEEKDAY)(?::([^}]*))?\s*\}\}")
MOMENT_RE = re.compile(r"\[([^\]]*)\]|YYYY|dddd|MM|DD|HH|mm|M|D")


def moment(fmt, when):
    d = when
    vals = {"YYYY": f"{d.year:04d}", "MM": f"{d.month:02d}", "DD": f"{d.day:02d}", "M": str(d.month),
            "D": str(d.day), "dddd": WEEKDAYS[d.weekday()], "HH": f"{d.hour:02d}", "mm": f"{d.minute:02d}"}
    return MOMENT_RE.sub(lambda m: m.group(1) if m.group(1) is not None else vals[m.group(0)], fmt)


def render_template(tpl, date, now=None):
    """Fill the tokens Obsidian fills, so a daily note looks the same whoever creates it."""
    d = dt.date.fromisoformat(date)
    now = now or dt.datetime.now()
    when = dt.datetime.combine(d, now.time())

    def sub(m):
        kind, fmt = m.group(1), (m.group(2) or "").strip()
        if kind in ("date", "DATE"):
            return moment(fmt or "YYYY-MM-DD", when)
        if kind == "time":
            return moment(fmt or "HH:mm", when)
        if kind == "WEEKDAY":
            return WEEKDAYS[d.weekday()]
        return date  # {{title}} = file name of the daily note
    return TOKEN_RE.sub(sub, tpl)
