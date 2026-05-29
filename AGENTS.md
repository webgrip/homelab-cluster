# AGENTS.md

This repo is GitOps-managed (Flux + HelmRelease + Kustomize) and uses SOPS for secrets.

## Tooling / execution context

Use the repo's `.mise.toml` for operational commands. In practice, prefer `mise exec -- <command>` (or equivalent `mise x -- <command>`) for cluster tooling so the pinned versions and required environment variables are loaded automatically.

This matters especially for:

- `kubectl` (uses repo `KUBECONFIG`)
- `flux`
- `talosctl` (uses repo `TALOSCONFIG`)
- `helm`, `jq`, `cilium`, and related cluster tooling

Do not assume these tools are available or correctly configured outside `mise`, even if a system binary exists on `PATH`.

When embedding shell scripts in Kubernetes manifests that are reconciled by Flux/Kustomize, escape shell variable syntax as `$${...}` so GitOps variable substitution does not eat runtime shell expansions.

## How to work in this repo (broad strokes)

When you (the agent) are asked to make changes here, the intent is usually:

- Make the change in GitOps manifests (HelmRelease/Kustomize/Flux Kustomization) so Flux applies it.
- Keep changes minimal, reversible, and consistent with existing patterns.
- Prefer “wire it up” changes over bespoke YAML (reuse chart features like `existingSecret`, `extraEnvFrom`, `envFromSecret`).

When unsure, optimize for:

- Clear ownership of where config lives (one obvious file to edit).
- No secrets in Git history.
- Simple rollback (revert commit).

## SOPS / secrets policy

SOPS secrets require human action.

- Do not add or modify `*.sops.yaml` files automatically.
- If a change needs a secret, implement the non-secret wiring, and then document:
  - Secret name + namespace
  - required keys
  - a plaintext YAML template the human should encrypt with SOPS
  - any external setup steps (OAuth apps, DNS, API tokens)

Preferred secret wiring patterns:

- Helm values: `existingSecret`, `extraEnvFrom`, `envFromSecret` / `envFromSecrets`.
- Avoid embedding secret values in HelmRelease values.

## Diagnosing cluster issues (how to think)

Treat incidents as a dependency chain and debug from “control plane / GitOps” outward.

1) Confirm Flux is applying what you think it is

- Check Flux reconciliation first: Kustomization/HelmRelease Ready states, recent errors.
- If the manifests aren't being applied, everything else is downstream noise.

1) Confirm the Kubernetes primitives are healthy

- Namespace exists, pods scheduled, deployments progressing, events make sense.
- Look for obvious scheduling blockers: image pulls, missing PVCs, affinity/taints, invalid configs.

1) Confirm storage + network basics

- Storage: PVC bound, Longhorn volumes healthy, no multi-attach loops.
- Network: DNS works from inside cluster, Gateway/HTTPRoute Accepted, services resolve.

1) Confirm app-specific signals

- Logs/traces/metrics: use the observability stack to spot where failure begins.
- Prefer answering: “what changed?” and “what dependency is failing?”

1) Make fixes GitOps-first

- If the fix is configuration, change manifests and let Flux reconcile.
- If a one-off action is unavoidable (e.g., emergency secret creation), record it and convert it to GitOps afterward.

## Grafana dashboards

Grafana is managed by the **Grafana Operator** (`grafana.integreatly.org/v1beta1`). Use CRDs, not ConfigMaps or helm chart values, for all Grafana resources.

### Instance label

Every resource CRD needs `spec.instanceSelector.matchLabels: { grafana.internal/instance: grafana }` to bind to the cluster Grafana instance. Resources in namespaces other than `observability` also need `spec.allowCrossNamespaceImport: true`.

### CRD types and where they live

| CRD | Location | Notes |
|---|---|---|
| `Grafana` | `observability/grafana/app/grafana-instance.yaml` | The instance itself — edit this instead of a HelmRelease |
| `GrafanaFolder` | `observability/grafana/app/folders/<name>.yaml` | One file per folder |
| `GrafanaDatasource` | `observability/grafana/app/datasources/<name>.yaml` | One file per datasource; set `spec.datasource.editable: true` |
| `GrafanaDashboard` (service-specific) | `<namespace>/<service>/app/grafana-dashboard[-name].yaml` | Co-located with the service |
| `GrafanaDashboard` (cross-cutting) | `observability/grafana/app/dashboards/<name>.yaml` | Fleet-wide dashboards with no single owner |
| `GrafanaAlertRuleGroup` | next to the service it alerts on | |
| `GrafanaContactPoint` | `observability/grafana/app/alerting/` | |
| `GrafanaNotificationPolicy` | `observability/grafana/app/alerting/` | |

### Adding a dashboard for a new service

1. Create `kubernetes/apps/<namespace>/<service>/app/grafana-dashboard.yaml`:
   ```yaml
   apiVersion: grafana.integreatly.org/v1beta1
   kind: GrafanaDashboard
   metadata:
     name: <service>
   spec:
     instanceSelector:
       matchLabels:
         grafana.internal/instance: grafana
     allowCrossNamespaceImport: true   # required for non-observability namespaces
     folderUID: <uid-from-taxonomy-below>  # use folderUID for cross-namespace dashboards
     json: |
       { "title": "...", "uid": "...", ... }
   ```
   For dashboards inside `observability` namespace, use `folder: "<Title>"` instead.
2. Add `- ./grafana-dashboard.yaml` to that service's `kustomization.yaml`.
3. Do **not** set `namespace:` — `targetNamespace` in the Flux Kustomization handles it.

### Dashboard folder taxonomy

**Cross-namespace dashboards** (outside `observability`) must use `folderUID` — the operator resolves `folder` and `folderRef` only within the same namespace as the dashboard CRD. `allowCrossNamespaceImport` controls Grafana *instance* targeting, not folder resolution.

**Same-namespace dashboards** (inside `observability/grafana/app/dashboards/`) may use `folder: "<Title>"`.

| Folder title | `folderUID` | Scope |
|---|---|---|
| `Apps` | `afn5acnjfqz9ca` | User-facing workloads |
| `Data` | `bfn5acnv39xc0b` | Databases, message queues |
| `GitHub & Copilot` | `b4e1e0b5-8de6-4224-960b-0cb5d785d039` | GitHub billing and Copilot analytics |
| `Kubernetes` | `ffn5acop222o0e` | Cluster health, workload capacity |
| `Networking` | `54f68a5a-3227-4558-85a0-3f200df26d58` | Cilium, Envoy Gateway |
| `Observability` | `efn5actp9qcqoc` | Prometheus, Alertmanager, Loki, Tempo, Mimir |
| `Platform` | `cfn5acphkecqof` | Flux, cert-manager, Renovate, etcd |
| `Security` | `88988e5b-9560-438e-90e9-cbd01fa258d6` | Kyverno, Falco, Tetragon, Trivy, Cosign |
| `Storage` | `dfn5acvqq8utce` | Longhorn |
| `Synthetics` | `d892add9-e5ce-4616-99e8-9a7c27998b34` | Blackbox probes, k6 canaries |

### Lifecycle

- **Removing a service:** delete the service directory or disable its Flux Kustomization. The `GrafanaDashboard` CRD is removed with it — no separate cleanup needed.
- **Drift protection:** the operator reconciles every `resyncPeriod` (default 10m). Manual changes in the Grafana UI will be reverted.
- **Inventory:** `kubectl get grafanadashboards -A` shows all dashboards with sync status across the cluster.

### What NOT to do

- Do not create dashboard ConfigMaps with `grafana_dashboard: "1"` labels — the sidecar has been removed.
- Do not add datasources to the `Grafana` CRD's `spec.config`; create a `GrafanaDatasource` CRD instead.
- Do not omit `editable: true` on `GrafanaDatasource` resources; otherwise Grafana may treat operator-created datasources as read-only and reject future updates.
- Do not modify `observability/grafana/app/helmrelease.yaml` — it no longer exists; edit `grafana-instance.yaml`.

## Guardrails

- If a change requires a secret, document:
  - the Secret name/namespace
  - the required keys
  - a plaintext YAML template the human should encrypt with SOPS
  - any external setup steps (OAuth app config, DNS, etc.)
- Prefer wiring secrets into workloads via Helm values such as `existingSecret`, `extraEnvFrom`, or `envFromSecret`.
