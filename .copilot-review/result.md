pr: 323

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This patch bumps the Grafana Alloy Helm chart from 1.8.1 to 1.8.2 across two local deployments (`alloy-agent` and `alloy-gateway`). The **sole upstream change** is a bump of the bundled `config-reloader` sidecar image from `quay.io/prometheus-operator/prometheus-config-reloader:v0.81.0` to `v0.91.0`. No alloy binary version, chart templates, or default values were changed. The config-reloader is a lightweight sidecar that watches ConfigMaps and sends a reload signal to alloy; its v0.81→v0.91 changes are entirely internal to the prometheus-operator project (CRD validations, operator CLI flags) and have no behavioural impact on alloy. Neither local release overrides the `configReloader.image.tag` value, so both will pick up the new default automatically.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `alloy` | Helm | `1.8.1 → 1.8.2` | patch | runtime (observability) | Green |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | Bump bundled `config-reloader` sidecar default tag from `v0.81.0` to `v0.91.0` | [alloy#6233](https://github.com/grafana/alloy/pull/6233) | **Yes** — applies to both `alloy-agent` and `alloy-gateway` deployments; neither overrides `configReloader.image.tag` so they will automatically use the new image |
| `[bugfix]` | prometheus-config-reloader v0.81→v0.91: ten releases of operator-internal fixes (CRD validations, StatefulSet informer selectors, Alertmanager peer discovery, remote-write URL scheme validation, repair policy CLI flags). None of these changes affect the reloader's file-watch-and-reload function that alloy depends on. | [prometheus-operator releases](https://github.com/prometheus-operator/prometheus-operator/releases) | **No** — all changes are to prometheus-operator CRD behaviour and the operator binary, not to the config file-watching/reloading logic used by alloy |

### Local impact

Two Flux HelmRelease resources are updated:

- **`kubernetes/apps/observability/alloy-agent/app/helmrelease.yaml`** — DaemonSet (`hostNetwork: true`) deployed on every node. Collects pod logs via `loki.source.kubernetes`, Kubernetes events, and Talos OS kernel/service syslog over TCP port 6514. Annotated with `reloader.stakater.com/auto: "true"`. Rolling update of all DaemonSet pods; node-level log gaps will be negligible as pods restart sequentially.
- **`kubernetes/apps/observability/alloy-gateway/app/helmrelease.yaml`** — single-replica Deployment on the `fringe` node group. Receives OTLP gRPC (4317), OTLP HTTP (4318), and Faro (12347) traffic; exports to Loki, Tempo, and Prometheus remote-write. Annotated with `reloader.stakater.com/auto: "true"`. A brief pod restart is expected; clients (SDKs, apps) should reconnect automatically.

No state is held in the alloy pods beyond in-flight buffered data. Rollback to 1.8.1 is straightforward (revert the two `version:` fields).

The Talos syslog integration (`tcp://127.0.0.1:6514`) relies on `hostNetwork: true`; this is unchanged in 1.8.2.

### Improvement opportunities

None identified. The sole chart change is a sidecar image bump with no new configuration options exposed to chart consumers.

### Grafana dashboards and alerts

No dashboard or alert changes identified. The config-reloader sidecar does not export metrics consumed by any dashboards or recording rules in this repository. No PrometheusRule, ServiceMonitor, or dashboard JSON/YAML files reference the config-reloader image or its metrics. Alloy's own metrics pipeline (`loki.source`, `otelcol.*`, `faro.receiver`) is unaffected by this change.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Alloy dashboards / metrics | Not explicitly configured in this repo | None | Config-reloader bump does not alter alloy's exposed metrics or labels |

### Pre-merge checks

- [ ] Confirm Flux reconciles `alloy-agent` and `alloy-gateway` successfully after merge (watch `flux get hr -n observability`).
- [ ] Verify `alloy-agent` DaemonSet pods restart and resume log shipping to Loki (check for new log ingestion from all nodes).
- [ ] Verify `alloy-gateway` pod restarts and OTLP/Faro endpoints remain reachable.

### Follow-up

None.

### Evidence reviewed

- **PR**: [#323](https://github.com/webgrip/homelab-cluster/pull/323) — "fix(helm): update chart alloy ( 1.8.1 ➔ 1.8.2 )"; labels: `area/kubernetes`, `type/patch`, `renovate/helm`, `dependencies`; diff: 2 files, 2 lines changed (version field in each HelmRelease)
- **Files in repo**: `kubernetes/apps/observability/alloy-agent/app/helmrelease.yaml`, `kubernetes/apps/observability/alloy-gateway/app/helmrelease.yaml`, `talos/patches/global/machine-logging.yaml`, `kubernetes/apps/observability/kustomization.yaml`
- **Upstream sources checked**:
  - [grafana/helm-charts release alloy-1.8.2](https://github.com/grafana/helm-charts/releases/tag/alloy-1.8.2)
  - [grafana/alloy compare d06bc66...94e2936](https://github.com/grafana/alloy/compare/d06bc66d09be62f9f374a131211005088861d2e1...94e2936cf57978f55ddac056b17f3186a1f9a28e)
  - [grafana/alloy PR #6233](https://github.com/grafana/alloy/pull/6233) — config-reloader bump
  - [grafana/alloy PR #6307](https://github.com/grafana/alloy/pull/6307) — helm release v1.8.2
  - [prometheus-operator releases v0.81.0–v0.91.0](https://github.com/prometheus-operator/prometheus-operator/releases)
- **Notable uncertainty**: The grafana/helm-charts raw tag refs returned 404 (likely protected/internal), but the GitHub compare API and the alloy source repo provided complete information. Confidence is high.
