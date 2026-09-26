"""config.py - `brain.config.json`, the one place a vault's personal structure lives (python3 stdlib only).

Every key is optional; a missing file means the defaults below (single root = the repo, contexts `work` and
`private`, English folder names). The file is found as:
    $BRAIN_CONFIG (a path; a missing file there means defaults), else
    <workspace>/brain.config.json, where the workspace is $BRAIN_WORKSPACE, else the nearest ancestor of lib/
    that holds brain.config.json, else the folder above lib/ (the repo root).
Merging is deep for objects (a partial "folders" keeps the other defaults) and replaces lists and scalars.
`contexts` and `roots` replace the defaults as a whole when given (a vault defines its own set).
"""
import json
import os
from pathlib import Path

LIB = Path(__file__).resolve().parent
FILE_NAME = "brain.config.json"

DEFAULTS = {
    "user": {"name": "", "role": "", "org": ""},
    "language": "en",
    # root path relative to the workspace -> contexts whose notes live there ("." = the workspace itself;
    # no "contexts" = every context)
    "roots": {".": {}},
    # context -> project slug prefix, primary area (standing sources, relationship map), knowledge namespace
    "contexts": {
        "work": {"slug": "work", "primary_area": "30_Areas/work", "namespace": "work"},
        "private": {"slug": "priv", "primary_area": "30_Areas/private", "namespace": "private"},
    },
    "folders": {
        "people": "40_Knowledge/people",      # global registry of person notes
        "orgs": "40_Knowledge/orgs",          # global registry of org notes
        "meetings": "meetings",               # subfolder of a project/area: meeting notes
        "decisions": "decisions",             # subfolder of a project/area: decision records
        "notes": "notes",                     # subfolder of a project/area: working notes
        "outputs": "outputs",                 # subfolder of a project: deliverables
        "sources": "sources",                 # subfolder of a project: raw material kept as-is
        "ideas": "ideas",                     # any folder of this name below 40_Knowledge/ holds ideas
        "reports": "50_Raw/reports",
        "relationship_map": "relationship-map.md",
        "templates": "templates",             # note templates (workspace level)
        "system_docs": "docs",                # human docs (workspace level); not notes
    },
    "shared_namespace": "shared",             # knowledge owned by no context
    "flat_knowledge": [],                     # folders below 40_Knowledge/ listed in full in index.md (never collapsed)
    "vendor_dirs": [],                        # bulk reference folders kept out of index.md
    "companions": [],                         # extra file names allowed next to subfolders (branch/leaf rule)
    "system_dirs": ["bin", "lib", "tests", "templates", "docs", "plugins"],  # root folders that hold no notes
    "labels": {},                             # type -> plural label (overrides schema.json); no reader in the core
    "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "stopwords": [],                          # no reader in the core; kept so existing configs stay valid
    "pending_marker": "pending",              # a numbered proposal line in a run log ending in this waits for an answer
    "task_manager": {"default": "none"},
    "integrations": {},
}
REPLACE_KEYS = {"contexts", "roots"}


def workspace():
    """The workspace folder: $BRAIN_WORKSPACE, else the nearest ancestor of lib/ holding brain.config.json, else
    the folder above lib/."""
    env = os.environ.get("BRAIN_WORKSPACE")
    if env:
        return Path(env).resolve()
    for d in LIB.parents:
        if (d / FILE_NAME).is_file():
            return d
    return LIB.parent


def config_path():
    env = os.environ.get("BRAIN_CONFIG")
    return Path(env) if env else workspace() / FILE_NAME


def _merge(base, over, top=True):
    out = dict(base)
    for k, v in (over or {}).items():
        if top and k in REPLACE_KEYS:
            out[k] = v
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v, top=False)
        else:
            out[k] = v
    return out


def normalise(cfg):
    """Fill per-context defaults (slug = context name, namespace = context name, primary area = 30_Areas/<name>)
    and per-root defaults (contexts = every context)."""
    ctxs = {}
    for name, spec in (cfg.get("contexts") or {}).items():
        spec = dict(spec or {})
        spec.setdefault("slug", name)
        spec.setdefault("namespace", name)
        spec.setdefault("primary_area", f"30_Areas/{name}")
        ctxs[name] = spec
    cfg["contexts"] = ctxs
    roots = {}
    for name, spec in (cfg.get("roots") or {".": {}}).items():
        spec = dict(spec or {})
        spec["contexts"] = list(spec.get("contexts") or ctxs)
        roots[str(name).strip("/") or "."] = spec
    cfg["roots"] = roots
    return cfg


def read_file(path=None):
    """The user's config as stored ({} when the file is missing); raises ValueError on invalid JSON."""
    p = Path(path) if path else config_path()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{p}: top level must be a JSON object")
    return data


def load(path=None):
    """Effective config: defaults deep-merged with the file."""
    return normalise(_merge(json.loads(json.dumps(DEFAULTS)), read_file(path)))


def check(cfg=None, path=None):
    """[problem] for a config: unknown contexts in roots, duplicate slugs, non-kebab folder names."""
    import re
    try:
        cfg = cfg or load(path)
    except ValueError as e:
        return [f"invalid JSON: {e}"]
    out = []
    ctxs = cfg["contexts"]
    if not ctxs:
        out.append("no contexts defined")
    for r, spec in cfg["roots"].items():
        for c in spec["contexts"]:
            if c not in ctxs:
                out.append(f"root {r}: unknown context {c}")
    slugs = [s["slug"] for s in ctxs.values()]
    for s in sorted({s for s in slugs if slugs.count(s) > 1}):
        out.append(f"project slug prefix {s} used by several contexts")
    kebab = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    for name, spec in ctxs.items():
        if not kebab.match(spec["slug"]):
            out.append(f"context {name}: slug {spec['slug']!r} is not ascii kebab-case")
    for key, val in cfg["folders"].items():
        for seg in str(val).split("/"):
            stem = seg[:-3] if seg.endswith(".md") else seg
            if not (kebab.match(stem) or re.match(r"^\d\d_[A-Za-z]+$", stem)):
                out.append(f"folders.{key}: {val!r} is not ascii kebab-case")
                break
    return out


try:
    CONFIG, ERROR = load(), None
except ValueError as _e:  # a broken file must not break hooks: defaults + `brain doctor` reports it
    CONFIG, ERROR = normalise(json.loads(json.dumps(DEFAULTS))), f"invalid JSON in {config_path()}: {_e}"
