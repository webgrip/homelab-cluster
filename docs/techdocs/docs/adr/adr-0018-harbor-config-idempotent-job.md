# Provision Harbor proxy config via an idempotent API CronJob

* Status: accepted
* Date: 2026-06-23

Technical Story: [RFC: Harbor Pull-Through Proxy Cache](../rfc/rfc-harbor-proxy-cache.md)

## Context and Problem Statement

The proxy-cache projects and their upstream registry endpoints
([ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md)) are **Harbor-internal objects**, created
through the Harbor v2 API (`POST /api/v2.0/registries`, `…/projects`). They are not Kubernetes
resources, so Flux/Kustomize cannot declare them. The cluster runs no Harbor operator (upstream
`harbor-operator` is not production-grade, and a CRD controller for a handful of objects is
disproportionate), and clicking them into the Harbor UI would be undeclared drift that a Harbor DB
restore silently loses. The `openbao-init` CronJob is the proven in-house shape for "reconcile an
external system's state from Git."

## Considered Options

* An idempotent `harbor-proxy-config` CronJob against the Harbor v2 API
* Harbor UI clickops
* `harbor-operator` CRDs
* Helm post-install hook
* One-shot `Job`

## Decision Outcome

Chosen option: "An idempotent `harbor-proxy-config` CronJob against the Harbor v2 API", because
the proxy config is Harbor-internal state Flux cannot declare, and a timer-tier converging
CronJob — the proven `openbao-init` shape — self-heals after a Harbor DB restore and activates on
late credentials with no further GitOps change.

Provision the Harbor side with an idempotent **`harbor-proxy-config` CronJob** (hourly) that calls
the Harbor v2 API, mirroring `openbao-init`. It is a timer-tier converging task per the model later
codified in [ADR-0019](adr-0019-bootstrap-task-pattern.md) — idempotent `GET`-before-create
("already exists" = success), self-healing after a Harbor DB restore, hardened pod, least-privilege
— plus the specifics that matter here:

* **Fail-soft `exit 0`:** if the upstream credentials aren't in OpenBao yet, or Harbor is
  mid-restart, it logs and exits **0** — Harbor is never blocked and no `KubeJobFailed` noise
  accrues. This let the provisioning plane land *before* cutover: it no-ops until
  `bao kv put secret/harbor/registry-proxy …` runs, then activates with no further GitOps change.
* **Credentials via ESO:** a `harbor-registry-proxy` ExternalSecret reads
  `secret/harbor/registry-proxy` from OpenBao (Docker Hub + GHCR tokens, used only to lift upstream
  rate limits); the admin password comes from the existing `harbor-admin` secret. All are mounted
  `optional` so a missing secret degrades to fail-soft, not a wedged pod.
* **Finished-job hygiene:** `ttlSecondsAfterFinished` + success/failure history limits of 1 — the
  lesson of the [openbao-init incident](../blogs/2026-06-13-harbor-as-a-pull-through-cache.md).

Lives at `kubernetes/apps/harbor/harbor/app/harbor-proxy-config.cronjob.yaml`.

### Positive Consequences

* The Harbor proxy config is declared in Git, reproducible across a Harbor rebuild, and reviewable;
  a DB restore re-establishes it on the next tick.

### Negative Consequences

* It is imperative glue, not a controller: a genuinely new Harbor object type means extending the
  script, not declaring a CR — an accepted trade for avoiding an operator.
* API-shape coupling: the script pins Harbor v2 payloads; a major Harbor API change means updating
  it. Low-frequency, well-contained risk.

## Pros and Cons of the Options

### An idempotent `harbor-proxy-config` CronJob against the Harbor v2 API

* Good, because it is idempotent, self-healing after a Harbor DB restore, and fail-soft before
  credentials exist.
* Bad, because it is imperative glue — a genuinely new Harbor object type means extending the
  script.

### Harbor UI clickops

* Bad, because undeclared, non-reproducible, silently lost on a DB restore.

### `harbor-operator` CRDs

* Bad, because a whole controller for a handful of objects; not production-grade upstream.

### Helm post-install hook

* Bad, because it fires only on chart install/upgrade; misses a DB restore or late credential
  population.

### One-shot `Job`

* Bad, because it won't re-run on a Harbor rebuild or late credentials without a name change;
  scheduled convergence is the point.

## Links

* 2026-06-13 — proposed; the CronJob landed the same day, dormant (fail-soft until credentials
  existed)
* 2026-06-16 — extended to provision the private `webgrip` project + CI robot account
* 2026-06-23 — accepted: active in production at the Phase-1 cutover, provisioning all six
  proxy-cache projects ([ADR-0016](adr-0016-harbor-pull-through-proxy-cache.md))
