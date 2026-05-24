pr: 227

## Dependency Update Review

**Verdict:** Green — Low risk
**Recommendation:** Merge
**Confidence:** High

### Executive summary

This PR adds a SHA-256 digest pin to the existing `webgrip/backstage-application:1.0.4` image tag already running in the cluster. The digest `sha256:1918c9e90b09e4c09303dd24e3e221202557c9f51167ba824a786e54ca5ba934` is confirmed to match the current `1.0.4` tag on Docker Hub. No version change, no behavior change — this is a pure supply-chain security improvement that prevents tag mutation attacks.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `webgrip/backstage-application` | Docker/OCI | `1.0.4` → `1.0.4@sha256:1918c9e…` | digest pin | runtime | Green |

### Important upstream changes

No version upgrade is involved — this PR only pins the digest of the already-deployed `1.0.4` image. Digest confirmed on Docker Hub as matching the `1.0.4` tag (and `latest`), pushed 2025-12-16.

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | Digest pinning added to prevent tag-mutable image pulls | [Docker Hub tag](https://hub.docker.com/r/webgrip/backstage-application/tags) | **No** — no behavioral change; same image bytes already running |

For reference, the release notes for `1.0.4` (the running version) are:
- **Fixed**: use env var for base url in the `app-config.yml` ([fe73265](https://github.com/webgrip/backstage-application/commit/fe73265849933020cc5bc49093cb9736185b58cb))

### Local impact

The only file changed is `kubernetes/apps/backstage/backstage/app/deployment.yaml`. The image reference changes from:

```
webgrip/backstage-application:1.0.4
```
to:
```
webgrip/backstage-application:1.0.4@sha256:1918c9e90b09e4c09303dd24e3e221202557c9f51167ba824a786e54ca5ba934
```

The digest is confirmed to be identical to what Docker Hub currently serves for the `1.0.4` tag. Kubernetes will resolve to exactly the same image layers already running, so no pod restart with a content change is expected. The deployment uses `imagePullPolicy: IfNotPresent`, meaning if the image is already cached on the node, no pull will occur at all. The pod has readiness and liveness probes on `/healthcheck:7007` and connects to a PostgreSQL database (`backstage-db-rw.backstage.svc.cluster.local`); neither is affected by this change.

### Improvement opportunities

- **Consider pinning the `latest` alias to a versioned tag** — the `latest` tag on Docker Hub currently points to the same digest as `1.0.4`, but this will drift. The current manifest already uses `1.0.4`, which is good; the digest pin now adds a second layer of protection.

### Grafana dashboards and alerts

No dashboard or alert changes identified. The `apps-backstage.yaml` dashboard (`kubernetes/apps/backstage/backstage/app/dashboards/apps-backstage.yaml`) uses only Kubernetes infrastructure metrics (`up`, `kube_pod_status_phase`, `kube_deployment_spec_replicas`, `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`, `kubelet_volume_stats_*`). These are unaffected by a digest-only pin.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `dashboards/apps-backstage.yaml` — infra-level metrics only | None | Digest pin has no metric impact |

### Pre-merge checks

- [ ] Confirm the digest resolves correctly in your registry/pull environment: `docker manifest inspect webgrip/backstage-application:1.0.4@sha256:1918c9e90b09e4c09303dd24e3e221202557c9f51167ba824a786e54ca5ba934`
- [ ] Verify Flux reconciles cleanly after merge (no `ImagePullBackOff` due to digest not being reachable from the cluster's network).

### Follow-up

- [ ] Consider enabling Renovate digest updates for all other container images in the cluster for consistent supply-chain hygiene.

### Evidence reviewed

- **PR**: "chore(container): pin image webgrip/backstage-application to 1918c9e" — labels: `area/kubernetes`, `renovate/container`, `dependencies`; diff: 1 file, 1 line changed (digest appended to image tag)
- **Files in repo**: `kubernetes/apps/backstage/backstage/app/deployment.yaml`, `kubernetes/apps/backstage/backstage/app/dashboards/apps-backstage.yaml`, `kubernetes/apps/backstage/backstage/app/configmap.yaml`, `kubernetes/apps/backstage/backstage/app/kustomization.yaml`
- **Upstream sources checked**:
  - Docker Hub API: `https://hub.docker.com/v2/repositories/webgrip/backstage-application/tags?page_size=20` — confirmed digest `sha256:1918c9e90b09e4c09303dd24e3e221202557c9f51167ba824a786e54ca5ba934` matches `1.0.4` tag
  - GitHub Releases API: `https://api.github.com/repos/webgrip/backstage-application/releases` — latest release is `1.0.4` (2025-12-16), no newer versions exist
- **Notable uncertainty**: None — digest match confirmed, no version upgrade involved.
