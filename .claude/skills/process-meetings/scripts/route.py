#!/usr/bin/env python3
"""route.py - score a meeting note (or any text) against active projects and rituals (python3 stdlib only).

  route.py <note> [--attendees "a,b"] [--title "calendar title"] [--context CTX]   -> JSON: route, target, reason,
                                                                                   candidates, ritual
  route.py --list                                                                  -> the routing table (JSON)

Scoring per active project (20_Projects/*/CLAUDE.md, `status: active`):
  +3 slug / title mentioned     +2 per `keywords` hit     +2 per `stakeholders` hit
  +1 keyword in the title       +1 same context
The winner needs score >= 4 and a lead >= 2, else `route: ambiguous`.
Rituals: any note under 30_Areas/ or the people registry with `meeting_match: [standup, 1:1 ada]` in frontmatter
(projects may carry it too) wins outright when one of its strings occurs in the note title (longest match wins).
`target`: branch project -> 20_Projects/<slug>/<meetings folder>/, flat project -> 20_Projects/<slug>/,
ritual -> that note, ambiguous -> 00_Inbox/meetings/. Matching is case- and diacritics-insensitive.
Run from the workspace (BRAIN_ROOT for multi-root). Exit code 0 unless the note is missing.
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))
import paths  # noqa: E402
import vault  # noqa: E402

MIN_SCORE, MIN_LEAD = 4, 2


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def word_in(word, text):
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None


def label(v):
    """`[[target|Label]]` -> Label, `[[Target]]` -> Target, else unchanged."""
    m = re.fullmatch(r"\s*\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\\?\|([^\]]+))?\]\]\s*", str(v))
    return (m.group(2) or m.group(1)).strip() if m else str(v).strip()


def fm_of(path):
    fm, m = vault.frontmatter(vault.read(path) or "")
    return {k: v.strip("\"'") if not v.startswith("[") else v for k, v in fm.items()}, m


def load_projects(root):
    out = []
    for d in paths.project_dirs(root):
        p = d / "CLAUDE.md"
        if not p.is_file():
            continue
        fm, _ = fm_of(p)
        if fm.get("status", "").lower() != "active":
            continue
        title = fm.get("title") or d.name
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9-]{3,}", norm(title))]
        out.append({"slug": d.name, "path": paths.rel(p, root), "title": title, "context": norm(fm.get("context")),
                    "keywords": sorted({norm(k) for k in vault.as_list(fm.get("keywords"))}),
                    "stakeholders": [label(x) for x in vault.as_list(fm.get("stakeholders"))],
                    "explicit": sorted({norm(d.name), norm(title)} | set(words)),
                    "match": [norm(x) for x in vault.as_list(fm.get("meeting_match"))]})
    return out


def load_rituals(root, projects):
    out = [{"path": p["path"], "title": p["title"], "match": p["match"]} for p in projects if p["match"]]
    cands = sorted((root / paths.AREAS).rglob("*.md")) if (root / paths.AREAS).is_dir() else []
    for p in cands + list(paths.iter_people(root)):
        fm, _ = fm_of(p)
        match = [norm(x) for x in vault.as_list(fm.get("meeting_match"))]
        if match:
            out.append({"path": paths.rel(p, root), "title": fm.get("title") or p.stem, "match": match})
    return out


def load_note(path, args):
    text = vault.read(path) or ""
    if path.suffix == ".vtt":
        text = "\n".join(ln for ln in text.splitlines() if ln.strip() and "-->" not in ln
                         and not ln.startswith(("WEBVTT", "NOTE")) and not ln.strip().isdigit())
    fmo = vault.Frontmatter(text)
    fm = fmo.as_dict()
    title = args.title or str(fm.get("title") or re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", path.stem).replace("-", " "))
    att = fm.get("attendees") or []
    att = [label(a) for a in (att if isinstance(att, list) else vault.as_list(str(att)))]
    att += [a.strip() for a in args.attendees.split(",") if a.strip()]
    return {"path": str(path), "title": title, "context": norm(args.context or fm.get("context") or ""),
            "attendees": att, "date": str(fm.get("date") or ""), "body": fmo.body}


def score(note, projects, rituals):
    ntitle = norm(note["title"])
    hay = norm(note["title"] + "\n" + note["body"] + "\n" + " ".join(note["attendees"]))
    ranked = []
    for pr in projects:
        s, hits = 0, []
        for term in pr["explicit"]:
            if len(term) >= 4 and (term in hay if (" " in term or "-" in term) else word_in(term, hay)):
                s += 3
                hits.append(f"explicit:{term}(+3)")
        for kw in pr["keywords"]:
            if kw and kw in hay:
                s += 2
                hits.append(f"kw:{kw}(+2)")
            if kw and kw in ntitle:
                s += 1
                hits.append(f"title-kw:{kw}(+1)")
        for st in pr["stakeholders"]:
            if norm(st) and norm(st) in hay:
                s += 2
                hits.append(f"stakeholder:{st}(+2)")
        if note["context"] and note["context"] == pr["context"]:
            s += 1
            hits.append("context(+1)")
        ranked.append({"slug": pr["slug"], "title": pr["title"], "path": pr["path"], "score": s, "hits": hits})
    ranked.sort(key=lambda c: (-c["score"], c["slug"]))
    rit = sorted(({"path": r["path"], "title": r["title"], "match": m} for r in rituals for m in r["match"]
                  if m and m in ntitle), key=lambda r: -len(r["match"]))
    ritual = rit[0] if rit and (len(rit) == 1 or len(rit[0]["match"]) > len(rit[1]["match"])) else None
    if ritual:
        route, reason = ritual["path"], f"ritual match '{ritual['match']}' in the title"
    elif rit:
        route, reason = "ambiguous", "several rituals match equally: " + ", ".join(r["path"] for r in rit)
    elif not ranked or ranked[0]["score"] < MIN_SCORE:
        route, reason = "ambiguous", f"best score {ranked[0]['score'] if ranked else 0} < {MIN_SCORE}"
    elif len(ranked) > 1 and ranked[0]["score"] - ranked[1]["score"] < MIN_LEAD:
        route, reason = "ambiguous", f"lead {ranked[0]['score'] - ranked[1]['score']} < {MIN_LEAD} over {ranked[1]['slug']}"
    else:
        route, reason = ranked[0]["slug"], f"score {ranked[0]['score']}, lead ok"
    return {"note": note["path"], "title": note["title"], "attendees": note["attendees"], "date": note["date"],
            "ritual": ritual, "candidates": ranked[:5], "route": route, "reason": reason}


def target(root, res):
    if res["ritual"]:
        return res["ritual"]["path"]
    if res["route"] == "ambiguous":
        return paths.MEETINGS + "/"
    d = root / paths.PROJECTS / res["route"]
    branch = d.is_dir() and any(e.is_dir() and not e.name.startswith(".") for e in d.iterdir())
    return f"{paths.PROJECTS}/{res['route']}/" + (f"{paths.MEETINGS_SUB}/" if branch else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("note", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--attendees", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--context", default="")
    ap.add_argument("--json", action="store_true", help="(output is always JSON)")
    args = ap.parse_args(argv)
    root = Path(paths.find_root())
    projects = load_projects(root)
    rituals = load_rituals(root, projects)
    if args.list or not args.note:
        print(json.dumps({"projects": projects, "rituals": rituals}, ensure_ascii=False, indent=1))
        return 0
    p = Path(args.note)
    if not p.is_absolute() and not p.exists():
        p = root / p
    if not p.is_file():
        print(f"error: note not found: {args.note}", file=sys.stderr)
        return 1
    res = score(load_note(p, args), projects, rituals)
    res["target"] = target(root, res)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
