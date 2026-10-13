#!/usr/bin/env python3
"""Fail when a first-party release's chart and image pins name different versions.

Unfold and Ploeg each publish a chart and images under one version, and Renovate
automerges their release PRs. A release whose chart reached Harbor before its images
(or whose images failed the CVE gate) yields a PR that moves only part of the pins;
this check keeps such a PR red so it never merges.
"""

from __future__ import annotations

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

RELEASES = (
    Release(
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
    ),
    Release(
        "Ploeg",
        (
            Pin(
                "chart",
                "kubernetes/apps/ploeg/ploeg/app/ocirepository.yaml",
                rf"url:\s*oci://harbor\.webgrip\.dev/ghcr/ploeg-hq/charts/ploeg\s*\n(?:.*\n)*?\s*tag:\s*[\"']?{SEMVER}[\"']?\s*\n\s*digest:\s*sha256:[a-f0-9]{{64}}",
            ),
            Pin(
                "ploegd image",
                "kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml",
                rf"repository:\s*harbor\.webgrip\.dev/ghcr/ploeg-hq/ploegd\s*\n\s*tag:\s*[\"']?{SEMVER}{DIGEST}[\"']?",
            ),
            Pin(
                "ploeg-mcp image",
                "kubernetes/apps/ploeg/ploeg/app/mcp/deployment.yaml",
                rf"image:\s*harbor\.webgrip\.dev/ghcr/ploeg-hq/ploegd:{SEMVER}{DIGEST}",
            ),
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


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    failures: list[str] = []
    for release in RELEASES:
        versions, problems = read_versions(root, release)
        failures.extend(problems)
        if len(set(versions.values())) > 1:
            listed = ", ".join(f"{label} {version}" for label, version in versions.items())
            failures.append(f"{release.name} pins disagree: {listed}")
        elif versions and not problems:
            print(f"OK {release.name} {next(iter(versions.values()))}")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
