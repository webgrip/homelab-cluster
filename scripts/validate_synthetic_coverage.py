#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

import yaml

BLACKBOX_DIR = Path("kubernetes/apps/observability/blackbox-exporter/app")
ANNOTATION = re.compile(r"monitoring\.webgrip\.io/synthetic-check:\s*[\"']?([^\"'\s#]+)")
IGNORED_TREES = ("kubernetes/apps/kyverno/",)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Fail when a route claims synthetic coverage from a blackbox Probe that does not exist or cannot run."
    )
    parser.add_argument("root", type=Path)
    return parser.parse_args(argv)


def load_documents(path):
    with open(path, encoding="utf-8") as handle:
        return [document for document in yaml.safe_load_all(handle) if document]


def defined_modules(blackbox):
    release = next(d for d in load_documents(blackbox / "helmrelease.yaml") if d.get("kind") == "HelmRelease")
    return set(release["spec"]["values"]["config"]["modules"])


def listed_resources(blackbox):
    kustomization = load_documents(blackbox / "kustomization.yaml")[0]
    return {Path(entry).name for entry in kustomization.get("resources", [])}


def declared_probes(blackbox):
    probes = {}
    for path in sorted(blackbox.glob("probe-*.yaml")):
        for document in load_documents(path):
            if document.get("kind") == "Probe":
                probes[document["metadata"]["name"]] = (document["spec"]["module"], path.name)
    return probes


def probe_findings(probes, modules, resources):
    findings = []
    for name, (module, filename) in sorted(probes.items()):
        if module not in modules:
            findings.append(f"probe {name}: module {module} is not defined in the blackbox HelmRelease")
        if filename not in resources:
            findings.append(f"probe {name}: {filename} is not listed in the blackbox kustomization, so it never deploys")
    return findings


def annotation_findings(root, probes):
    findings = []
    claims = 0
    for path in sorted((root / "kubernetes/apps").rglob("*.yaml")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(IGNORED_TREES):
            continue
        for match in ANNOTATION.finditer(path.read_text(encoding="utf-8")):
            claims += 1
            if match.group(1) not in probes:
                findings.append(f"{relative}: synthetic-check {match.group(1)!r} names no blackbox Probe")
    return claims, findings


def main(argv):
    args = parse_args(argv)
    blackbox = args.root / BLACKBOX_DIR
    probes = declared_probes(blackbox)
    findings = probe_findings(probes, defined_modules(blackbox), listed_resources(blackbox))
    claims, route_findings = annotation_findings(args.root, probes)
    findings.extend(route_findings)
    for finding in findings:
        print(f"FAIL {finding}")
    if findings:
        return 1
    print(f"OK: {claims} synthetic-check claims resolve to {len(probes)} deployable blackbox probes")
    return 0


def run(argv):
    try:
        return main(argv)
    except (OSError, yaml.YAMLError, KeyError, StopIteration, TypeError, AttributeError) as error:
        print(f"ERROR cannot evaluate synthetic coverage: {type(error).__name__}: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
