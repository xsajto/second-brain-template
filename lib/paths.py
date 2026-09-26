"""paths.py - every folder of the vault in one place (python3 stdlib only).

Layout: numbered roots 00_Inbox/ (+ 00_Inbox/meetings/), 10_Daily/YYYY/, 20_Projects/<slug>/, 30_Areas/<role>/,
40_Knowledge/, 50_Raw/ (+ 50_Raw/logs/<skill>/), 99_Archives/. Every name below the root is ascii kebab-case
(exceptions: CLAUDE.md, README.md, AGENTS.md, SKILL.md); human names live in `title:` / `aliases:`.
40_Knowledge/ = two global registries (people, orgs) + namespaces by *whose* knowledge it is (one per context,
`shared/`, any company) with free topic subfolders; frontmatter `type`/`kind` says *what* a note is.
Folder names that are not numbered roots (registries, project/area subfolders, …), contexts, roots and project
slug prefixes come from brain.config.json (lib/config.py). Paths are relative to the vault root unless a function
says otherwise.

Single root (default): the workspace (the repo) is the vault root. Multi-root: `roots` in the config names
folders of the workspace (e.g. `work/` and `home/`), each a vault root with its own numbered folders; the
workspace keeps bin/, lib/, templates/, docs/. find_root() works from cwd or $BRAIN_ROOT.
"""
import datetime as dt
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

CFG = config.CONFIG
F = CFG["folders"]

# ---------------------------------------------------------------- top level (numbered English roots, fixed)
INBOX = "00_Inbox"
MEETINGS = "00_Inbox/meetings"       # transcripts landing zone
DAILY = "10_Daily"                   # 10_Daily/YYYY/YYYY-MM-DD.md
PROJECTS = "20_Projects"
AREAS = "30_Areas"
KNOWLEDGE = "40_Knowledge"
RESOURCES = "50_Raw"
ARCHIVES = "99_Archives"
TEMPLATES = F["templates"]           # note templates; not graph notes
SYSTEM = F["system_docs"]            # human-readable system docs; not graph notes
LOGS = "50_Raw/logs"                 # run logs of skills/scripts
BRAIN_LOGS = "50_Raw/logs/brain"
ROOT_TOP = (INBOX, DAILY, PROJECTS, AREAS, KNOWLEDGE, RESOURCES, ARCHIVES)   # note folders of a vault root
WORKSPACE_TOP = (TEMPLATES, SYSTEM)                                           # shared system folders
TOP_LEVEL = ROOT_TOP + WORKSPACE_TOP

# ---------------------------------------------------------------- contexts and roots (config)
CONTEXTS = tuple(CFG["contexts"])
SLUG_CTX = {spec["slug"]: name for name, spec in CFG["contexts"].items()}
CTX_SLUG = {v: k for k, v in SLUG_CTX.items()}
ROOTS = CFG["roots"]                 # path relative to the workspace -> {"contexts": [...]}

# ---------------------------------------------------------------- knowledge (config)
KNOWLEDGE_DIR = KNOWLEDGE
PEOPLE_DIR = F["people"]             # global registry: type person
ORGS_DIR = F["orgs"]                 # global registry: type org
REGISTRY_DIRS = (PEOPLE_DIR, ORGS_DIR)
SHARED_NS = CFG["shared_namespace"]
SHARED_DIR = f"{KNOWLEDGE}/{SHARED_NS}"
KNOWLEDGE_MOC = "40_Knowledge/knowledge-moc.md"
IDEAS_SUB = F["ideas"]
REPORTS_DIR = F["reports"]
KNOWLEDGE_DIRS = (RESOURCES, KNOWLEDGE)
DAILY_GLOB = "10_Daily/[0-9][0-9][0-9][0-9]/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md"
# subfolders a project (branch) or an area (role) may hold
MEETINGS_SUB, DECISIONS_SUB, NOTES_SUB = F["meetings"], F["decisions"], F["notes"]
OUTPUTS_SUB, SOURCES_SUB = F["outputs"], F["sources"]
PROJECT_SUBDIRS = (MEETINGS_SUB, DECISIONS_SUB, NOTES_SUB, OUTPUTS_SUB, SOURCES_SUB)
AREA_SUBDIRS = (DECISIONS_SUB, MEETINGS_SUB, NOTES_SUB)
RELATION_MAP = F["relationship_map"]  # relationship map in the primary area of a context
HUB_SUFFIX = "-hub.md"               # <area-slug>-hub.md
MOC_SUFFIX = "-moc.md"               # <name>-moc.md
# vendor / bulk reference folders: kept out of `.claude/index.md` by default (their MOC or
# README still gets an index line); folders whose README has `graph: false` are out of the graph altogether
VENDOR_DIRS = tuple(CFG["vendor_dirs"])
AGENT_INDEX = ".claude/index.md"     # generated navigation index (brain context --write)
HOT = ".claude/hot.md"               # generated session snapshot (brain context --write / SessionStart hook)


def namespace_of(relpath):
    """Knowledge namespace of a note or folder path (`40_Knowledge/<ns>[/…]` -> ns), None for the registries,
    files directly in 40_Knowledge/ and anything outside it."""
    parts = Path(nfc(str(relpath))).parts
    if len(parts) < 2 or parts[0] != KNOWLEDGE or f"{KNOWLEDGE}/{parts[1]}" in REGISTRY_DIRS:
        return None
    if len(parts) == 2 and Path(parts[1]).suffix:  # a file at the 40_Knowledge/ root
        return None
    return parts[1]


def namespace_dir(ns):
    """Vault-relative folder of a Knowledge namespace: 40_Knowledge/<ns>."""
    return f"{KNOWLEDGE}/{ns}"


def topic_parts(relpath):
    """Topic folders between the namespace and a note (`40_Knowledge/acme/infra/sites/x.md` ->
    ('infra', 'sites')); for a folder path (no suffix) the folder counts too; () outside a namespace."""
    parts = Path(nfc(str(relpath))).parts
    if not namespace_of(relpath):
        return ()
    return tuple(parts[2:-1]) if Path(parts[-1]).suffix else tuple(parts[2:])


def in_dirs(relpath, dirs):
    rp = nfc(str(relpath))
    return any(rp == d or rp.startswith(d + "/") for d in dirs)


# ---------------------------------------------------------------- scanning rules
SKIP_PARTS = {".obsidian", ".claude", ".git", ".trash", "node_modules", ".DS_Store", "__pycache__"}
# run logs, templates, docs and the engine's own folders (bin/, lib/, tests/, plugins/ …) are not notes
SKIP_PREFIXES = tuple(dict.fromkeys((LOGS, TEMPLATES, SYSTEM, *CFG["system_dirs"])))
DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
SLUG_RE = re.compile(r"^(" + "|".join(sorted((re.escape(s) for s in SLUG_CTX), key=len, reverse=True) or ["x"])
                     + r")-[a-z0-9-]+$")
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_EXCEPTIONS = {"CLAUDE.md", "README.md", "AGENTS.md", "SKILL.md"}  # keep their names anywhere
MAX_STEM = 60


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def kebab(s, maxlen=MAX_STEM):
    """ASCII lowercase kebab-case for a file/folder name (without extension): accents transliterated, emoji and
    punctuation dropped, separators (' - ', ' — ', '–', spaces, &, (), +, _, .) -> '-', truncated at a hyphen
    to <= maxlen. 'Café Menu - Hub' -> 'cafe-menu-hub', '🗺️ Team MOC' -> 'team-moc'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    if maxlen and len(s) > maxlen:
        cut = s[:maxlen + 1]
        s = cut.rsplit("-", 1)[0] if "-" in cut[1:] else s[:maxlen]
        s = s.strip("-")
    return s or "x"


def is_kebab_name(name):
    """True for an allowed file/folder name below the root: an exception (CLAUDE.md …) or ascii kebab stem
    (+ lowercase extension); dated names `YYYY-MM-DD[-rest]` are kebab too."""
    if name in NAME_EXCEPTIONS:
        return True
    stem, dot, ext = name.partition(".") if not name.startswith(".") else (name, "", "")
    if "." in ext:  # stem.with.dots.ext -> not kebab
        return False
    return bool(KEBAB_RE.match(stem)) and (not ext or re.match(r"^[a-z0-9]+$", ext) is not None)


def is_root(d):
    """True for a vault root: 20_Projects/ plus CLAUDE.md or 00_Inbox/."""
    d = Path(d)
    return (d / PROJECTS).is_dir() and ((d / "CLAUDE.md").is_file() or (d / INBOX).is_dir())


def find_root(start=None):
    """Vault root: $BRAIN_ROOT, else the first ancestor of `start` (default cwd) that is_root()."""
    env = os.environ.get("BRAIN_ROOT")
    if env:
        return Path(env).resolve()
    base = Path(start or Path.cwd()).resolve()
    for d in [base, *base.parents]:
        if is_root(d):
            return d
    hint = ", ".join(f"{r}/" for r in ROOTS if r != ".") or "the vault"
    raise SystemExit(f"Brain root not found ({PROJECTS}/ + CLAUDE.md or {INBOX}/ above {base}); "
                     f"cd into {hint} (or set BRAIN_ROOT)")


def workspace():
    """The workspace (repo) folder: $BRAIN_WORKSPACE, else the folder holding brain.config.json above lib/, else
    the folder above lib/."""
    return config.workspace()


def ws_path(relpath):
    """Absolute path of a workspace-relative path ("bin/brain", "docs/how-it-works.md")."""
    return workspace() / relpath


def templates_dir(root=None):
    """templates/: in the workspace, else in the root."""
    ws = workspace() / TEMPLATES
    if ws.is_dir():
        return ws
    if root is not None and (Path(root) / TEMPLATES).is_dir():
        return Path(root) / TEMPLATES
    return ws


def root_key(root):
    """The config `roots` key of a vault root ("." for the workspace itself), or None when not configured."""
    root = Path(root).resolve()
    ws = workspace().resolve()
    for key in ROOTS:
        try:
            if (ws / key).resolve() == root:
                return key
        except OSError:
            continue
    return None


def root_name(root):
    return Path(root).resolve().name


def root_contexts(root):
    """Contexts whose notes live in this root; every context for a root not listed in the config."""
    key = root_key(root)
    return tuple(ROOTS[key]["contexts"]) if key is not None else CONTEXTS


def is_split_root(root):
    """True when the config has several roots and this is one of them."""
    return len(ROOTS) > 1 and root_key(root) is not None


def contexts_root(ctx):
    """Config root key(s) holding a context."""
    return [k for k, v in ROOTS.items() if ctx in v["contexts"]]


def sibling_roots(root):
    """Other configured vault roots of the workspace (multi-root); [] for a single-root vault."""
    if not is_split_root(root):
        return []
    root = Path(root).resolve()
    ws = workspace().resolve()
    return sorted(d for d in ((ws / k).resolve() for k in ROOTS) if d != root and is_root(d))


def all_roots(root=None):
    """Every vault root of the workspace (the configured roots that exist, else the given/current root)."""
    ws = workspace()
    found = [(ws / k).resolve() for k in ROOTS if is_root(ws / k)]
    if found:
        return found
    return [Path(root).resolve()] if root is not None else []


def rel(path, root):
    """Vault-relative POSIX string (NFC)."""
    p = Path(path)
    try:
        p = p.resolve().relative_to(Path(root).resolve()) if p.is_absolute() else p
    except ValueError:
        pass
    return nfc(p.as_posix())


def is_skipped(relpath):
    """Not a note: hidden parts, engine folders, logs, templates, docs, and every markdown file at the root
    (CLAUDE.md, README.md … are instructions; notes live in the numbered folders)."""
    parts = Path(relpath).parts
    if any(part in SKIP_PARTS or part.startswith(".") for part in parts):
        return True
    if len(parts) == 1:
        return True
    rp = nfc(Path(relpath).as_posix())
    return any(rp == pre or rp.startswith(pre + "/") for pre in SKIP_PREFIXES)


def iter_files(root, top=None):
    """Every non-hidden file under root (or root/top), skipping SKIP_PARTS, run logs and templates; yields Paths."""
    base = Path(root) / top if top else Path(root)
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        rd = rel(dirpath, root)
        dirnames[:] = sorted(d for d in dirnames if not is_skipped(f"{rd}/{d}" if rd != "." else f"{d}/x"))
        for f in sorted(filenames):
            rp = f"{rd}/{f}" if rd != "." else f
            if not is_skipped(rp):
                yield Path(dirpath) / f


def iter_notes(root, include_archives=True):
    """All Markdown notes (absolute Paths) in the vault."""
    for p in iter_files(root):
        if p.suffix != ".md":
            continue
        if not include_archives and rel(p, root).startswith(ARCHIVES + "/"):
            continue
        yield p


def is_daily(relpath):
    rp = Path(nfc(str(relpath)))
    if not DAILY_RE.match(rp.name):
        return False
    parts = rp.parts
    return len(parts) == 3 and parts[0] == DAILY and re.match(r"^\d{4}$", parts[1]) is not None


def daily_path(date, root):
    """Where the daily note for `date` lives: 10_Daily/YYYY/YYYY-MM-DD.md."""
    if isinstance(date, str):
        date = dt.date.fromisoformat(date)
    return Path(root) / DAILY / f"{date.year:04d}" / f"{date.isoformat()}.md"


def people_dir(root, context=None):
    """Folder for a new person note: the people registry (context is recorded in frontmatter, not the folder)."""
    return Path(root) / PEOPLE_DIR


def project_dirs(root, include_archives=False):
    base = Path(root) / PROJECTS
    out = sorted(d for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")) if base.is_dir() else []
    if include_archives and (Path(root) / ARCHIVES).is_dir():
        out += sorted(d for d in (Path(root) / ARCHIVES).iterdir() if d.is_dir() and SLUG_RE.match(d.name))
    return out


def is_hub(name):
    return nfc(name).endswith(HUB_SUFFIX)


def is_moc(name):
    return nfc(name).endswith(MOC_SUFFIX)


def area_hub(area_dir):
    """The area note: `<area-slug>-hub.md` inside an area folder (first match), or the expected path when missing.
    It carries the area entity (type: area, kind: role, context, sources, rituals)."""
    area_dir = Path(area_dir)
    hubs = sorted(area_dir.glob("*" + HUB_SUFFIX))
    return hubs[0] if hubs else area_dir / f"{area_dir.name}{HUB_SUFFIX}"


def logs_dir(root, skill="brain"):
    return Path(root) / LOGS / skill


# ---------------------------------------------------------------- sync conflict copies
# File-sync tools resolve a conflict by keeping both files: `note.md` + `note 2.md` (others add
# "conflicted copy"). Only `.git` (and Obsidian's .trash) are not scanned.
CONFLICT_RE = re.compile(r"^(?P<base>.+?) (?P<n>[2-9]|[1-9][0-9])(?P<ext>\.[^. ]+)?$")
CONFLICT_SKIP = {".git", ".trash", "node_modules"}


def is_conflict_name(name):
    """True for a name shaped like a sync conflict copy (`x 2`, `x 2.md`) or a `conflicted copy`."""
    name = nfc(name)
    return "conflicted copy" in name.casefold() or bool(CONFLICT_RE.match(name))


def conflict_copies(root):
    """[vault-relative path] of sync conflict copies: `* N[.ext]` whose original (`*[.ext]`) sits next to it,
    or any name containing `conflicted copy`. Folders count too (their content is not descended)."""
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        names = set(dirnames) | set(filenames)
        hits = []
        for name in sorted(names):
            n = nfc(name)
            m = CONFLICT_RE.match(n)
            if "conflicted copy" in n.casefold() or (m and (m["base"] + (m["ext"] or "")) in {nfc(x) for x in names}):
                hits.append(name)
        dirnames[:] = sorted(d for d in dirnames if d not in CONFLICT_SKIP and d not in hits)
        rd = rel(dirpath, root)
        out += [nfc(f"{rd}/{h}" if rd != "." else h) for h in hits]
    return sorted(out)


def folder_context(relpath):
    """Context implied by the folder (project slug prefix), else None; areas carry `context:` in their hub."""
    parts = Path(nfc(str(relpath))).parts
    if len(parts) > 1 and parts[0] in (PROJECTS, ARCHIVES):
        m = SLUG_RE.match(parts[1])
        return SLUG_CTX.get(m.group(1)) if m else None
    return None
