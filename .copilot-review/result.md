pr: 238

## Dependency Update Review

**Verdict:** Green Low risk
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates only the pinned digest for `docker.io/library/busybox:1.38.0` in two HelmRelease-managed init containers. Upstream evidence indicates the new digest is a republished OCI index that adds a `linux/riscv64` manifest; existing platform digests used in this cluster were not changed in our manifest comparison. The local blast radius is limited because BusyBox is only used for short-lived config-copy init steps in Minecraft and Zomboid. Merge is reasonable after confirming rendered manifests and successful initContainer startup in those two workloads.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `docker.io/library/busybox` | Docker/OCI | `sha256:b6762dd` → `sha256:fd8d9aa` (tag `1.38.0`) | digest | runtime/infra (initContainers) | Low |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[feature]` | `busybox:1.38.0` tag digest now points to a newer OCI index digest (`fd8d9aa`) with 17 manifests and includes `linux/riscv64` image metadata (new platform entry observed vs old digest). | [Docker Hub tag API (1.38.0)](https://hub.docker.com/v2/repositories/library/busybox/tags/1.38.0), [docker-library/busybox commit `a7aa89a` (riscv64 metadata)](https://github.com/docker-library/busybox/commit/a7aa89abdab03706254ea3c256067ea96a8cdcd5) | **No** — cluster workloads here are not configured for `riscv64`; BusyBox use is for simple init scripts on existing node architectures. |
| `[behavior]` | Official images update stream for BusyBox 1.38.0 references the metadata refresh set merged via official-images update `#21520`. | [docker-library/official-images commit `da3b030` (`Update busybox (#21520)`)](https://github.com/docker-library/official-images/commit/da3b030b9dd58f7cb1cd0063a96984c2686ffd5f) | **Unknown** — no explicit per-architecture runtime behavior change is documented for amd64 in this digest-only PR. |

No formal BusyBox “release notes” were published for this digest republish. Checked: Docker Hub tag metadata/API for `library/busybox:1.38.0`, Docker Official Images commit history for `library/busybox`, and linked `docker-library/busybox` commits.

### Local impact

BusyBox appears in:
- `kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml` (two initContainers: `geyser-config-sync`, `bluemap-config-sync`)
- `kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml` (initContainer: `config-sync`)
- `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` (separate workload still pinned to old digest; not changed by this PR)

In PR #238, only Minecraft and Zomboid are changed. In both apps, BusyBox runs short `sh`+`cp` scripts before main containers start. This is low privilege/low complexity logic, but failed init containers would block pod startup. Rollback is simple (revert digest).

### Improvement opportunities

- **`Align remaining BusyBox pin usage`** — consider updating `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` to the same reviewed digest to reduce drift and keep BusyBox provenance consistent across workloads. (Grounded in local usage discovery.)
- **`Track platform expansion policy`** — because this digest republish appears to add `riscv64`, document whether heterogeneous node architectures are expected in this cluster so digest reviews can explicitly assess new-platform additions. [Source](https://github.com/docker-library/busybox/commit/a7aa89abdab03706254ea3c256067ea96a8cdcd5)

### Grafana dashboards and alerts

No dashboard or alert changes identified: BusyBox is used only in initContainers for file copy/bootstrap and does not expose service metrics consumed by repo dashboards/alerts.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard | `kubernetes/apps/zomboid/zomboid/app/dashboards/apps-zomboid.yaml` tracks app/game and container runtime metrics, not BusyBox initContainer internals | None | Digest update only affects BusyBox init image pin; no upstream metric/schema change source found |
| Alert / Metric / Scrape config | No BusyBox-specific PrometheusRule/ServiceMonitor/PodMonitor references found | None | BusyBox official image digest republish does not define Prometheus metric changes; Docker Hub/official-images sources indicate image metadata/platform refresh |

### Pre-merge checks

- [ ] Confirm Flux/Helm render for the two modified HelmReleases without schema errors.
- [ ] After deploy, verify `minecraft` and `zomboid` pods complete BusyBox initContainers successfully (`geyser-config-sync`, `bluemap-config-sync`, `config-sync`).
- [ ] Pull and inspect `docker.io/library/busybox:1.38.0@sha256:fd8d9aa...` from a cluster-matching architecture node to confirm image availability.
- [ ] Run `./scripts/verify-oci-digests.sh <repo-root>` in CI/local to keep digest pin integrity checks green.

### Follow-up

- [ ] Consider opening a separate Renovate/manual PR to update BusyBox digest in `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` for consistency.
- [ ] Add a short runbook note for digest-only OCI updates explaining how to compare OCI index manifests (platform additions/removals) before merge.

### Evidence reviewed

- PR: `chore(container): update image docker.io/library/busybox ( b6762dd ➔ fd8d9aa )`; labels `area/kubernetes`, `renovate/container`, `type/digest`, `dependencies`; diff modifies 2 files and 3 digest lines.
- Files in repo: `kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml`, `kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml`, `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml`, `kubernetes/apps/zomboid/zomboid/app/dashboards/apps-zomboid.yaml`, `.renovaterc.json5`.
- Upstream sources checked: `https://hub.docker.com/v2/repositories/library/busybox/tags/1.38.0`, `https://github.com/docker-library/official-images/commit/da3b030b9dd58f7cb1cd0063a96984c2686ffd5f`, `https://github.com/docker-library/busybox/commit/a7aa89abdab03706254ea3c256067ea96a8cdcd5`, `https://github.com/docker-library/busybox/commit/3c8912ca2ca28fbe2d698c8ae6b534bd4eb408cd`.
- Notable uncertainty: No explicit upstream human-authored release note explains this exact digest republish; inference is based on OCI index comparison and linked metadata-update commits.
