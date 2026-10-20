#!/usr/bin/env python3
"""Fail when the Unfold pins do not name one release, or when a second Helm release could own Ploeg.

Each Unfold release publishes a chart and images under one version, so its pins must agree.
The Unfold chart carries the Ploeg chart it was tested with (Unfold ADR-0043), so no standalone
Ploeg HelmRelease may come back next to it.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Pin:
    label: str
    path: str
    pattern: str


@dataclass(frozen=True)
class Release:
    name: str
    pins: tuple[Pin, ...]


SEMVER = r"(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)"
DIGEST = r"@sha256:[a-f0-9]{64}"
STANDALONE_PLOEG_HELMRELEASE = "kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml"

UNFOLD = Release(
    "Unfold",
    (
        Pin(
            "chart",
            "kubernetes/apps/ploeg/unfold/app/ocirepository.yaml",
            rf"url:\s*oci://harbor\.webgrip\.dev/webgrip/charts/unfold\s*\n(?:.*\n)*?\s*tag:\s*[\"']?{SEMVER}[\"']?\s*\n\s*digest:\s*sha256:[a-f0-9]{{64}}",
        ),
        Pin(
            "image",
            "kubernetes/apps/ploeg/unfold/app/helmrelease.yaml",
            rf"repository:\s*harbor\.webgrip\.dev/webgrip/unfold\s*\n\s*tag:\s*[\"']?{SEMVER}[\"']?\s*\n\s*digest:\s*[\"']?sha256:[a-f0-9]{{64}}",
        ),
        Pin(
            "workspace image",
            "kubernetes/apps/ploeg/unfold/app/helmrelease.yaml",
            rf"workspaceImage:\s*[\"']?harbor\.webgrip\.dev/webgrip/unfold-agent:{SEMVER}{DIGEST}",
        ),
    ),
)


def read_versions(root: Path, release: Release) -> tuple[dict[str, str], list[str]]:
    versions: dict[str, str] = {}
    problems: list[str] = []
    for pin in release.pins:
        file = root / pin.path
        if not file.is_file():
            problems.append(f"{release.name} {pin.label}: {pin.path} does not exist")
            continue
        matches = list(re.finditer(pin.pattern, file.read_text()))
        if len(matches) != 1:
            problems.append(
                f"{release.name} {pin.label}: expected one digest-pinned version in {pin.path}, found {len(matches)}"
            )
            continue
        versions[pin.label] = matches[0].group("version")
    return versions, problems


def lockstep_failures(root: Path) -> list[str]:
    versions, failures = read_versions(root, UNFOLD)
    if len(set(versions.values())) > 1:
        listed = ", ".join(f"{label} {version}" for label, version in versions.items())
        failures.append(f"{UNFOLD.name} pins disagree: {listed}")
    elif versions and not failures:
        print(f"OK {UNFOLD.name} {next(iter(versions.values()))}")
    return failures


def single_ploeg_owner_failures(root: Path) -> list[str]:
    if (root / STANDALONE_PLOEG_HELMRELEASE).exists():
        return [
            f"{STANDALONE_PLOEG_HELMRELEASE} exists, but the Unfold release owns Ploeg's objects; "
            "two Helm releases would fight over them"
        ]
    print("OK Ploeg runs only in the Unfold release")
    return []


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    root = parse_arguments(argv).root
    failures = lockstep_failures(root) + single_ploeg_owner_failures(root)
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
