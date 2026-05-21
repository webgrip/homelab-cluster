# Cluster Health Audit — 2026-05-21

**Auditor**: Copilot cluster-health agent  
**Cluster**: homelab-cluster (Talos v1.12.4 / K8s v1.34.4 / Flux v2.7.5)  
**Nodes**: 4 (soyo-1/2/3 control-plane + fringe-workstation worker) — all `Ready`

---

## Severity Summary

| Severity | Count | Issues |
|----------|-------|--------|
| 🔴 CRITICAL | 1 | Flux cannot reconcile 15 digest-pinned OCI sources (source-controller v1.7.4 bug) |
| 🟠 HIGH | 1 | kube-prometheus-stack HelmRelease stalled, operator has InvalidImageName pod |
| 🟡 MEDIUM | 1 | ARC runner-set listener crashlooping (409 session conflict) |
| 🟢 OK | — | Nodes, storage (28/28 PVCs Bound), network (Gateways Accepted, CoreDNS Running), certificates (3/3 Ready), observability stack (Prometheus/Grafana/Loki/Tempo/Pyroscope all Running) |

---

## CRITICAL — Flux OCI Digest Verification Bug (15 OCIRepositories)

### Symptom
All 15 `OCIRepository` objects that use `tag@sha256:digest` pinning fail with:
```
failed to determine artifact digest:
GET https://github.com/-/v2/packages/container/package/bjw-s-labs%2Fhelm%2Fapp-template%2Fmanifests%2F5.0.1:
unexpected status code 404 Not Found
```

### Affected sources
`n8n`, `echo`, `drawio`, `searxng`, `freshrss`, `minecraft`, `excalidraw`, `sparkyfitness`, `cloudflare-tunnel` (all `app-template 5.0.1@sha256:...`), `cilium`, `coredns`, `metrics-server`, `reloader`, `spegel`, `renovate-operator`

### Root cause
**Flux source-controller v1.7.4 incorrectly constructs the GitHub Packages REST API URL for GHCR OCI repositories when a digest pin is present.**

When Flux verifies a `tag@sha256:digest` reference on GHCR, it calls the GitHub Packages API at:
```
https://github.com/-/v2/packages/container/package/{entire-oci-path-url-encoded}/manifests/{tag}
```
The entire OCI path (org/repo/chart) **plus** the `/manifests/{tag}` segment is URL-encoded as a single package-name path component, producing a malformed URL that returns 404.

OCIRepositories with plain tags (no `@sha256:`) use the standard OCI registry API (`ghcr.io/v2/...`) and work correctly. 12 such repos show `Ready: True`.

### Impact
- Flux cannot verify or re-pull these 15 chart sources
- HelmReleases depending on them **cannot be upgraded** (Flux refuses to apply a HelmRelease whose source is not Ready)
- Running workloads are **not affected** — cached artifacts are in use and pods are Running
- `cilium`, `coredns`, `metrics-server`, `spegel` are cluster-critical CNI/DNS/metrics — any restart that would require re-pulling would fail to upgrade

### Options to resolve

**Option A — Upgrade Flux operator** (preferred, non-mutating to workloads)
Check whether `flux-instance` chart ≥ 0.49.x ships a fixed source-controller. Open a Renovate PR or manually bump `flux-instance` version in the Flux Kustomization.
```bash
# Verify which source-controller version is included
helm show chart oci://ghcr.io/controlplaneio-fluxcd/charts/flux-instance --version <latest>
```

**Option B — Remove digest pins** (workaround, reduces supply-chain verification)
Remove the `@sha256:...` suffix from all failing OCIRepository `.spec.ref.tag` fields. This uses tag-only resolution (same as the currently-working repos). Acceptable short-term given the cache is intact.

**Option C — Switch to `spec.ref.digest`**
Use the separate `digest:` field instead of the `tag@sha256:` inline format. May trigger the same code path — needs testing.

**Recommended action**: Check latest `flux-instance` chart release → if it includes source-controller ≥ v1.4.x with the fix, bump it. Otherwise apply Option B as a temporary measure while tracking the upstream Flux issue.

---

## HIGH — kube-prometheus-stack HelmRelease Stalled

### Symptom
```
status: Stalled
message: Failed to perform remediation: missing target release for rollback: cannot remediate failed release
```
Two replicaset pods coexist in `observability`:
- `kube-prometheus-stack-operator-cf487bfff-hbjzd` — Running (old version, 82.18.0)
- `kube-prometheus-stack-operator-9c4dcddbb-dd5ps` — `InvalidImageName` (failed 85.2.0 upgrade)

The failed upgrade pod has a malformed image: `v0.91.0@sha256:...@sha256:...` (digest duplicated).

### Root cause
Renovate PR merged `82.18.0 → 85.2.0` (3 chart versions in one batch). The upgrade included Loki 6→16 and Pyroscope 1→2 major bumps. The Helm upgrade timed out (5m25s context deadline), Flux attempted rollback, but found no valid rollback target (both revision 28 and 29 are poisoned). The partial upgrade left a deployment with a double-digest image that cannot start.

### Impact
- Actual operator functionality: **intact** — the old (`cf487bfff`) pod is still Running and managing PrometheusRules, ServiceMonitors, etc.
- The stalled HelmRelease blocks Flux from applying any future `kube-prometheus-stack` updates
- The bad pod is cosmetic noise but will remain until cleaned up

### To resolve (human action required)
```bash
# 1. Delete the stale failed Helm release secrets to unblock Flux
kubectl -n observability get secret -l owner=helm,name=kube-prometheus-stack --sort-by='{.metadata.labels.version}'
kubectl -n observability delete secret <failed-revision-secret>

# 2. Force Flux to re-install (will pick up current chart version)
flux reconcile helmrelease kube-prometheus-stack -n observability --force

# 3. Delete the bad operator pod (old one will serve until new one is ready)
kubectl -n observability delete pod kube-prometheus-stack-operator-9c4dcddbb-dd5ps
```
**Note**: Next time, pin Renovate to upgrade chart versions one major at a time using `separateMajorMinor: true` and version constraints.

---

## MEDIUM — ARC Runner Set Listener 409 Session Conflict

### Symptom
`arc-runner-set-656b5d56-listener` crashloops every ~5s with exit code 1:
```
StatusCode 409 — The actions runner scaleset arc-runner-set already has an active session
```

### Root cause
ARC was upgraded from `0.13.0 → 0.13.1`. The previous listener pod registered a session with GitHub's Actions API. The old session was not cleaned up on chart upgrade, and the new listener cannot register while the stale session exists.

### Impact
- GitHub Actions runners from the `arc-runner-set` scale set are **not available** during the conflict
- Renovate review workflow and any other CI using this runner set will queue/fail

### To resolve (human action required)

**Option A — Restart the ARC controller manager** (recommended)
The controller owns the stale sessions and will clean them up on restart:
```bash
kubectl -n arc-systems rollout restart deployment gha-runner-scale-set-controller
```

**Option B — Delete the listener pod and allow controller to clean sessions**
```bash
kubectl -n arc-systems delete pod arc-runner-set-656b5d56-listener
# Wait for controller to notice and clean up session (~30–60s)
```

**Option C — Manual API cleanup** (avoid unless Options A/B fail)
Requires a GitHub PAT with `manage_runners:org` scope. See [GitHub REST API: delete runner registration token](https://docs.github.com/en/rest/actions/self-hosted-runners).

---

## Phase Results

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Flux reconciliation | ⚠️ | 15 OCIRepositories `False`, 28 total not-ready resources; Kustomizations applied |
| 2. Kubernetes primitives | ✅ | 4/4 nodes Ready, 1 pod InvalidImageName (cosmetic) |
| 3. Talos nodes | ✅ | Talos v1.12.4, kernel 6.18.9, all nodes healthy |
| 4. Storage | ✅ | 28/28 PVCs Bound, all Longhorn pods Running |
| 5. Network | ✅ | Cilium Running, CoreDNS 2/2 Running, both Envoy Gateways Programmed, 17 HTTPRoutes |
| 6. Certificates | ✅ | 3/3 certificates Ready (barman-cloud x2, webgrip-dev-production) |
| 7. Observability | ⚠️ | All workloads running (Prometheus, Grafana, Loki, Tempo, Pyroscope, Alloy); HelmRelease Stalled (non-blocking for running pods) |
| 8. App impact | ✅ | All application pods Running; no user-facing downtime from current issues |

---

## Standards Notes

- **Digest pinning**: The OCI digest-pin pattern (`tag@sha256:`) is correct practice for supply-chain security but is currently broken in source-controller v1.7.4 on GHCR. Do not remove pins without a plan to re-add them after the Flux upgrade.
- **Renovate batching**: Avoid multi-major chart version bumps in a single PR for components with large Helm upgrade timeouts. Use `separateMajorMinor` and per-package `automerge` strategies.
- **ARC session handling**: ARC chart upgrades that involve the runner registration lifecycle should be done with the controller restarted first (or scaled to 0 then back up).
