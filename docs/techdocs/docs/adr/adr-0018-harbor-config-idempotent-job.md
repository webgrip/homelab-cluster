# ADR-0018: Provision Harbor proxy config via an idempotent API CronJob

> Status: **Proposed** · Date: 2026-06-13 · Part of [RFC: Harbor Pull-Through Proxy Cache](../rfc/rfc-harbor-proxy-cache.md)

## Context

The proxy-cache projects and their upstream registry endpoints
([ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md)) are **Harbor-internal objects**, created
through the Harbor v2 API (`POST /api/v2.0/registries`, `POST /api/v2.0/projects`). They are not
Kubernetes resources, so Flux/Kustomize cannot declare them directly. The cluster runs **no
Harbor operator** (the upstream `harbor-operator` is not production-grade and would add a CRD
controller for two objects), and everything else here is GitOps — clicking these into the Harbor
UI would be undeclared, non-reproducible drift that a Harbor DB restore silently loses.

The cluster already has a proven pattern for "reconcile an external system's state from a
manifest": the **`openbao-init` CronJob** — idempotent, self-healing, hardened, and (after a
[recent incident](../blogs/2026-06-13-harbor-as-a-pull-through-cache.md)) careful about finished-job
hygiene.

## Decision

Provision the Harbor side with an **idempotent `harbor-proxy-config` CronJob** that calls the
Harbor v2 API, mirroring the `openbao-init` shape:

- **Idempotent:** `GET` each registry endpoint / project first; create only if absent; treat
  "already exists" as success. Re-running converges, never duplicates.
- **Self-healing:** runs on a schedule (hourly), so a Harbor DB restore or a fresh Harbor
  re-establishes the proxy config on the next tick.
- **Fail-soft:** if the upstream credentials aren't in OpenBao yet (or Harbor is mid-restart), it
  logs and exits **0** — Harbor is never blocked and no `KubeJobFailed` noise accrues.
- **Credentials via ESO:** a `harbor-registry-proxy` ExternalSecret reads
  `secret/harbor/registry-proxy` from OpenBao (Docker Hub + GHCR tokens, used only to lift upstream
  rate limits); the Harbor admin password comes from the existing `harbor-admin` secret. Both are
  mounted as `optional` env so a missing secret degrades to fail-soft rather than a wedged pod.
- **Hardened + tidy:** `runAsNonRoot`, `readOnlyRootFilesystem`, all capabilities dropped,
  resource requests/limits set (Kyverno), and `ttlSecondsAfterFinished` + `successfulJobsHistory`
  /`failedJobsHistoryLimit: 1` — the finished-job hygiene the openbao-init incident taught us.

## Consequences

- **The Harbor proxy config is declared in Git** (the script + its inputs), reproducible across a
  Harbor rebuild, and reviewable — no clickops drift.
- **The provisioning plane is safe to land before cutover.** With no credentials yet the CronJob
  no-ops; it activates the moment `bao kv put secret/harbor/registry-proxy …` runs, with no
  further GitOps change.
- **It's imperative glue, not a controller.** A genuinely new Harbor object type (robot accounts,
  retention policies) means extending the script, not declaring a CR — an accepted trade for
  avoiding an operator for a handful of objects.
- **API-shape coupling.** The script pins Harbor v2 API payloads; a major Harbor API change would
  require updating it. Low-frequency, well-contained risk.

## Alternatives considered

- **Harbor UI clickops.** Undeclared, non-reproducible, and silently lost on a Harbor DB restore.
  Rejected — it violates the GitOps-first rule.
- **`harbor-operator` (CRDs).** A whole controller to manage two objects; not production-grade
  upstream. Disproportionate.
- **A Helm post-install hook in the Harbor HelmRelease.** Runs only on chart install/upgrade, not
  on a Harbor DB restore or credential population; the standalone CronJob self-heals on a schedule
  independent of Helm.
- **A one-shot `Job`.** Immutable and won't re-run on Harbor rebuild or late credential entry
  without a name change; the CronJob's scheduled convergence is the openbao-init-proven idiom.
