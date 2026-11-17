#!/usr/bin/env python3
"""Fail when the homelab stops following the signed Unfold candidate channel as one chart.

Flux follows the newest signed 0.x release candidate of the Unfold chart (RFC
rfc-unfold-release-train, P1c), and the chart's own values pin the Unfold and workspace
images by digest, so chart and images move together by construction. An image pin in the
HelmRelease would split them again, a per-architecture tag or an unsigned chart must never
be followed, and the Unfold chart carries the Ploeg chart it was tested with (Unfold
ADR-0043), so no standalone Ploeg HelmRelease may come back next to it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHANNEL = "kubernetes/apps/ploeg/unfold/release/ocirepository.yaml"
RELEASE = "kubernetes/apps/ploeg/unfold/app/helmrelease.yaml"
RETIRED_PINNED_CHANNEL = "kubernetes/apps/ploeg/unfold/app/ocirepository.yaml"
STANDALONE_PLOEG_HELMRELEASE = "kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml"

CHART_URL = "oci://ghcr.io/unfold-hq/charts/unfold"
ISSUER = "https://token.actions.githubusercontent.com"
RELEASE_WORKFLOW = "https://github.com/unfold-hq/unfold/.github/workflows/on_release_published.yml@refs/tags/unfold-v"

FOLLOWED_TAGS = ("0.4.0-rc.136", "0.5.0-rc.1", "0.12.3-rc.40")
REFUSED_TAGS = ("0.4.0-rc.136-arm64", "0.4.0-rc.136-amd64", "0.4.0", "1.0.0-rc.1", "latest", "sha256-1c79.sig")
SIGNER_SUBJECTS = (RELEASE_WORKFLOW + "0.4.0-rc.136",)
FOREIGN_SUBJECTS = (
    RELEASE_WORKFLOW + "0.4.0",
    "https://github.com/unfold-hq/unfold/.github/workflows/ci.yml@refs/tags/unfold-v0.4.0-rc.136",
    "https://github.com/someone/unfold/.github/workflows/on_release_published.yml@refs/tags/unfold-v0.4.0-rc.136",
    RELEASE_WORKFLOW + "0.4.0-rc.136@refs/heads/main",
)


def scalar(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*-?\s*{key}:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value.replace("\\\\", "\\") if match.group(1).startswith('"') else value


def pattern_failures(label: str, pattern: str | None, accepted: tuple[str, ...], refused: tuple[str, ...]) -> list[str]:
    if not pattern:
        return [f"{CHANNEL}: {label} is missing"]
    try:
        compiled = re.compile(pattern)
    except re.error as error:
        return [f"{CHANNEL}: {label} {pattern!r} is not a regular expression: {error}"]
    failures = [f"{CHANNEL}: {label} {pattern!r} refuses {value}" for value in accepted if not compiled.search(value)]
    failures += [f"{CHANNEL}: {label} {pattern!r} accepts {value}" for value in refused if compiled.search(value)]
    return failures


def channel_failures(root: Path) -> list[str]:
    file = root / CHANNEL
    if not file.is_file():
        return [f"{CHANNEL} does not exist"]
    text = file.read_text()
    failures: list[str] = []
    if scalar(text, "url") != CHART_URL:
        failures.append(f"{CHANNEL}: url must be {CHART_URL}")
    if not scalar(text, "semver"):
        failures.append(f"{CHANNEL}: ref.semver is missing, so Flux follows no channel")
    for pinned in ("tag", "digest"):
        if scalar(text, pinned):
            failures.append(f"{CHANNEL}: ref.{pinned} pins one chart; a hold is a '!=' exclusion in ref.semver (RFC D12)")
    failures += pattern_failures("ref.semverFilter", scalar(text, "semverFilter"), FOLLOWED_TAGS, REFUSED_TAGS)
    if scalar(text, "provider") != "cosign":
        failures.append(f"{CHANNEL}: verify.provider must be cosign, or Flux follows unsigned charts (RFC D13)")
    failures += pattern_failures("verify issuer", scalar(text, "issuer"), (ISSUER,), (ISSUER + ".evil.example", "https://accounts.google.com"))
    failures += pattern_failures("verify subject", scalar(text, "subject"), SIGNER_SUBJECTS, FOREIGN_SUBJECTS)
    return failures


def release_failures(root: Path) -> list[str]:
    file = root / RELEASE
    if not file.is_file():
        return [f"{RELEASE} does not exist"]
    text = file.read_text()
    failures: list[str] = []
    if not re.search(r"chartRef:\s*\n\s*kind:\s*OCIRepository\s*\n\s*name:\s*unfold\s*\n\s*namespace:\s*flux-system\s*\n", text):
        failures.append(f"{RELEASE}: chartRef must name OCIRepository flux-system/unfold, the signed candidate channel")
    for image in ("unfold", "unfold-agent"):
        if re.search(rf"repository:\s*\S+/unfold-hq/{image}\s*\n\s*(tag|digest):", text):
            failures.append(f"{RELEASE}: the {image} image pins a tag or digest; the chart's own values must decide it")
    if re.search(r"^\s*workspaceImage:\s*\S", text, re.MULTILINE):
        failures.append(f"{RELEASE}: workspaceImage overrides the chart's workspace image; set workspaceAgentImage.repository only")
    if (root / RETIRED_PINNED_CHANNEL).exists():
        failures.append(f"{RETIRED_PINNED_CHANNEL} exists next to the candidate channel; two chart sources would disagree")
    return failures


def single_ploeg_owner_failures(root: Path) -> list[str]:
    if (root / STANDALONE_PLOEG_HELMRELEASE).exists():
        return [
            f"{STANDALONE_PLOEG_HELMRELEASE} exists, but the Unfold release owns Ploeg's objects; "
            "two Helm releases would fight over them"
        ]
    return []


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    root = parse_arguments(argv).root
    failures = channel_failures(root) + release_failures(root) + single_ploeg_owner_failures(root)
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if not failures:
        print("OK Unfold follows the signed candidate channel as one chart, and only the Unfold release runs Ploeg")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
