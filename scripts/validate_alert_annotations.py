#!/usr/bin/env python3

"""Validate alert summary/description format for this repo.

This is intentionally a lightweight *text* validator (no YAML parsing deps) so it
can run anywhere.

Rules enforced (from docs/techdocs/docs/alerting-principles.md):
- annotations.summary is present and includes a scope in parentheses.
- annotations.description uses a block scalar and includes the standard sections.

Applies to:
- PrometheusRule alert rules (monitoring.coreos.com/v1)
- Sloth PrometheusServiceLevel burn-rate alert annotations
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


RE_KIND_PROMETHEUSRULE = re.compile(r"^kind:\s*PrometheusRule\s*$")
RE_KIND_SLOTH_SLO = re.compile(r"^kind:\s*PrometheusServiceLevel\s*$")

RE_ALERT_NAME = re.compile(r"^\s*-\s*alert:\s*(?P<name>\S+)\s*$")

RE_ANNOTATIONS_LINE = re.compile(r"^(?P<indent>\s*)annotations:\s*$")
RE_SUMMARY_LINE = re.compile(r"^\s*summary:\s*(?P<value>.+?)\s*$")
RE_DESCRIPTION_BLOCK = re.compile(r"^(?P<indent>\s*)description:\s*\|\s*$")

RE_SLOTH_ALERTING = re.compile(r"^(?P<indent>\s*)alerting:\s*$")

RE_YAML_FILE = re.compile(r".*\.ya?ml$")

RE_SCOPE_PARENS = re.compile(r"\(.*\)")

REQUIRED_SECTIONS = (
    "What's happening:",
    "Impact/risk:",
    "Likely causes:",
    "First actions:",
)


@dataclass
class Failure:
    path: Path
    subject: str
    message: str


def _is_yaml(path: Path) -> bool:
    return bool(RE_YAML_FILE.fullmatch(path.name))


def _scan_annotations_block(lines: list[str], start_index: int) -> tuple[dict[str, str], set[str], int]:
    """Scan an annotations block starting at `annotations:` line.

    Returns:
      - kv: summary/raw value, and whether description is block
      - sections: set of found required section headers
      - end_index: first line index after the block
    """

    m = RE_ANNOTATIONS_LINE.match(lines[start_index])
    if not m:
        return {}, set(), start_index + 1

    base_indent = m.group("indent")
    block_end = len(lines)

    summary_value: str | None = None
    has_description_block = False
    found_sections: set[str] = set()

    # First pass: find summary + description block marker.
    description_block_indent: str | None = None
    description_start = None

    for i in range(start_index + 1, len(lines)):
        line = lines[i]

        # End when indentation returns to <= base_indent and looks like a key.
        if line.strip() and (not line.startswith(base_indent + " ")) and not line.startswith(base_indent + "\t"):
            block_end = i
            break

        summary_match = RE_SUMMARY_LINE.match(line)
        if summary_match and summary_value is None:
            summary_value = summary_match.group("value").strip()

        desc_match = RE_DESCRIPTION_BLOCK.match(line)
        if desc_match and not has_description_block:
            has_description_block = True
            description_block_indent = desc_match.group("indent")
            description_start = i

    # Second pass: if description block exists, look for required section headers inside it.
    if has_description_block and description_start is not None and description_block_indent is not None:
        content_indent = description_block_indent + "  "
        for i in range(description_start + 1, block_end):
            line = lines[i]
            if not line.startswith(content_indent):
                continue
            stripped = line.strip("\n").strip()
            if stripped in REQUIRED_SECTIONS:
                found_sections.add(stripped)

    kv = {
        "summary": summary_value or "",
        "has_description_block": "true" if has_description_block else "false",
    }

    return kv, found_sections, block_end


def validate_file(path: Path) -> list[Failure]:
    failures: list[Failure] = []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        failures.append(Failure(path, "<file>", f"unable to read: {exc}"))
        return failures

    lines = text.splitlines(keepends=True)

    is_prometheusrule = any(RE_KIND_PROMETHEUSRULE.match(l) for l in lines)
    is_sloth_slo = any(RE_KIND_SLOTH_SLO.match(l) for l in lines)

    if not (is_prometheusrule or is_sloth_slo):
        return failures

    if is_prometheusrule:
        # Validate each '- alert:' rule has a compliant annotations block.
        i = 0
        while i < len(lines):
            m_alert = RE_ALERT_NAME.match(lines[i])
            if not m_alert:
                i += 1
                continue

            alert_name = m_alert.group("name")
            # Search forward for annotations block within the same rule stanza.
            j = i + 1
            while j < len(lines):
                if RE_ALERT_NAME.match(lines[j]):
                    break
                if RE_ANNOTATIONS_LINE.match(lines[j]):
                    kv, sections, end = _scan_annotations_block(lines, j)

                    summary = kv.get("summary", "")
                    if not summary:
                        failures.append(Failure(path, alert_name, "missing annotations.summary"))
                    elif not RE_SCOPE_PARENS.search(summary):
                        failures.append(Failure(path, alert_name, "annotations.summary must include scope in parentheses"))

                    if kv.get("has_description_block") != "true":
                        failures.append(Failure(path, alert_name, "annotations.description must be a block scalar (description: |)"))
                    else:
                        missing_sections = [s for s in REQUIRED_SECTIONS if s not in sections]
                        if missing_sections:
                            failures.append(
                                Failure(
                                    path,
                                    alert_name,
                                    "annotations.description missing sections: " + ", ".join(missing_sections),
                                )
                            )

                    j = end
                    break

                j += 1

            i = j

    if is_sloth_slo:
        # Validate alerting.annotations blocks.
        # Sloth files are structured differently; look for 'alerting:' then an 'annotations:' block.
        i = 0
        while i < len(lines):
            m_alerting = RE_SLOTH_ALERTING.match(lines[i])
            if not m_alerting:
                i += 1
                continue

            alerting_indent = m_alerting.group("indent")
            # find annotations inside alerting
            j = i + 1
            while j < len(lines):
                line = lines[j]
                # end of alerting block
                if line.strip() and (not line.startswith(alerting_indent + " ")) and not line.startswith(alerting_indent + "\t"):
                    break

                if RE_ANNOTATIONS_LINE.match(line):
                    kv, sections, end = _scan_annotations_block(lines, j)
                    summary = kv.get("summary", "")
                    subject = "sloth.alerting.annotations"

                    if not summary:
                        failures.append(Failure(path, subject, "missing annotations.summary"))
                    elif not RE_SCOPE_PARENS.search(summary):
                        failures.append(Failure(path, subject, "annotations.summary must include scope in parentheses"))

                    if kv.get("has_description_block") != "true":
                        failures.append(Failure(path, subject, "annotations.description must be a block scalar (description: |)"))
                    else:
                        missing_sections = [s for s in REQUIRED_SECTIONS if s not in sections]
                        if missing_sections:
                            failures.append(
                                Failure(
                                    path,
                                    subject,
                                    "annotations.description missing sections: " + ", ".join(missing_sections),
                                )
                            )

                    j = end
                    break

                j += 1

            i = j

    return failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Repo root (defaults to current working directory)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root does not exist: {root}", file=sys.stderr)
        return 2

    yaml_paths: list[Path] = []
    for dirpath, _, filenames in os.walk(root / "kubernetes"):
        for filename in filenames:
            path = Path(dirpath) / filename
            if _is_yaml(path):
                yaml_paths.append(path)

    all_failures: list[Failure] = []
    for path in sorted(yaml_paths):
        all_failures.extend(validate_file(path))

    if all_failures:
        for f in all_failures:
            rel = f.path.relative_to(root)
            print(f"{rel}: {f.subject}: {f.message}")
        return 1

    print("OK: alert annotations match the gold-standard template")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
