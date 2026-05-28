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

Dashboards are co-located with the service they monitor, not centralised under `observability/grafana/`.

**How discovery works:** Grafana's sidecar is configured with `searchNamespace: ALL`. Any ConfigMap with label `grafana_dashboard: "1"` in any namespace is picked up automatically. The `grafana_folder` annotation on the ConfigMap controls which Grafana folder it appears in.

**Where to put a dashboard:**

| Scope | Location |
|---|---|
| Service-specific (monitors one app) | `kubernetes/apps/<namespace>/<service>/app/grafana-dashboard[-name].yaml` |
| Cross-cutting / fleet-wide | `kubernetes/apps/observability/grafana/app/dashboards/` |

Cross-cutting dashboards (those that stay central) are things like cluster health, workloads capacity, fleet-wide PVC view, the LGTM stack health overview, and GitHub/Copilot billing — dashboards that have no single owning service.

**Adding a dashboard for a new service:**

1. Create `kubernetes/apps/<namespace>/<service>/app/grafana-dashboard.yaml` as a ConfigMap with:
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: grafana-dashboard-<service>
     labels:
       grafana_dashboard: "1"
     annotations:
       grafana_folder: <Folder Name>
   data:
     dashboard.json: |
       { ... }
   ```
2. Add `- ./grafana-dashboard.yaml` to that service's `kustomization.yaml`.
3. Do **not** set `namespace:` in the ConfigMap — the `targetNamespace` in the Flux Kustomization applies it.

**Dashboard folder taxonomy** (use one of these in `grafana_folder`):

- `Apps` — user-facing workloads
- `Data` — databases, message queues (CloudNativePG, etc.)
- `GitHub & Copilot` — GitHub billing and Copilot usage
- `Kubernetes` — core cluster health and workload capacity
- `Networking` — Cilium, Envoy Gateway
- `Observability` — Prometheus, Alertmanager, Tempo, Mimir, Loki, LGTM stack
- `Platform` — Flux GitOps, cert-manager, Renovate, etcd
- `Security` — Kyverno, Falco, Tetragon, Trivy, Cosign
- `Storage` — Longhorn
- `Synthetics` — Blackbox probes, k6 canaries

**Removing a service:** Delete the service directory (or disable its Flux Kustomization). The dashboard ConfigMap is gone with it — no separate cleanup needed.

**Do not use the `GrafanaDashboard` CRD** (Grafana Operator) unless a decision is made to adopt the operator cluster-wide. The existing sidecar pattern covers all current needs.

## Guardrails

- If a change requires a secret, document:
  - the Secret name/namespace
  - the required keys
  - a plaintext YAML template the human should encrypt with SOPS
  - any external setup steps (OAuth app config, DNS, etc.)
- Prefer wiring secrets into workloads via Helm values such as `existingSecret`, `extraEnvFrom`, or `envFromSecret`.

