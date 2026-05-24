pr: 241

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates a pinned BusyBox image digest in the Invoice Ninja `prepare-storage` initContainer, without changing the tag (`1.38.0`). Upstream metadata shows the digest change is an OCI index republish; existing common platform child manifests (including amd64) appear unchanged, with a new riscv64 platform entry added. The main risk is architecture-specific behavior if this cluster uses non-amd64 nodes. Merge is reasonable after a quick architecture and rollout verification.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `busybox` | Docker/OCI | `sha256:b6762dd...` → `sha256:fd8d9aa...` (tag remains `1.38.0`) | digest | runtime (Kubernetes initContainer) | Yellow |

### Important upstream changes

| Type | Description | Link | Repo affected? |
|------|-------------|------|----------------|
| `[behavior]` | OCI index digest for `busybox:1.38.0` changed; index now includes additional descriptors (notably `linux/riscv64`) while existing amd64/arm/ppc64le/s390x child digests remained the same in registry manifest comparison. | [old digest manifest](https://registry-1.docker.io/v2/library/busybox/manifests/sha256:b6762ddf4a50aabb5f4d21aa6f447d05d5633fb09f09c08b33f22356a2f98be0), [new digest manifest](https://registry-1.docker.io/v2/library/busybox/manifests/sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d) | **Yes** — this repo pins the index digest directly in Kubernetes manifests. |
| `[feature]` | Docker Official Images busybox refresh includes BusyBox `1.38.0` / buildroot `2026.02.2`, and explicit riscv64 metadata update in the referenced source commits. | [official-images update](https://github.com/docker-library/official-images/commit/da3b030b9dd58f7cb1cd0063a96984c2686ffd5f), [busybox PR #247](https://github.com/docker-library/busybox/pull/247), [riscv64 metadata commit](https://github.com/docker-library/busybox/commit/a7aa89a) | **Unknown** — relevant if any cluster nodes schedule this initContainer on riscv64; no explicit node-arch inventory found in this repo review scope. |
| `[unknown]` | No BusyBox upstream release-note document was found that maps specifically to this digest-to-digest republish event for the same tag. | [Docker Hub tag metadata](https://hub.docker.com/v2/repositories/library/busybox/tags/1.38.0) | **Unknown** — provenance details for why the tag digest moved are indirect (commit references, not a dedicated digest changelog). |

### Local impact

BusyBox is used as a lightweight shell image in multiple manifests, but PR #241 changes only `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml` for the `prepare-storage` initContainer. That container runs `mkdir` and `chown` on a PVC mount before app startup, so failure would block pod readiness/startup for Invoice Ninja. Other BusyBox references remain in `kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml` and `kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml` (still on old digest), so this PR introduces a temporary mixed-digest state across workloads.

### Improvement opportunities

- **Align all shared BusyBox digest pins in one pass** — this repo still has other BusyBox references on the old digest; updating them together reduces drift and simplifies rollback reasoning. (Local files: `kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml`, `kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml`)
- **Document architecture expectation for workloads using digest-pinned multi-arch images** — since digest changes can be index-level (platform set) without tag change, documenting expected node architectures would reduce uncertainty during future digest-only PRs. ([official-images commit context](https://github.com/docker-library/official-images/commit/da3b030b9dd58f7cb1cd0063a96984c2686ffd5f))

### Grafana dashboards and alerts

No dashboard or alert changes identified. I found no observability files in this repo that reference BusyBox-specific metrics, and this initContainer image does not expose application metrics.

| Area | Current repo usage | Suggested change | Reason / source |
|------|--------------------|------------------|-----------------|
| Dashboard / Alert / Metric / Scrape config | none found for BusyBox (`kubernetes/apps/observability/**`, `kubernetes/components/**`, `docs/techdocs/**`) | None | BusyBox digest update for an initContainer does not introduce metric/schema changes; no local PromQL/dashboard coupling found. |

### Pre-merge checks

- [ ] Confirm cluster node architectures for namespaces/workloads running this initContainer; if only amd64/arm variants already present in both indexes, risk is low.
- [ ] After Flux reconcile, verify `invoiceninja` pod init sequence succeeds (`prepare-storage` completes without crash/retry loops).
- [ ] Validate no unexpected image pull issues for the new digest in cluster events.

### Follow-up

- [ ] Consider a follow-up PR to align remaining BusyBox digest pins in Minecraft/Zomboid manifests — reduces mixed-digest operational state across apps.

### Evidence reviewed

- PR: `chore(container): update image busybox ( b6762dd ➔ fd8d9aa )`; labels: `area/kubernetes`, `renovate/container`, `type/digest`, `dependencies`; diff summary: 1 file changed, 1 line updated.
- Files in repo: `kubernetes/apps/invoiceninja/invoiceninja/app/invoiceninja-deployment.yaml`, `kubernetes/apps/minecraft/minecraft/app/helmrelease.yaml`, `kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml`, `.renovaterc.json5`, observability paths under `kubernetes/apps/observability/**` and `kubernetes/components/**`.
- Upstream sources checked: `https://hub.docker.com/v2/repositories/library/busybox/tags/1.38.0`, `https://github.com/docker-library/official-images/commit/da3b030b9dd58f7cb1cd0063a96984c2686ffd5f`, `https://github.com/docker-library/busybox/pull/247`, `https://github.com/docker-library/busybox/commit/a7aa89a`, OCI manifest endpoints for old/new digests.
- Notable uncertainty: No dedicated vendor changelog exists for this same-tag digest republish; architecture-specific impact depends on actual node architectures.
