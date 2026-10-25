#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import yaml

ACCESS_LABEL = "mcp.webgrip.io/access"
GATEWAY_ONLY = "litellm-gateway-only"
LITELLM_CONFIG = Path("kubernetes/apps/ai/litellm/app/litellm-config.configmap.yaml")
LITELLM_PEER = {
    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ai"}},
    "podSelector": {"matchLabels": {"app.kubernetes.io/name": "litellm"}},
}
READ_ONLY_ACCESS_GROUPS = {"observability", "brain-dogfood"}
CREDENTIAL_AUTH_TYPES = {"bearer_token", "api_key", "token"}
ENVIRONMENT_REFERENCE = "os.environ/"
ROUTE_KINDS = {"HTTPRoute", "GRPCRoute", "TCPRoute", "TLSRoute", "UDPRoute"}
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}
IGNORED_TREES = ("kubernetes/apps/kyverno/tests/",)


class TolerantLoader(yaml.SafeLoader):
    pass


TolerantLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Fail when an MCP server marked litellm-gateway-only, or one LiteLLM serves to a write-capable access group, is reachable other than through LiteLLM, unless that server demands a credential LiteLLM reads from its environment."
    )
    parser.add_argument("root", type=Path)
    return parser.parse_args(argv)


def namespace_of(root, path, document):
    declared = (document.get("metadata") or {}).get("namespace")
    if declared:
        return declared
    return path.relative_to(root / "kubernetes/apps").parts[0]


def manifests(root):
    for path in sorted((root / "kubernetes/apps").rglob("*.yaml")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(IGNORED_TREES):
            continue
        with open(path, encoding="utf-8") as handle:
            for document in yaml.load_all(handle, Loader=TolerantLoader):
                if isinstance(document, dict) and document.get("kind"):
                    yield relative, namespace_of(root, path, document), document


def selector_matches(selector, labels):
    if selector is None:
        return False
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expression in selector.get("matchExpressions") or []:
        key, operator, values = expression["key"], expression["operator"], expression.get("values") or []
        present = key in labels
        if operator == "In" and not (present and labels[key] in values):
            return False
        if operator == "NotIn" and present and labels[key] in values:
            return False
        if operator == "Exists" and not present:
            return False
        if operator == "DoesNotExist" and present:
            return False
    return True


def gateway_only_services(documents):
    return {
        (namespace, document["metadata"]["name"]): (relative, document)
        for relative, namespace, document in documents
        if document["kind"] == "Service"
        and (document["metadata"].get("labels") or {}).get(ACCESS_LABEL) == GATEWAY_ONLY
    }


def pod_labels_behind(service, namespace, documents):
    selector = {"matchLabels": service["spec"].get("selector") or {}}
    return [
        (relative, document["spec"]["template"]["metadata"].get("labels") or {})
        for relative, workload_namespace, document in documents
        if document["kind"] in WORKLOAD_KINDS
        and workload_namespace == namespace
        and selector["matchLabels"]
        and selector_matches(selector, document["spec"]["template"]["metadata"].get("labels") or {})
    ]


MCP_PATH = "/mcp"


def path_reaches_mcp(path):
    kind = path.get("type", "PathPrefix")
    value = path.get("value", "/")
    if kind == "Exact":
        return value == MCP_PATH
    if kind == "PathPrefix":
        prefix = value.rstrip("/")
        return prefix == "" or MCP_PATH == prefix or MCP_PATH.startswith(prefix + "/")
    return True


def rule_reaches_mcp(document, rule):
    if document["kind"] != "HTTPRoute":
        return True
    matches = rule.get("matches") or [{}]
    return any(path_reaches_mcp(match.get("path") or {}) for match in matches)


def route_findings(gateway_only, credential_gated, documents):
    findings = []
    for relative, namespace, document in documents:
        if document["kind"] not in ROUTE_KINDS:
            continue
        for rule in document.get("spec", {}).get("rules") or []:
            for backend in rule.get("backendRefs") or []:
                key = (backend.get("namespace") or namespace, backend.get("name"))
                if key in gateway_only or (key in credential_gated and rule_reaches_mcp(document, rule)):
                    findings.append(f"{relative}: {document['kind']} {document['metadata']['name']} routes outside traffic to the MCP endpoint of in-cluster-only service {key[1]}.{key[0]}")
    return findings


def exposure_findings(services):
    return [
        f"{relative}: in-cluster-only MCP service {name}.{namespace} is type {service['spec']['type']}"
        for (namespace, name), (relative, service) in sorted(services.items())
        if service["spec"].get("type", "ClusterIP") != "ClusterIP"
    ]


def ingress_peer_findings(policy, relative, target):
    findings = []
    for rule in policy["spec"].get("ingress") or []:
        peers = rule.get("from")
        if not peers:
            findings.append(f"{relative}: NetworkPolicy {policy['metadata']['name']} admits every source to {target}")
            continue
        for peer in peers:
            if peer != LITELLM_PEER:
                findings.append(f"{relative}: NetworkPolicy {policy['metadata']['name']} admits {peer} to {target}, not only LiteLLM")
    return findings


def policy_findings(services, documents):
    findings = []
    for (namespace, name), (relative, service) in sorted(services.items()):
        workloads = pod_labels_behind(service, namespace, documents)
        if not workloads:
            findings.append(f"{relative}: gateway-only service {name}.{namespace} selects no workload")
            continue
        for workload_relative, labels in workloads:
            if labels.get(ACCESS_LABEL) != GATEWAY_ONLY:
                findings.append(f"{workload_relative}: pods behind {name}.{namespace} lack {ACCESS_LABEL}={GATEWAY_ONLY}")
            admitting_litellm = False
            for policy_relative, policy_namespace, policy in documents:
                if policy_namespace != namespace or policy["kind"] not in {"NetworkPolicy", "CiliumNetworkPolicy"}:
                    continue
                spec = policy.get("spec") or {}
                if policy["kind"] == "CiliumNetworkPolicy":
                    if selector_matches(spec.get("endpointSelector"), labels) and spec.get("ingress"):
                        findings.append(f"{policy_relative}: CiliumNetworkPolicy {policy['metadata']['name']} admits ingress to {name}.{namespace}")
                    continue
                if "Ingress" not in (spec.get("policyTypes") or ["Ingress"]):
                    continue
                if not selector_matches(spec.get("podSelector"), labels):
                    continue
                findings.extend(ingress_peer_findings(policy, policy_relative, f"{name}.{namespace}"))
                admitting_litellm = admitting_litellm or any(
                    LITELLM_PEER in (rule.get("from") or []) for rule in spec.get("ingress") or []
                )
            if not admitting_litellm:
                findings.append(f"{namespace}: no NetworkPolicy admits LiteLLM to {name}.{namespace}, so the gateway cannot reach it")
    return findings


def litellm_http_servers(root):
    configmap = yaml.safe_load((root / LITELLM_CONFIG).read_text(encoding="utf-8"))
    config = yaml.safe_load(configmap["data"]["config.yaml"])
    for name, server in (config.get("mcp_servers") or {}).items():
        if server.get("transport") == "http":
            yield name, server


def service_of(url):
    host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
    parts = host.split(".")
    if len(parts) >= 3 and parts[2] == "svc":
        return parts[1], parts[0]
    return None


def presents_credential(server):
    token = server.get("authentication_token")
    return (
        server.get("auth_type") in CREDENTIAL_AUTH_TYPES
        and isinstance(token, str)
        and token.startswith(ENVIRONMENT_REFERENCE)
        and len(token) > len(ENVIRONMENT_REFERENCE)
    )


def write_capable_servers(root):
    for name, server in litellm_http_servers(root):
        groups = set(server.get("access_groups") or [])
        if not groups <= READ_ONLY_ACCESS_GROUPS:
            yield name, server, groups


def credential_gated_services(root, documents):
    services = {
        (namespace, document["metadata"]["name"]): (relative, document)
        for relative, namespace, document in documents
        if document["kind"] == "Service"
    }
    return {
        target: services[target]
        for _, server, _ in write_capable_servers(root)
        if presents_credential(server)
        and (target := service_of(server["url"])) in services
    }


def litellm_findings(root, services):
    findings = []
    for name, server, groups in write_capable_servers(root):
        if presents_credential(server):
            continue
        target = service_of(server["url"])
        if target not in services:
            findings.append(
                f"{LITELLM_CONFIG}: mcp_servers.{name} serves write-capable groups {sorted(groups - READ_ONLY_ACCESS_GROUPS)} from {server['url']}, which is not a {ACCESS_LABEL}={GATEWAY_ONLY} service and is not sent a credential from LiteLLM's environment"
            )
    return findings


def main(argv):
    args = parse_args(argv)
    documents = list(manifests(args.root))
    services = gateway_only_services(documents)
    gated = credential_gated_services(args.root, documents)
    findings = litellm_findings(args.root, services)
    findings += route_findings(services, gated, documents)
    findings += exposure_findings({**services, **gated})
    findings += policy_findings(services, documents)
    for finding in findings:
        print(f"FAIL {finding}")
    if findings:
        return 1
    print(f"OK: {len(services)} gateway-only MCP services are reachable only through LiteLLM; {len(gated)} write-capable MCP services demand LiteLLM's credential and keep /mcp inside the cluster")
    return 0


def run(argv):
    try:
        return main(argv)
    except (OSError, yaml.YAMLError, KeyError, IndexError, TypeError, AttributeError) as error:
        print(f"ERROR cannot evaluate MCP gateway-only exposure: {type(error).__name__}: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
