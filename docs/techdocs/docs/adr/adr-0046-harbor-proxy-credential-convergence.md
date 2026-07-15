---
status: accepted
date: 2026-07-15
---

# Harbor proxy reconcile converges credentials and fails loud on upstream auth

Technical Story: 2026-07-15 CI outage — cold pulls of `docker.io` / `ghcr.io` images
(kind node image, opencost + flux-local charts) returned 404 through Harbor's pull-through
cache. Refines [ADR-0025](adr-0025-harbor-config-idempotent-job.md).

## Context and Problem Statement

The `harbor-proxy-config` CronJob ([ADR-0025](adr-0025-harbor-config-idempotent-job.md)) is
the idempotent, fail-soft reconciler for Harbor's proxy-cache endpoints. Two properties that
were correct at provisioning time turned into a silent outage once the estate was steady-state:

1. **`ensure_registry` was create-only.** Its `GET`-before-create logic treated an existing
   registry as "already exists = success" and returned immediately — it never reconciled the
   **credential** on an endpoint that already existed. So when the Docker Hub PAT expired and
   was rotated in OpenBao (and ESO propagated the new value into the `harbor-registry-proxy`
   Secret), the reconcile was a no-op against the *credential*: Harbor kept using the old,
   expired token. Rotation could not converge through Git — the documented mechanism — at all.

2. **The job fail-softs unconditionally (`exit 0`).** That is exactly right *before* credentials
   exist (ADR-0025's late-credential activation). But it also means an authenticated registry
   whose upstream token has **expired or been revoked** produces a green job and no signal.
   Harbor logged `login to dockerhub error: {"message":"secret is expired"}` on every cold pull;
   nothing surfaced it. The only alerts were liveness (`up{job="harbor-core"} == 0`) — Harbor was
   up, so they stayed silent. The outage was discovered by a failing CI run, not by monitoring.

A rotated token that never reaches Harbor, plus no alert when the stored token stops working,
is a standing trap: the next PAT expiry reproduces the same silent cache-miss outage.

## Considered Options

* **Converge credentials in the reconciler + fail loud on a credentialed-upstream health failure** (chosen)
* Leave create-only; document "rotate = delete the registry in the UI so the next run recreates it"
* Move credential rotation out of the reconciler into a dedicated one-shot Job triggered by ESO

## Decision Outcome

Chosen option: **converge credentials in the reconciler + fail loud on a credentialed-upstream
health failure**, because the reconciler is already the Git-declared owner of this Harbor state —
credential rotation belongs on the same convergence path as endpoint creation, and the health
check turns a silent auth failure into an alertable one without weakening the late-credential
fail-soft that ADR-0025 depends on.

Load-bearing specifics:

* **Credential convergence on existing registries.** `ensure_registry`'s "already exists" branch
  now issues `PUT /registries/{id}` with the current credential whenever creds are present.
  The update uses the **flat** `RegistryUpdate` shape
  (`{credential_type, access_key, access_secret}`) — **not** the nested `{credential:{…}}` object
  the create path (`POST /registries`) uses. (This distinction cost real time during the incident:
  a `PUT` with the nested create-shape body is silently accepted and changes nothing.)
* **Narrowed fail-loud.** A new `verify_registry_health` pings the *stored* credential
  (`POST /registries/ping {"id":N}`, with retries to ride out blips) for the credentialed
  upstreams only (docker-hub, ghcr). A failure sets `HEALTH_FAILED`; the script `exit 1`s at the
  end. ADR-0025's blanket fail-soft is preserved everywhere else — Harbor unreachable, admin
  password absent, or credentials not yet populated still `exit 0`. Fail-loud fires **only** when
  Harbor is up and a credential that *should* work does not.
* **Alert.** `HarborProxyReconcileStale` fires when
  `time() - kube_cronjob_status_last_successful_time{cronjob="harbor-proxy-config"} > 2h`. The
  hourly schedule means a single transient ping failure self-clears on the next successful run;
  two missed cycles indicate a genuinely stuck credential and page platform with the rotation
  runbook inline.

### Consequences

* Good, because token rotation now converges through Git/OpenBao as designed — update the value,
  let ESO sync, and the next reconcile (or a manual `create job --from=cronjob`) applies it to
  the live Harbor registry. No UI clickops, no registry deletion.
* Good, because an expired/revoked upstream token is now a warning with a runbook, not a silent
  cache-miss outage found via failing CI.
* Good, because the fail-soft that let the provisioning plane land before credentials existed
  (ADR-0025) is intact — the new `exit 1` is scoped to a live, authenticated upstream failing.
* Bad, because the reconcile now performs an upstream round-trip (the ping) each run, adding a
  few seconds and a dependency on upstream reachability for a *healthy* exit. Mitigated by
  retries and the >2h alert threshold, so upstream flakiness does not page.
* Bad, because the script now encodes two Harbor payload shapes (create vs update) for the same
  credential — the flat/nested distinction is a documented footgun, called out in-line.

### Confirmation

* After rotating `secret/harbor/registry-proxy` in OpenBao and running the job, the stored
  credential on registries 1 (docker-hub) and 2 (ghcr) is the new value and both report
  `status: healthy` — verified live during the 2026-07-15 fix; the three previously-404ing cold
  pulls (`kindest/node`, `opencost:2.5.25`, `flux-local`) return `200`.
* A deliberately-wrong token in OpenBao drives the reconcile Job to `exit 1` and
  `HarborProxyReconcileStale` to fire within its window (mutation test, before the change is
  declared complete).

## More Information

* Refines [ADR-0025](adr-0025-harbor-config-idempotent-job.md) — the idempotent reconciler whose
  create-only gap and unconditional fail-soft this decision closes; ADR-0025 stays accepted, this
  narrows two of its behaviours rather than superseding it.
* Builds on [ADR-0023](adr-0023-harbor-pull-through-proxy-cache.md) — the pull-through proxy cache
  the credentials serve.
* Implementation: `kubernetes/apps/harbor/harbor/app/harbor-proxy-config.configmap.yaml`
  (`ensure_registry` credential convergence + `verify_registry_health`) and
  `…/prometheusrule.yaml` (`HarborProxyReconcileStale`).
