#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import yaml

CLUSTER_SCOPE = "cluster"


def load_yaml(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Fail when an Omnigraph cluster.yaml leaves a graph without a policy or lets one actor span client graphs."
    )
    parser.add_argument("cluster_yaml", type=Path)
    parser.add_argument("--client-prefix", default="client-")
    parser.add_argument("--cross-client-actor", action="append", default=[], dest="cross_client_actors")
    parser.add_argument("--protected-branch", default="main")
    return parser.parse_args(argv)


def bundles_by_graph(cluster, bundle_dir, findings):
    bound = {}
    for bundle_name, bundle in (cluster.get("policies") or {}).items():
        policy_path = bundle_dir / bundle["file"]
        if not policy_path.is_file():
            findings.append(f"policy bundle '{bundle_name}' names missing file {bundle['file']}")
            continue
        policy = load_yaml(policy_path)
        for scope in bundle.get("applies_to") or []:
            bound.setdefault(scope, []).append((bundle_name, policy))
    return bound


def actors_granted_by(policy):
    groups = policy.get("groups") or {}
    granted = set()
    for rule in policy.get("rules") or []:
        group = rule["allow"]["actors"]["group"]
        granted.update(groups.get(group, []))
    return granted


def check_every_graph_bound(graph_ids, bound, findings):
    for graph_id in sorted(graph_ids):
        bundles = bound.get(graph_id, [])
        if not bundles:
            findings.append(f"graph '{graph_id}' has no policy bundle: every static bearer token can read it")
        elif len(bundles) > 1:
            names = ", ".join(name for name, _ in bundles)
            findings.append(f"graph '{graph_id}' is bound by more than one bundle: {names}")


def check_protected_branch(client_graphs, bound, branch, findings):
    for graph_id in sorted(client_graphs):
        for bundle_name, policy in bound.get(graph_id, []):
            if branch not in (policy.get("protected_branches") or []):
                findings.append(
                    f"bundle '{bundle_name}' for client graph '{graph_id}' does not protect '{branch}': unprotected-scope writers reach it"
                )


def check_actor_spans(client_graphs, bound, cross_client_actors, findings):
    graphs_per_actor = {}
    for graph_id in client_graphs:
        for _, policy in bound.get(graph_id, []):
            for actor in actors_granted_by(policy):
                graphs_per_actor.setdefault(actor, set()).add(graph_id)
    for actor, graphs in sorted(graphs_per_actor.items()):
        if len(graphs) > 1 and actor not in cross_client_actors:
            findings.append(f"actor '{actor}' is granted on {len(graphs)} client graphs: {', '.join(sorted(graphs))}")


def check_unknown_scopes(graph_ids, bound, findings):
    for scope in sorted(bound):
        if scope != CLUSTER_SCOPE and scope not in graph_ids:
            findings.append(f"policy bound to undeclared graph '{scope}'")


def main(argv):
    args = parse_args(argv)
    cluster = load_yaml(args.cluster_yaml)
    graph_ids = set((cluster.get("graphs") or {}).keys())
    client_graphs = {graph_id for graph_id in graph_ids if graph_id.startswith(args.client_prefix)}
    findings = []
    bound = bundles_by_graph(cluster, args.cluster_yaml.parent, findings)
    check_every_graph_bound(graph_ids, bound, findings)
    check_unknown_scopes(graph_ids, bound, findings)
    check_protected_branch(client_graphs, bound, args.protected_branch, findings)
    check_actor_spans(client_graphs, bound, set(args.cross_client_actors), findings)
    for finding in findings:
        print(f"FAIL {args.cluster_yaml}: {finding}")
    if findings:
        return 1
    print(f"OK {args.cluster_yaml}: {len(graph_ids)} graphs bound, {len(client_graphs)} client graphs isolated")
    return 0


def run(argv):
    try:
        return main(argv)
    except (OSError, yaml.YAMLError, KeyError, TypeError, AttributeError) as error:
        print(f"ERROR cannot evaluate policies: {type(error).__name__}: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
