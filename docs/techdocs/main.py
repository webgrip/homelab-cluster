"""mkdocs-macros module: build-time cluster inventory (estate item #10).

Renders always-true tables from the GitOps tree itself — no cluster API calls,
deterministic, works in flux-local CI and both engines (Zensical executes
macros modules natively; verified 2026-08-11).
"""
import pathlib

import yaml


class _TagTolerantLoader(yaml.SafeLoader):
    """Material configs and manifests may carry custom tags; load them as None."""


_TagTolerantLoader.add_multi_constructor("", lambda loader, tag, node: None)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
APPS_ROOT = REPO_ROOT / "kubernetes" / "apps"


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
