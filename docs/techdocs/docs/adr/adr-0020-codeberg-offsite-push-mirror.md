# ADR-0020: Fan Forgejo out to Codeberg as a second off-site mirror (native push-mirror, CronJob-reconciled)

> Status: **Proposed** · Date: 2026-06-17 · Part of [RFC: Cutting the GitOps umbilical](../rfc/rfc-flux-forgejo-source.md)

## Context

[ADR-0015](adr-0015-external-bootstrap-fallback-source.md) names Codeberg as a planned *second*
off-site mirror so the disaster-recovery copy isn't itself a single host; this ADR pins down the
mechanism, scope, and trigger. The forces: **Codeberg runs Forgejo**, so one script drives both
ends through the same REST API. Forgejo's **native push-mirror** is the built-in mechanism
(interval and/or on-commit push, sync status in the UI/API); the existing
[`gitea-mirror`](../general/forgejo.md) app is inbound-only, with no outbound path. The repo set
**self-drifts** (new `webgrip/*` repos appear; a Forgejo DB restore wipes push-mirror rows — the
self-drift [ADR-0018](adr-0018-harbor-config-idempotent-job.md) calls out), so coverage must
self-heal; and a push-mirror does **not** create the destination repo — the reconciler must.
Sequencing: this must **not** run before the Flux-source cutover
([ADR-0014](adr-0014-flux-source-forgejo.md)) — until Forgejo is authoritative, most `webgrip/*`
repos are read-only pull-mirrors of GitHub, so mirroring them onward only launders GitHub's content
sideways. **Decided now, built after cutover.**

## Decision

Add a third leg to the redundancy ring: **Forgejo → Codeberg via Forgejo's native push-mirror, for
every repo in the `webgrip` org**, kept converged by a **Tier-2 reconcile CronJob**
([ADR-0019](adr-0019-bootstrap-task-pattern.md)) running in-cluster against the two Forgejo APIs.
Each run: enumerate `webgrip/*` on the local forge; ensure the destination repo exists on Codeberg
(`GET`-before-`POST`, "already exists" = success); ensure a push-mirror is attached
(`sync_on_commit: true` + a bounded interval). A single Codeberg token (org repo-create + write)
arrives via **ESO + OpenBao**; the `ExternalSecret` stays unsynced until the OpenBao path exists,
so the job fails soft — exactly how it stays dormant until activated post-cutover. Daily is ample;
the same script serves as a Tier-1 one-shot if recurring healing proves unnecessary. Push-mirror
last-sync/health is alerted (ADR-0015's "keep the push-mirror honest"), so a silent mirror failure
doesn't rot the DR copy.

## Alternatives considered

- **Tier-1 do-once Job** — new repos and post-restore wipes wouldn't self-heal without a manual
  re-run; exactly the self-drift that argues for Tier 2 (promotion/demotion stays free — same
  script).
- **Extend the `gitea-mirror` app** — inbound-only, wrong direction; a stateful web UI where a
  stateless reconcile suffices.
- **A `forgesync`-style external sync tool** — more to operate than the forge's built-in
  push-mirror with visible status.

## Consequences

- The DR ring stops being single-host: a total cluster loss *and* a GitHub takedown still leave a
  current copy on Codeberg (plus the nightly CNPG→Garage `forgejo-db` backup).
- More write paths to keep honest — three counting the GitHub leg: a failed push-mirror silently
  rots its copy, hence the alert is part of the decision, not an afterthought.
- **Codeberg's usage policy is a real constraint, not a footnote.** Codeberg is a volunteer-run
  community host that explicitly is *not* a free backup/mirror service; bulk push-mirrors of private
  or inactive repos can run afoul of its terms. The "all webgrip org repos" scope must therefore be
  filtered to repos appropriate to host there (public, of genuine community interest), **or** the
  off-site target should instead be the **second self-hosted Forgejo** the RFC also envisions
  (ToS-clean, fully under our control). **Resolve this before build.**
- Private repos can't be public Codeberg mirrors — exclude them or push to private repos (same
  policy note).
- Reversible: delete the CronJob + Secret to stop new mirrors; existing push-mirror rows are
  removed per-repo via API/UI. Nothing here is load-bearing for the running cluster.

## Status log

- 2026-06-17 — Proposed. Deliberately unbuilt until after the [ADR-0014](adr-0014-flux-source-forgejo.md)
  cutover; the Codeberg ToS question must be resolved before build.
