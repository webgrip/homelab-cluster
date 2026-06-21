#!/usr/bin/env python3

"""Guard Grafana alert-rule server-side expression (SSE) shape.

Lightweight *text* validator (stdlib only, no YAML deps) so it runs anywhere CI
does, matching scripts/validate_alert_annotations.py.

Why this exists
---------------
All 16 GrafanaAlertRuleGroup SLO rules shipped a `threshold` SSE node WITHOUT the
`expression:` field that points at the input query's refId. Grafana then errored on
every evaluation:

    [sse.parseError] failed to parse expression [threshold]:
    no variable specified to reference for refId threshold

…and the entire SLO/SLA alerting layer was silently broken for ~3 weeks. kubeconform
and the Grafana operator CRD do NOT validate model internals (the model is a
preserve-unknown-fields blob), so this passed every existing gate. This guard closes
that hole. See ADR-0030.

Invariant enforced
------------------
For every `kind: GrafanaAlertRuleGroup`, each SSE node whose model `type:` is one of
{threshold, math, reduce} MUST have a sibling `expression:` key (the bare refId of its
input query). Classic-condition nodes (`type: classic_conditions`) are exempt — they
carry their input inside `conditions[].query`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

RE_KIND_GRAFANA_ALERT = re.compile(r"^kind:\s*GrafanaAlertRuleGroup\s*$")
RE_YAML_FILE = re.compile(r".*\.ya?ml$")

# SSE expression types that require a top-level `expression:` pointer.
EXPR_TYPES = {"threshold", "math", "reduce"}
RE_TYPE_LINE = re.compile(r"^(?P<indent>\s*)type:\s*(?P<type>\S+)\s*$")
RE_KEY_LINE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.-]+):")
# Nearest enclosing rule uid, for friendlier error messages. Must be a rule-list
# item (`- uid: slo-...`) — NOT a nested `uid:` such as a datasource's.
RE_UID_LINE = re.compile(r"^\s*-\s+uid:\s*(?P<uid>\S+)\s*$")


@dataclass
class Failure:
    path: Path
    subject: str
    message: str


def _is_yaml(path: Path) -> bool:
    return bool(RE_YAML_FILE.fullmatch(path.name))


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _nearest_uid(lines: list[str], idx: int) -> str:
    for i in range(idx, -1, -1):
        m = RE_UID_LINE.match(lines[i])
        if m:
            return m.group("uid")
    return "<unknown-rule>"


def _sibling_keys(lines: list[str], type_idx: int, indent: int) -> set[str]:
    """Collect mapping-sibling keys of the `type:` line (same indentation, same
    enclosing mapping). Scans up and down, stopping when indentation drops below
    `indent` on a non-blank line (that marks the mapping boundary)."""
    keys: set[str] = set()

    for direction in (1, -1):
        i = type_idx + direction
        while 0 <= i < len(lines):
            line = lines[i]
            if line.strip() == "":
                i += 1 if direction == 1 else -1
                continue
            if _indent_of(line) < indent:
                break
            if _indent_of(line) == indent:
                km = RE_KEY_LINE.match(line)
                if km:
                    keys.add(km.group("key"))
            i += 1 if direction == 1 else -1

    return keys


def validate_file(path: Path) -> list[Failure]:
    failures: list[Failure] = []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        return [Failure(path, "<file>", f"unable to read: {exc}")]

    lines = text.splitlines()
    if not any(RE_KIND_GRAFANA_ALERT.match(l) for l in lines):
        return failures

    for idx, line in enumerate(lines):
        m = RE_TYPE_LINE.match(line)
        if not m:
            continue
        sse_type = m.group("type")
        if sse_type not in EXPR_TYPES:
            continue

        indent = len(m.group("indent"))
        siblings = _sibling_keys(lines, idx, indent)
        if "expression" not in siblings:
            uid = _nearest_uid(lines, idx)
            failures.append(
                Failure(
                    path,
                    uid,
                    f"SSE node 'type: {sse_type}' (line {idx + 1}) is missing the "
                    f"'expression:' field → Grafana errors 'no variable specified to "
                    f"reference for refId ...'. Add 'expression: <input-refId>'.",
                )
            )

    return failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".", help="Repo root")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"error: root does not exist: {root}", file=sys.stderr)
        return 2

    yaml_paths: list[Path] = []
    for dirpath, _, filenames in os.walk(root / "kubernetes"):
        for filename in filenames:
            p = Path(dirpath) / filename
            if _is_yaml(p):
                yaml_paths.append(p)

    all_failures: list[Failure] = []
    for path in sorted(yaml_paths):
        all_failures.extend(validate_file(path))

    if all_failures:
        for f in all_failures:
            print(f"{f.path.relative_to(root)}: {f.subject}: {f.message}")
        return 1

    print("OK: all Grafana alert-rule SSE nodes carry an 'expression:' pointer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
