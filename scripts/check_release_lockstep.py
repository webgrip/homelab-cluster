#!/usr/bin/env python3
"""Fail when the Unfold and Ploeg pins do not name one tested release pair.

Each release publishes a chart and images under one version, so its pins must agree.
With --certified-pair the Ploeg pin must also be the Ploeg release that the pinned
Unfold release names, the pair Unfold tested: the contract bundle in its
apps/unfold/ploeg-release.json, or, before Unfold ADR-0039, the submodule branch in
its .gitmodules.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.error
import urllib.request
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
UNFOLD_RELEASE_TAG_PREFIX = "unfold-v"
UNFOLD_PLOEG_RELEASE_FILE = "apps/unfold/ploeg-release.json"
PLOEG_CONTRACT_BUNDLE = re.compile(rf'"contract"\s*:\s*"[^"]*/ploeg-contract:v?{SEMVER}{DIGEST}"')
PLOEG_SUBMODULE_BRANCH = re.compile(
    r'\[submodule\s+"apps/ploeg"\][^\[]*?^\s*branch\s*=\s*v?(?P<version>\S+)\s*$',
    re.MULTILINE,
)

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

PLOEG = Release(
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
        Pin(
            "claude-runner harness image",
            "kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml",
            rf"image:\s*harbor\.webgrip\.dev/ghcr/ploeg-hq/claude-runner:{SEMVER}{DIGEST}",
        ),
        Pin(
            "claude-runner image",
            "kubernetes/apps/ploeg/ploeg/app/claude-runner/deployment.yaml",
            rf"image:\s*harbor\.webgrip\.dev/ghcr/ploeg-hq/claude-runner:{SEMVER}{DIGEST}",
        ),
    ),
)

RELEASES = (UNFOLD, PLOEG)


def text_in_tree(root: Path, path: str) -> str | None:
    file = root / path
    return file.read_text() if file.is_file() else None


def text_at_revision(root: Path, revision: str, path: str) -> str | None:
    shown = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return shown.stdout if shown.returncode == 0 else None


def read_versions(read, release: Release) -> tuple[dict[str, str], list[str]]:
    versions: dict[str, str] = {}
    problems: list[str] = []
    for pin in release.pins:
        text = read(pin.path)
        if text is None:
            problems.append(f"{release.name} {pin.label}: {pin.path} does not exist")
            continue
        matches = list(re.finditer(pin.pattern, text))
        if len(matches) != 1:
            problems.append(
                f"{release.name} {pin.label}: expected one digest-pinned version in {pin.path}, found {len(matches)}"
            )
            continue
        versions[pin.label] = matches[0].group("version")
    return versions, problems


def release_version(read, release: Release) -> str | None:
    versions, problems = read_versions(read, release)
    distinct = set(versions.values())
    return distinct.pop() if not problems and len(distinct) == 1 else None


def lockstep_failures(root: Path) -> list[str]:
    failures: list[str] = []
    for release in RELEASES:
        versions, problems = read_versions(lambda path: text_in_tree(root, path), release)
        failures.extend(problems)
        if len(set(versions.values())) > 1:
            listed = ", ".join(f"{label} {version}" for label, version in versions.items())
            failures.append(f"{release.name} pins disagree: {listed}")
        elif versions and not problems:
            print(f"OK {release.name} {next(iter(versions.values()))}")
    return failures


def release_file(source: str, unfold_version: str, path: str) -> tuple[str, str | None]:
    url = f"{source.rstrip('/')}/{UNFOLD_RELEASE_TAG_PREFIX}{unfold_version}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return url, response.read().decode()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return url, None
        raise
    except urllib.error.URLError as error:
        if isinstance(error.reason, FileNotFoundError):
            return url, None
        raise


def certified_ploeg_version(source: str, unfold_version: str) -> str:
    url, pin = release_file(source, unfold_version, UNFOLD_PLOEG_RELEASE_FILE)
    if pin is not None:
        found = PLOEG_CONTRACT_BUNDLE.search(pin)
        if found is None:
            raise ValueError(f"{url} names no digest-pinned Ploeg contract bundle")
        return found.group("version")
    url, gitmodules = release_file(source, unfold_version, ".gitmodules")
    if gitmodules is None:
        raise ValueError(
            f"Unfold {unfold_version} publishes neither {UNFOLD_PLOEG_RELEASE_FILE} nor .gitmodules"
        )
    found = PLOEG_SUBMODULE_BRANCH.search(gitmodules)
    if found is None:
        raise ValueError(f"{url} names no branch for the apps/ploeg submodule")
    return found.group("version")


def certified_pair_failures(root: Path, source: str, base: str | None) -> list[str]:
    unfold = release_version(lambda path: text_in_tree(root, path), UNFOLD)
    ploeg = release_version(lambda path: text_in_tree(root, path), PLOEG)
    if unfold is None or ploeg is None:
        return ["the Unfold and Ploeg pins do not each name one release, so the pair cannot be checked"]
    if base is not None:
        base_pair = (
            release_version(lambda path: text_at_revision(root, base, path), UNFOLD),
            release_version(lambda path: text_at_revision(root, base, path), PLOEG),
        )
        if base_pair == (unfold, ploeg):
            print(f"SKIP pair Unfold {unfold} with Ploeg {ploeg}: unchanged from {base}")
            return []
    try:
        certified = certified_ploeg_version(source, unfold)
    except (OSError, ValueError) as error:
        return [f"cannot read the Ploeg release Unfold {unfold} pins: {error}"]
    if certified != ploeg:
        return [
            f"Ploeg {ploeg} is pinned, but Unfold {unfold} was released and tested with Ploeg {certified}; "
            "this stays red until both pins name a pair Unfold released"
        ]
    print(f"OK pair Unfold {unfold} with Ploeg {ploeg}")
    return []


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--certified-pair", action="store_true")
    parser.add_argument(
        "--source",
        default="https://forgejo.webgrip.dev/webgrip/unfold/raw/tag",
        help="base URL that serves the files of tag unfold-v<version>",
    )
    parser.add_argument(
        "--base",
        help="git revision whose pair needs no certification: the pair is checked only when it differs",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    arguments = parse_arguments(argv)
    if arguments.certified_pair:
        failures = certified_pair_failures(arguments.root, arguments.source, arguments.base)
    else:
        failures = lockstep_failures(arguments.root)
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
