#!/usr/bin/env python3
"""check_evidence.py - grounding check of a meeting note against its transcript (python3 stdlib only).

  check_evidence.py NOTE --source TRANSCRIPT [--section TEXT] [--json]

Every number, date, time, percentage, amount and direct quote in the note must exist in the source. Each claim is
  FOUND    in the source (case, diacritics, spacing and thousand separators folded)
  FUZZY    close: a quote with similarity >= 0.8, or the number is there without its unit/currency
  MISSING  not in the source -> fix the claim, remove it, or mark the line `(unverified)`
  MARKED   the line carries `(unverified)` (or `--marker`) -> accepted
Exit 0 when nothing is MISSING, 1 otherwise, 2 on usage errors.

Ignored in the note: frontmatter, headings, wikilinks, link targets, URLs, inline code, HTML comments, `^f-` ids,
dates equal to the meeting date (frontmatter `date:` or the file name prefix), single-digit numbers and numbers
glued to letters (B2B, 4K). `--section TEXT` checks only the part under the first heading containing TEXT
(a ritual or person note gets a new dated section per meeting). Number words ("twenty") are not parsed:
write digits in notes, or expect a FUZZY/MISSING that you confirm by reading the transcript.
"""
import argparse
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

FUZZY = 0.8
FM_RE = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*\n", re.S)
NUM_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ ,.  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
                    r"(\s?(?:%|percent|k\b|m\b|bn\b|[$€£¥]|[A-Z]{3}\b))?(?![\w])")
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DMY_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})?\b")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
QUOTE_RE = re.compile(r"[\"“„«]([^\"“”„«»\n]{8,}?)[\"”“»]")


def fold(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[   ]", " ", s)
    return re.sub(r"[–—−]", "-", s)


def digits(v):
    """'12 500,5' / '12,500.5' / '12.500' -> canonical string of the value's digits."""
    v = re.sub(r"[   ]", "", v)
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", v):
        return v.replace(".", "").replace(",", "")
    m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})*)[.,](\d{1,2})", v)
    if m and re.search(r"[.,]\d{3}", m.group(1)):
        return m.group(1).replace(".", "").replace(",", "") + "." + m.group(2)
    return v.replace(",", ".")


def unit(u):
    u = (u or "").strip().lower()
    return "%" if u in ("%", "percent") else u


def source_numbers(src):
    """{(value, unit)} of every number in the source, plus (value, "") for each."""
    out = set()
    for m in NUM_RE.finditer(src):
        out |= {(digits(m.group(1)), unit(m.group(2))), (digits(m.group(1)), "")}
    return out


def clean_note(text, section=None):
    text = FM_RE.sub("", text)
    if section:
        m = re.search(r"^(#+)[^\n]*" + re.escape(section) + r"[^\n]*\n", text, re.M)
        if not m:
            return None
        lvl = len(m.group(1))
        end = re.search(r"^#{1,%d} " % lvl, text[m.end():], re.M)
        text = text[m.end(): m.end() + end.start()] if end else text[m.end():]
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"^#+ .*$", "", text, flags=re.M)
    text = re.sub(r"\[\[[^\]]*\]\]|\]\([^)]*\)|https?://\S+|`[^`\n]*`|\^f-[0-9a-f]{6}", " ", text)
    return text


def check(note_text, src_text, meeting_date="", section=None, marker="(unverified)"):
    body = clean_note(note_text, section)
    if body is None:
        return None
    src = fold(src_text)
    src_nums = source_numbers(src_text)
    src_words = src.split()
    out = []
    for line in body.splitlines():
        if not line.strip():
            continue
        marked = marker.lower() in line.lower()
        claims, taken = [], []
        for rx, kind in ((ISO_RE, "date"), (DMY_RE, "date"), (TIME_RE, "time"), (QUOTE_RE, "quote")):
            for m in rx.finditer(line):
                taken.append((m.start(), m.end()))
                claims.append((kind, m))
        for m in NUM_RE.finditer(line):
            if any(a <= m.start() < b for a, b in taken):
                continue
            val = m.group(1)
            if len(val) == 1 and not m.group(2):
                continue
            claims.append(("number", m))
        for kind, m in claims:
            raw = m.group(0).strip()
            if kind == "date" and m.re is ISO_RE and raw == meeting_date:
                continue
            status = "MISSING"
            if kind == "quote":
                q = fold(m.group(1)).split()
                if " ".join(q) in " ".join(src_words):
                    status = "FOUND"
                else:
                    n = len(q)
                    best = max((difflib.SequenceMatcher(None, q, src_words[i:i + n]).ratio()
                                for i in range(0, max(1, len(src_words) - n + 1))), default=0)
                    status = "FUZZY" if best >= FUZZY else "MISSING"
            elif kind == "date":
                if m.re is ISO_RE:
                    y, mo, d = m.groups()
                    alts = [raw, f"{int(d)}.{int(mo)}.", f"{int(d)}. {int(mo)}.", f"{int(mo)}/{int(d)}", f"{int(d)}/{int(mo)}"]
                else:
                    d, mo = m.group(1), m.group(2)
                    alts = [fold(raw), f"{d}.{mo}.", f"{d}. {mo}.", f"{d}/{mo}", f"-{int(mo):02d}-{int(d):02d}"]
                status = "FOUND" if any(a in src for a in alts) else "MISSING"
            elif kind == "time":
                h, mi = m.groups()
                status = "FOUND" if re.search(rf"\b0?{int(h)}[:.]{mi}\b", src) else \
                    "FUZZY" if re.search(rf"\b{int(h)}\b", src) else "MISSING"
            else:
                val = digits(m.group(1))
                if fold(raw) in src:
                    status = "FOUND"
                elif (val, unit(m.group(2))) in src_nums:
                    status = "FOUND"
                elif (val, "") in src_nums:
                    status = "FUZZY"
            if marked and status == "MISSING":
                status = "MARKED"
            out.append({"kind": kind, "claim": raw, "status": status, "line": line.strip()[:160]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("note")
    ap.add_argument("--source", required=True)
    ap.add_argument("--section")
    ap.add_argument("--marker", default="(unverified)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        note, src = Path(a.note).read_text(encoding="utf-8"), Path(a.source).read_text(encoding="utf-8")
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    dm = re.search(r"^date:\s*[\"']?(\d{4}-\d{2}-\d{2})", note, re.M) or re.match(r"(\d{4}-\d{2}-\d{2})", Path(a.note).name)
    res = check(note, src, dm.group(1) if dm else "", a.section, a.marker)
    if res is None:
        print(f"error: section not found: {a.section}", file=sys.stderr)
        return 2
    counts = {k: sum(1 for r in res if r["status"] == k) for k in ("FOUND", "FUZZY", "MISSING", "MARKED")}
    summary = f"{len(res)} claims: " + " · ".join(f"{v} {k}" for k, v in counts.items())
    if a.json:
        print(json.dumps({"summary": summary, "counts": counts, "claims": res}, ensure_ascii=False, indent=1))
    else:
        for r in res:
            if r["status"] in ("MISSING", "FUZZY"):
                print(f"{r['status']:<8} {r['kind']:<6} {r['claim']!r}  | {r['line']}")
        print(summary)
    return 1 if counts["MISSING"] else 0


if __name__ == "__main__":
    sys.exit(main())
