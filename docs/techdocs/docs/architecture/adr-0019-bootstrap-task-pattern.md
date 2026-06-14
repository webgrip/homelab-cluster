# ADR-0019: Bootstrap & one-shot provisioning tasks — pick the lowest trigger tier

> Status: **Accepted** · Date: 2026-06-14 · Cross-cutting platform convention (no parent RFC)

## Context

The cluster repeatedly needs to bring an **external system's state** in line with Git — work that
is *not* a Kubernetes resource, so Flux/Kustomize cannot declare it and some imperative glue is
required: create a Forgejo bot user + token, seed Harbor proxy-cache projects, initialise OpenBao,
grant a Postgres role, load policy/sample data. Done carelessly each becomes either a recurring
CronJob (a pod + job-history noise on a timer, forever) or undeclared clickops drift.

The repo already contains every shape of this, arrived at ad hoc, with no shared convention so each
author re-derives the trade-off:

- **Controller-reconciled (no Job):** the Forgejo bot *password* (ESO `password-generator`), OIDC
  clients (Authentik blueprints), DB roles (CNPG `managed.roles`).
- **Timer CronJob:** `openbao-init` (`*/5`, re-inits a wiped volume), `harbor-proxy-config`
  (hourly, [ADR-0018](adr-0018-harbor-config-idempotent-job.md)), `github-app-token` (`*/30`, token
  rotation).
- **Change-triggered bare Job:** `sparkyfitness-db-pgstatstatements-perms` (a `Job` in a
  `force: true` Kustomization), `dependency-track` policy-bootstrap, `guac` sample-data.

## Decision

Adopt a **decision model** with two axes — *what triggers the task* and *what gates it* — and pick
the **lowest trigger tier that is correct**.

**Trigger tier (prefer the lowest):**

| Tier | Mechanism | Use when | Load |
|------|-----------|----------|------|
| **0 — reconciled** | A controller owns the desired state (ESO generator/PushSecret, Authentik blueprint, CNPG `managed.roles`, Helm hook) | A controller *can* express it | none |
| **1 — change-triggered** | A bare `Job` (fixed name) in a `force: true` Flux Kustomization; the completed Job is the "done" marker, re-run only on spec change | External state is **durable** (doesn't self-drift) and inputs already exist | one pod per change |
| **2 — timer** | A converging `CronJob` | External state **self-drifts** (a DB restore / volume wipe erases it, a token expires) **or** inputs arrive late and you want unattended healing | one pod per tick, forever |

**Gate (express the "requirements"):**

- **Flux:** `dependsOn` + `wait: true` + `healthChecks` on the prerequisite (e.g. "only after Forgejo
  is Ready").
- **Secret-existence:** an `ExternalSecret` stays unsynced until its backend path exists; consumers wait.
- **In-script precondition:** probe-then-act, and **fail-soft `exit 0`** when a prereq is absent so
  Flux retries next reconcile instead of accruing `KubeJobFailed` noise.

**Cross-cutting rules for every tier:** idempotent (`GET`-before-create, treat "already exists" as
success — never duplicate); hardened (`runAsNonRoot`, `readOnlyRootFilesystem`, drop `ALL`
capabilities, requests+limits for Kyverno); finished-job hygiene (`ttlSecondsAfterFinished` /
history limits); least-privilege RBAC.

## Consequences

- One named, reviewable trade-off instead of a per-author re-derivation; Tier 2's recurring load is
  spent only where external state genuinely self-drifts, so the cluster runs fewer idle timer pods.
- The existing instances map cleanly and stay valid: `openbao-init`, `github-app-token`, and
  **Harbor proxy-config ([ADR-0018](adr-0018-harbor-config-idempotent-job.md)) are correct Tier-2**
  choices (volume wipe / DB restore / token expiry + late credentials all demand unattended
  self-heal); `sparkyfitness` perms and the **Renovate→Forgejo provisioner are Tier 1**.
- **Honest tension with ADR-0018:** a Forgejo DB restore would wipe the bot/token just as a Harbor
  restore wipes proxy config — by the strict self-drift test that argues for Tier 2. The
  Renovate→Forgejo provisioner stays **Tier 1** anyway because (a) its only input (`forgejo/admin`)
  already exists, so there is no late-credential gap, (b) loss is **loud** (`RenovateProjectRunFailed`
  alert) and recovery is one `kubectl delete job` (Flux recreates it), and (c) it avoids a perpetual
  daily pod for an event that essentially never happens. If unattended healing is later wanted,
  *promotion is trivial* — the same script becomes a low-frequency Tier-2 CronJob. The tiers are a
  spectrum, not a wall.
- New work has a default: reach for Tier 0, then Tier 1; justify Tier 2 by naming the self-drift it heals.

## Alternatives considered

- **One tier for everything (all CronJobs, `openbao-init` style).** Simplest mental model, and the
  openbao/harbor cases need it — but it pays a perpetual timer for tasks whose state never drifts
  (perms grants, the Forgejo bot). Rejected as a blanket rule; kept as Tier 2.
- **All bare Jobs.** Lowest load, but cannot self-heal external self-drift (a Harbor/OpenBao restore)
  and won't re-run on late credentials without a name change — exactly ADR-0018's stated reason for
  choosing a CronJob. Rejected as a blanket rule; kept as Tier 1.
- **An operator/CRD per external system.** The level-triggered ideal (Tier 0), but disproportionate
  for a handful of objects with no production-grade upstream operator (ADR-0018's finding for Harbor).
- **Helm post-install/post-upgrade hooks for all of it.** Only fire on chart install/upgrade — they
  miss a DB restore or a late `bao kv put`. Fine *only* when the task is genuinely chart-lifecycle-bound.
