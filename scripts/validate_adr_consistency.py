#!/usr/bin/env python3

"""Validate the ADR corpus against the house MADR conventions.

Lightweight *text* validator (no YAML/markdown deps) so it runs anywhere —
same shape as validate_alert_annotations.py. Conventions enforced (from
docs/techdocs/docs/adr/index.md and the adr-writer skill):

- Filenames: adr-NNNN-<kebab-title>.md, numbers unique.
- Every record carries status + date in exactly one format generation:
  MADR 4.0.0 (YAML frontmatter, records since 2026-07-12) or
  MADR 2.1.2 (`* Status:` / `* Date:` bullets, the pre-2026-07-12 corpus).
  Mixing both shapes in one file is an error.
- Status value is legal: proposed | accepted | rejected | deprecated |
  superseded by ADR-NNNN (the referenced ADR must exist).
- Exactly one H1, without an `ADR-NNNN:` prefix.
- Required sections: Context and Problem Statement, Considered Options,
  Decision Outcome (opening with `Chosen option:`), and the history section
  (More Information in 4.0.0, Links in 2.1.2).
- index.md Records tables: every record has exactly one row; the row's
  status (primary word) and Last-updated date match the file's own metadata.
  MkDocs hides frontmatter, so the index row is the reader-visible status —
  drift here is the failure mode this script exists to catch.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RE_FILENAME = re.compile(r"^adr-(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
RE_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
RE_FM_STATUS = re.compile(r'^status:\s*"?([^"\n]+?)"?\s*$', re.MULTILINE)
RE_FM_DATE = re.compile(r'^date:\s*"?(\d{4}-\d{2}-\d{2})"?\s*$', re.MULTILINE)
RE_BULLET_STATUS = re.compile(r"^\* Status:\s*(.+?)\s*$", re.MULTILINE)
RE_BULLET_DATE = re.compile(r"^\* Date:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
RE_H1 = re.compile(r"^# (.+)$", re.MULTILINE)
RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
RE_INDEX_ROW = re.compile(
    r"^\| \[(\d{4})\]\((adr-\d{4}-[^)]+\.md)\) \| .+? \| (.+?) \| (\d{4}-\d{2}-\d{2}) \|",
    re.MULTILINE,
)

LEGAL_PRIMARY = {"proposed", "accepted", "rejected", "deprecated", "superseded"}
SKIP = {"index.md", "landscape.md", "adr-0000-template.md"}

REQUIRED_SECTIONS = (
    "## Context and Problem Statement",
    "## Considered Options",
    "## Decision Outcome",
)


def strip_links(text: str) -> str:
    return RE_MD_LINK.sub(r"\1", text)


def primary(status: str) -> str:
    return strip_links(status).strip().lower().split()[0] if status.strip() else ""


def numbers_in(status: str) -> set[str]:
    return set(re.findall(r"\d{4}", status))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="repo root")
    args = parser.parse_args()

    adr_dir = Path(args.root) / "docs/techdocs/docs/adr"
    if not adr_dir.is_dir():
        print(f"missing {adr_dir}", file=sys.stderr)
        return 1

    errors: list[str] = []

    def err(name: str, msg: str) -> None:
        errors.append(f"{name}: {msg}")

    records: dict[str, dict] = {}  # number -> {name, status, date}
    for path in sorted(adr_dir.glob("*.md")):
        if path.name in SKIP:
            continue
        m = RE_FILENAME.match(path.name)
        if not m:
            err(path.name, "filename does not match adr-NNNN-<kebab-title>.md")
            continue
        number = m.group(1)
        if number in records:
            err(path.name, f"duplicate ADR number {number} (also {records[number]['name']})")
            continue
        text = path.read_text(encoding="utf-8")

        fm = RE_FRONTMATTER.match(text)
        fm_status = RE_FM_STATUS.search(fm.group(1)) if fm else None
        fm_date = RE_FM_DATE.search(fm.group(1)) if fm else None
        b_status = RE_BULLET_STATUS.search(text)
        b_date = RE_BULLET_DATE.search(text)

        if fm_status and b_status:
            err(path.name, "mixes frontmatter status and `* Status:` bullet — pick one format")
        if fm_status:  # MADR 4.0.0
            status, date = fm_status.group(1), fm_date.group(1) if fm_date else None
            history = "## More Information"
        elif b_status:  # MADR 2.1.2
            status, date = b_status.group(1), b_date.group(1) if b_date else None
            history = "## Links"
        else:
            err(path.name, "no status found (frontmatter `status:` or `* Status:` bullet)")
            continue
        if not date:
            err(path.name, "no date found (YYYY-MM-DD)")
            continue

        if primary(status) not in LEGAL_PRIMARY:
            err(path.name, f"illegal status {status!r}")
        if primary(status) == "superseded":
            for ref in numbers_in(status):
                if not list(adr_dir.glob(f"adr-{ref}-*.md")):
                    err(path.name, f"superseded by ADR-{ref}, which does not exist")

        h1s = RE_H1.findall(text)
        if len(h1s) != 1:
            err(path.name, f"expected exactly one H1, found {len(h1s)}")
        elif re.match(r"(?i)adr[- ]?\d", h1s[0]):
            err(path.name, f"H1 must be a bare title, no ADR-number prefix: {h1s[0]!r}")

        for section in REQUIRED_SECTIONS + (history,):
            if f"\n{section}\n" not in text:
                err(path.name, f"missing required section {section!r}")
        if "\nChosen option:" not in text:
            err(path.name, 'Decision Outcome must open with `Chosen option: "…", because …`')

        records[number] = {"name": path.name, "status": status, "date": date}

    index_text = (adr_dir / "index.md").read_text(encoding="utf-8")
    rows: dict[str, tuple[str, str, str]] = {}  # number -> (file, status, date)
    for number, fname, status, date in RE_INDEX_ROW.findall(index_text):
        if number in rows:
            err("index.md", f"ADR {number} listed twice in the Records tables")
        rows[number] = (fname, status, date)

    for number, rec in sorted(records.items()):
        if number not in rows:
            err("index.md", f"no Records row for {rec['name']}")
            continue
        fname, idx_status, idx_date = rows[number]
        if fname != rec["name"]:
            err("index.md", f"row {number} links {fname}, file is {rec['name']}")
        if primary(idx_status) != primary(rec["status"]):
            err(
                "index.md",
                f"row {number} status {idx_status!r} != file status {rec['status']!r}",
            )
        if idx_date != rec["date"]:
            err(
                "index.md",
                f"row {number} Last updated {idx_date} != file date {rec['date']}"
                f" ({rec['name']})",
            )
    for number, (fname, _, _) in sorted(rows.items()):
        if number not in records:
            err("index.md", f"Records row {number} ({fname}) has no matching file")

    if errors:
        for e in errors:
            print(f"  {e}")
        print(f"validate-adr-consistency: FAILED ({len(errors)} problem(s))", file=sys.stderr)
        return 1
    print(f"validate-adr-consistency: OK ({len(records)} records checked against index)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
