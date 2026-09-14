"""mkdocs-macros module: build-time cluster inventory (estate item #10).

Renders always-true tables from the GitOps tree itself — no cluster API calls,
deterministic, works in flux-local CI and both engines (Zensical executes
macros modules natively; verified 2026-08-11).
"""
import pathlib
import re

import yaml


class _TagTolerantLoader(yaml.SafeLoader):
    """Material configs and manifests may carry custom tags; load them as None."""


_TagTolerantLoader.add_multi_constructor("", lambda loader, tag, node: None)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
APPS_ROOT = REPO_ROOT / "kubernetes" / "apps"
BROKER_MODULE = APPS_ROOT / "security" / "access-plane" / "tofu" / "broker" / "applications.tf"
LAUNCH_URL_HOST = re.compile(r'launch_url\s*=\s*"https://([^/"]+)')


def _docs(path: pathlib.Path):
    try:
        for doc in yaml.load_all(path.read_text(), Loader=_TagTolerantLoader):
            if isinstance(doc, dict):
                yield doc
    except Exception:  # noqa: BLE001 — a malformed manifest must not kill the docs build
        return


def define_env(env):
    @env.macro
    def app_inventory():
        """Namespace | app | dependsOn table from every kubernetes/apps ks.yaml."""
        rows = []
        for ks in sorted(APPS_ROOT.glob("*/*/ks.yaml")):
            ns, app = ks.parent.parent.name, ks.parent.name
            for doc in _docs(ks):
                if doc.get("kind") != "Kustomization":
                    continue
                name = doc.get("metadata", {}).get("name", app)
                deps = ", ".join(
                    d.get("name", "?") for d in doc.get("spec", {}).get("dependsOn", []) or []
                )
                rows.append(f"| `{ns}` | [{name}](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/{ks.parent.relative_to(REPO_ROOT)}) | {deps or '—'} |")
        return "\n".join(
            ["| Namespace | Kustomization | dependsOn |", "| --- | --- | --- |", *rows]
        )

    @env.macro
    def helmrelease_inventory():
        """App | chart/source | version table from every HelmRelease in the tree."""
        rows = []
        for hr in sorted(APPS_ROOT.glob("*/*/app/*.yaml")):
            for doc in _docs(hr):
                if doc.get("kind") != "HelmRelease":
                    continue
                meta, spec = doc.get("metadata", {}), doc.get("spec", {})
                chart_spec = (spec.get("chart") or {}).get("spec", {})
                chart = chart_spec.get("chart") or (spec.get("chartRef") or {}).get("name", "?")
                version = chart_spec.get("version", "—")
                rows.append(
                    f"| `{hr.parent.parent.parent.name}` | {meta.get('name', '?')} | {chart} | {version} |"
                )
        return "\n".join(
            ["| Namespace | HelmRelease | Chart | Version |", "| --- | --- | --- | --- |", *rows]
        )

    @env.macro
    def access_matrix():
        """Who can do what, computed from the access-plane model at build time."""
        return _access_matrix()


MODEL_ROOT = APPS_ROOT / "security" / "access-plane" / "model"
RISK_MARK = {"critical": "‼", "high": "!", "medium": "·", "low": " "}


def _model(name: str, key: str):
    return yaml.safe_load((MODEL_ROOT / f"{name}.yaml").read_text())[key]


def _held(person: dict, roles: dict, capabilities: dict, today) -> dict[str, str]:
    held: dict[str, str] = {}
    for grant in roles[person["role"]]["grants"]:
        held[grant["capability"]] = "R"
    for grant in person.get("grants", []):
        until = grant["until"]
        if until != "none" and str(until) < str(today):
            continue
        held[grant["capability"]] = "D"
    superseded = {s for c in held for s in capabilities[c].get("supersedes", [])}
    return {c: how for c, how in held.items() if c not in superseded}


def _reachable(held: dict[str, str], capabilities: dict) -> dict[str, tuple[str, bool]]:
    reached: dict[str, tuple[str, bool]] = {}
    frontier = [(c, c, False) for c in held]
    while frontier:
        current, origin, collusion = frontier.pop(0)
        for edge in capabilities[current].get("escalates_to", []):
            target = edge["capability"]
            needs_collusion = collusion or edge.get("requires") == "collusion"
            if target in held:
                continue
            if target in reached and (not reached[target][1] or needs_collusion):
                continue
            reached[target] = (origin, needs_collusion)
            frontier.append((target, origin, needs_collusion))
    return reached


def _broker_hosts() -> set[str]:
    hosts = LAUNCH_URL_HOST.findall(BROKER_MODULE.read_text())
    return {host.replace("${var.SECRET_DOMAIN}", "${SECRET_DOMAIN}") for host in hosts}


def _route_authentication(app_dir: pathlib.Path, route_name: str, hosts: set[str]) -> str:
    for sibling in app_dir.glob("*.yaml"):
        for other in _docs(sibling):
            if other.get("kind") != "SecurityPolicy":
                continue
            spec = other.get("spec", {})
            targets = spec.get("targetRefs", []) or []
            if not any(t.get("name") == route_name for t in targets):
                continue
            if "oidc" in spec:
                return "broker, at the gateway"
            if "basicAuth" in spec:
                return "basic auth, at the gateway"
            return "gateway policy"
    if hosts & _broker_hosts():
        return "broker, in the application"
    return "none"


def _routed_surfaces() -> list[str]:
    rows = []
    for route in sorted(APPS_ROOT.glob("*/*/app/*.yaml")):
        app_dir = route.parent
        for doc in _docs(route):
            if doc.get("kind") != "HTTPRoute":
                continue
            spec = doc.get("spec", {})
            hostnames = set(spec.get("hostnames", []) or [])
            hosts = ", ".join(sorted(hostnames))
            gateways = ", ".join(p.get("name", "?") for p in spec.get("parentRefs", []) or [])
            authn = _route_authentication(app_dir, doc.get("metadata", {}).get("name", "?"), hostnames)
            rows.append(f"| `{app_dir.parent.parent.name}` | {hosts} | {gateways} | {authn} |")
    return rows


def _via(held: dict[str, str], capabilities: dict, target: str) -> str:
    for capability in held:
        for edge in capabilities[capability].get("escalates_to", []):
            if edge["capability"] == target:
                return edge["via"]
    return "transitively"


def _access_matrix() -> str:
    import datetime as dt

    capabilities = _model("capabilities", "capabilities")
    roles = _model("roles", "roles")
    projects = _model("projects", "projects")
    people = _model("people", "people")
    today = dt.date.today()
    humans = [p for p in people if p["kind"] != "machine" and p["status"] == "active"]
    machines = [p for p in people if p["kind"] == "machine"]
    held = {p["id"]: _held(p, roles, capabilities, today) for p in humans}
    reach = {p["id"]: _reachable(held[p["id"]], capabilities) for p in humans}

    out = ["## Principals", "", "| Person | Role | Projects | Declared | Reachable | Reviewed |", "| --- | --- | --- | --- | --- | --- |"]
    for p in humans:
        out.append(f"| {p['email']} | `{p['role']}` | {', '.join(p['projects'])} | {len(held[p['id']])} | {len(reach[p['id']])} | {p['reviewed']} |")

    out += ["", "### Machine principals", "", "Inventory, never granted a human capability.", "", "| Id | What | Owner |", "| --- | --- | --- |"]
    for m in machines:
        out.append(f"| `{m['id']}` | {m['purpose']} | {m['owner']} |")

    out += ["", "## Capability matrix", "", "`D` dated grant · `R` through the role · `→` reachable without a grant · `~` reachable only with a second principal", ""]
    out.append("| Capability | Risk | " + " | ".join(p["id"] for p in humans) + " |")
    out.append("| --- | --- | " + " | ".join("---" for _ in humans) + " |")
    for name, cap in sorted(capabilities.items()):
        cells = []
        for p in humans:
            if name in held[p["id"]]:
                cells.append(held[p["id"]][name])
            elif name in reach[p["id"]]:
                cells.append("~" if reach[p["id"]][name][1] else "→")
            else:
                cells.append("")
        out.append(f"| {RISK_MARK[cap['risk']]} `{name}` | {cap['risk']} | " + " | ".join(cells) + " |")

    out += ["", "## How access is reached without being granted", "", "| Person | Reaches | From | Via |", "| --- | --- | --- | --- |"]
    for p in humans:
        for target, (origin, collusion) in sorted(reach[p["id"]].items()):
            suffix = " (needs a second principal)" if collusion else ""
            out.append(f"| {p['id']} | `{target}` | `{origin}` | {_via(held[p['id']], capabilities, target)}{suffix} |")

    out += ["", "## Capability catalogue", "", "| Capability | Risk | Projects onto | Escalates to |", "| --- | --- | --- | --- |"]
    for name, cap in sorted(capabilities.items()):
        planes = ", ".join(sorted((cap.get("projects") or {}).keys()))
        if not planes:
            planes = "derived" if cap.get("derived") else "break-glass" if cap.get("break_glass") else "nothing yet"
        edges = ", ".join(f"`{e['capability']}`" for e in cap.get("escalates_to", [])) or "—"
        out.append(f"| `{name}` | {cap['risk']} | {planes} | {edges} |")

    out += ["", "## Break-glass census", "", "| Credential | Risk | Alert | Holders |", "| --- | --- | --- | --- |"]
    for name, cap in sorted(capabilities.items()):
        if not cap.get("break_glass"):
            continue
        holders = ", ".join(p["id"] for p in humans if name in held[p["id"]]) or "nobody declared"
        out.append(f"| `{name}` | {cap['risk']} | {cap.get('alert', 'none')} | {holders} |")

    out += ["", "## Projects and what they own", "", "| Project | Owner | Namespaces | Repositories | Reviewed |", "| --- | --- | --- | --- | --- |"]
    for name, project in projects.items():
        out.append(f"| `{name}` | {project['owner']} | {', '.join(project['namespaces']) or '—'} | {', '.join(project['repos']) or '—'} | {project['reviewed']} |")

    out += ["", "## Routed surfaces, and what authenticates them", "", "Derived from every HTTPRoute and SecurityPolicy in the tree; `none` is a finding.", "", "| Namespace | Hostnames | Gateway | Authentication |", "| --- | --- | --- | --- |", *_routed_surfaces()]
    return "\n".join(out)
