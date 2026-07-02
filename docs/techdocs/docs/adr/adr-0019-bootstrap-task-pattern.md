# Bootstrap & one-shot provisioning tasks — pick the lowest trigger tier

* Status: accepted
* Date: 2026-06-14

## Context and Problem Statement

The cluster repeatedly needs to bring an **external system's state** in line with Git — work that is
not a Kubernetes resource, so Flux/Kustomize cannot declare it and some imperative glue is required:
create a Forgejo bot user + token, seed Harbor proxy-cache projects, initialise OpenBao, grant a
Postgres role. Done carelessly, each becomes either a recurring CronJob (a pod on a timer, forever)
or undeclared clickops drift. The repo already contained every shape of this, arrived at ad hoc —
controller-reconciled state (ESO `password-generator`, Authentik blueprints, CNPG `managed.roles`),
timer CronJobs (`openbao-init`, `harbor-proxy-config`, `github-app-token`), change-triggered bare
Jobs (`sparkyfitness` perms, dependency-track policy-bootstrap, guac sample-data) — with no shared
convention, so each author re-derived the trade-off. This is a cross-cutting platform convention;
no parent RFC.

## Considered Options

* A two-axis decision model — pick the lowest trigger tier that is correct
* One tier for everything (all CronJobs, `openbao-init` style)
* All bare Jobs
* An operator/CRD per external system
* Helm post-install/post-upgrade hooks for all of it

## Decision Outcome

Chosen option: "A two-axis decision model — pick the lowest trigger tier that is correct", because
one named, reviewable trade-off replaces per-author re-derivation, and a timer's recurring load is
spent only where external state genuinely self-drifts.

Adopt a **decision model** with two axes — *what triggers the task* and *what gates it* — and pick
the **lowest trigger tier that is correct**.

**Trigger tier (prefer the lowest):**

| Tier | Mechanism | Use when | Load |
| ---- | --------- | -------- | ---- |
| **0 — reconciled** | A controller owns the desired state (ESO generator/PushSecret, Authentik blueprint, CNPG `managed.roles`, Helm hook) | A controller *can* express it | none |
| **1 — change-triggered** | A bare `Job` (fixed name) in a `force: true` Flux Kustomization; the completed Job is the "done" marker, re-run only on spec change | External state is **durable** (doesn't self-drift) and inputs already exist | one pod per change |
| **2 — timer** | A converging `CronJob` | External state **self-drifts** (a DB restore / volume wipe erases it, a token expires) **or** inputs arrive late and you want unattended healing | one pod per tick, forever |

**Gate (express the "requirements"):**

* **Flux:** `dependsOn` + `wait: true` + `healthChecks` on the prerequisite (e.g. "only after Forgejo
  is Ready").
* **Secret-existence:** an `ExternalSecret` stays unsynced until its backend path exists; consumers wait.
* **In-script precondition:** probe-then-act, and **fail-soft `exit 0`** when a prereq is absent so
  Flux retries next reconcile instead of accruing `KubeJobFailed` noise.

**Cross-cutting rules for every tier:** idempotent (`GET`-before-create, treat "already exists" as
success — never duplicate); hardened (`runAsNonRoot`, `readOnlyRootFilesystem`, drop `ALL`
capabilities, requests+limits for Kyverno); finished-job hygiene (`ttlSecondsAfterFinished` /
history limits); least-privilege RBAC.

### Positive Consequences

* One named, reviewable trade-off instead of per-author re-derivation; Tier 2's recurring load is
  spent only where external state genuinely self-drifts.
* The existing instances map cleanly: `openbao-init`, `github-app-token`, and `harbor-proxy-config`
  ([ADR-0018](adr-0018-harbor-config-idempotent-job.md)) are correct Tier-2 choices (volume wipe /
  DB restore / token expiry demand unattended self-heal); the `sparkyfitness` perms grant and the
  Renovate→Forgejo provisioner are Tier 1.
* New work has a default: reach for Tier 0, then Tier 1; justify Tier 2 by naming the self-drift it
  heals.

### Negative Consequences

* **Honest tension with ADR-0018:** by the strict self-drift test, a Forgejo DB restore wipes the
  bot/token just as a Harbor restore wipes proxy config — which argues for Tier 2. The
  Renovate→Forgejo provisioner stays Tier 1 anyway: its only input already exists (no
  late-credential gap), loss is loud (`RenovateProjectRunFailed`) with one-command recovery, and
  promoting the same script to a low-frequency Tier-2 CronJob is trivial if unattended healing is
  ever wanted — the tiers are a spectrum, not a wall.

## Pros and Cons of the Options

### A two-axis decision model — pick the lowest trigger tier that is correct

* Good, because it replaces per-author re-derivation with one named, reviewable trade-off.
* Good, because the tiers are a spectrum, not a wall — promoting a Tier-1 script to a
  low-frequency Tier-2 CronJob is trivial if unattended healing is ever wanted.
* Bad, because the strict self-drift test leaves honest boundary cases (see the
  [ADR-0018](adr-0018-harbor-config-idempotent-job.md) tension under Negative Consequences).

### One tier for everything (all CronJobs, `openbao-init` style)

* Bad, because it pays a perpetual timer for tasks whose state never drifts; kept as Tier 2 only.

### All bare Jobs

* Bad, because they cannot self-heal external self-drift and won't re-run on late credentials
  without a name change; kept as Tier 1 only.

### An operator/CRD per external system

* Good, because it is the level-triggered ideal (Tier 0).
* Bad, because it is disproportionate for a handful of objects with no production-grade upstream
  operator.

### Helm post-install/post-upgrade hooks for all of it

* Good, because fine when the task is genuinely chart-lifecycle-bound.
* Bad, because they fire only on chart install/upgrade; miss a DB restore or a late `bao kv put`.

## Links

* 2026-06-14 — accepted
