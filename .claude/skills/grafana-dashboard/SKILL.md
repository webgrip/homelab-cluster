---
name: grafana-dashboard
description: Add or edit Grafana dashboards, datasources, folders, or alert rules. Use when working with Grafana resources — all managed as Grafana Operator CRDs, never ConfigMaps or HelmRelease values.
---

# Grafana resources (Operator-managed)

Everything is a `grafana.integreatly.org/v1beta1` CRD. Never use dashboard ConfigMaps (`grafana_dashboard: "1"` — the sidecar was removed) or HelmRelease values.

## Universal rules
- Every CRD needs:
  ```yaml
  spec:
    instanceSelector:
      matchLabels: { grafana.internal/instance: grafana }
  ```
- Resources **outside** the `observability` namespace also need `spec.allowCrossNamespaceImport: true`.
- The Grafana instance itself is `observability/grafana/app/grafana-instance.yaml` (there is no `helmrelease.yaml` — don't look for one).
- Datasources = `GrafanaDatasource` CRDs with `spec.datasource.editable: true` (not in the instance `spec.config`).
- The operator reconciles ~every 10m and **reverts UI edits** — all changes must be in Git. Inventory: `kubectl get grafanadashboards -A`.

## Add a dashboard
1. Create `kubernetes/apps/observability/grafana/app/dashboards/<name>.yaml`:
   ```yaml
   apiVersion: grafana.integreatly.org/v1beta1
   kind: GrafanaDashboard
   metadata: { name: <name> }
   spec:
     instanceSelector: { matchLabels: { grafana.internal/instance: grafana } }
     folder: "<Title>"        # by title — see Folders below
     json: |
       { "title": "...", "uid": "...", ... }
   ```
2. Add `- ./dashboards/<name>.yaml` to `observability/grafana/app/kustomization.yaml`.
3. **Do NOT co-locate dashboards with their service.** Folder resolution is **namespace-scoped**: `folder:`/`folderRef:` resolve only within the dashboard's own namespace. `allowCrossNamespaceImport` controls instance targeting, NOT folder lookup. Cross-namespace dashboards must use `folderUID` instead of `folder:`.

## Folders

Dashboards in `observability/` (the convention) just set `folder: "<Title>"` by name. Valid titles and scope: **Apps** (user workloads) · **Data** (DBs/queues) · **Kubernetes** (cluster health) · **Networking** (Cilium/Envoy) · **Observability** (Prom/Alertmanager/Loki/Tempo/Mimir) · **Platform** (Flux/cert-manager/Renovate/etcd) · **Security** (Kyverno/Falco/Tetragon/Trivy/Cosign) · **Storage** (Longhorn) · **Synthetics** (blackbox/k6) · **GitHub & Copilot**. List live folders with `kubectl get grafanafolders -A`.

Only if you must place a dashboard in a *different* namespace (discouraged), reference it by `folderUID` instead of `folder:` — titles resolve only within the dashboard's own namespace. Get the UID from `kubectl get grafanafolder <name> -o jsonpath='{.spec.uid}'`.

## Don't
- Don't omit `editable: true` on datasources (operator may treat them read-only and reject updates).
- Don't edit dashboards in the Grafana UI expecting them to persist — they're reverted.
