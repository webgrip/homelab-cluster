# ADR-0020: Fan Forgejo out to Codeberg as a second off-site mirror (native push-mirror, CronJob-reconciled)

> Status: **Proposed** · Date: 2026-06-17 · Part of [RFC: Cutting the GitOps umbilical](rfc-flux-forgejo-source.md)

## Context

[ADR-0015](adr-0015-external-bootstrap-fallback-source.md) keeps GitHub — demoted to a
Forgejo→GitHub push-mirror — as the cold-bootstrap + break-glass GitOps source, and names
**Codeberg as a planned *second* off-site mirror "later"** so the disaster-recovery copy isn't
itself a single host. This ADR pins down that "later": the mechanism, scope, and trigger for the
Forgejo→Codeberg leg. The forces:

- **Codeberg runs Forgejo.** Its REST API is the same shape as the in-cluster forge's, so one
  script drives both ends — enumerate sources on the local forge, ensure destinations + mirror
  config on Codeberg — with no second client to learn.
- **Native push-mirror is the built-in, "proper" mechanism.** Forgejo's per-repo push-mirror pushes
  refs to a remote on an interval and/or on commit, surfaces sync status in the UI/API, and adds no
  moving parts. The existing [`gitea-mirror`](../forgejo.md) app (raylabshq) is **inbound only**
  (GitHub→Forgejo, the migration mirror) and has no Forgejo→Codeberg push path.
- **The set of repos drifts.** New `webgrip/*` repos appear over time, and a Forgejo DB restore
  wipes push-mirror rows — the same self-drift [ADR-0018](adr-0018-harbor-config-idempotent-job.md)
  calls out for Harbor. Coverage must self-heal, not be a one-shot.
- **Push-mirror does not create the remote.** The destination repo must already exist on Codeberg;
  the reconciler creates it (idempotently) before attaching the mirror.
- **Sequencing.** This must **not** run before the GitHub→Forgejo cutover
  ([ADR-0014](adr-0014-flux-source-forgejo.md)). Until Forgejo is authoritative, most `webgrip/*`
  repos are themselves read-only pull-mirrors of GitHub, so mirroring them onward only launders
  GitHub's content sideways into Codeberg. **Decided now, built after cutover.**

## Decision

*(Proposed.)* Add a third leg to the redundancy ring: **Forgejo → Codeberg, via Forgejo's native
push-mirror, for every repo in the `webgrip` org**, kept in sync by a **Tier-2 reconcile CronJob**
([ADR-0019](adr-0019-bootstrap-task-pattern.md)) running in-cluster against the two Forgejo APIs.
Each converging run:

1. Enumerates `webgrip/*` repos on the in-cluster forge (`GET /orgs/webgrip/repos`).
2. For each, ensures a destination repo exists under the `webgrip` org on Codeberg
   (`GET`-before-`POST /orgs/webgrip/repos`; treat "already exists" as success).
3. Ensures a push-mirror is attached on the source repo (`GET /repos/webgrip/<r>/push_mirrors`, then
   `POST` if absent) pointing at the Codeberg remote, `sync_on_commit: true` + a bounded interval.

- **Credentials:** a single Codeberg access token (org repo-create + write) sourced via **ESO +
  OpenBao**, never plaintext. The reconciler reads it from a mounted Secret and hands it to the
  Forgejo push-mirror API as the stored remote password. The `ExternalSecret` stays unsynced until
  the OpenBao path exists, so the job **fails soft** until the token is provisioned (the precondition
  pattern in ADR-0019) — which is exactly how this stays dormant until activated post-cutover.
- **Tier 2 (CronJob), justified:** the source-repo set self-drifts (new repos) and mirror rows are
  wiped by a forge DB restore — unattended healing is wanted. Frequency is low (daily is ample); the
  *same script* would serve as a Tier-1 one-shot Job if recurring healing were later deemed
  unnecessary, so the choice is reversible.
- **Health is alerted.** Per ADR-0015's "keep the push-mirror honest," a check on push-mirror
  last-sync/health raises an alert when the off-site copy goes stale, so a silent mirror failure
  doesn't rot the DR copy.

## Consequences

- The DR ring stops being single-host: a total cluster loss *and* a GitHub takedown still leave a
  current copy on Codeberg. With the nightly CNPG→Garage `forgejo-db` backup, the forge's content
  then has two independent off-site homes (Codeberg refs + a logical DB backup).
- **Write paths to keep honest** — now three counting the GitHub leg: each push-mirror silently rots
  its copy if it fails, hence the alert is part of the decision, not an afterthought.
- **Codeberg's usage policy is a real constraint, not a footnote.** Codeberg is a volunteer-run
  community host that explicitly is *not* a free backup/mirror service; bulk push-mirrors of private
  or inactive repos can run afoul of its terms. The "all webgrip org repos" scope must therefore be
  filtered to repos appropriate to host there (public, of genuine community interest), **or** the
  off-site target should instead be the **second self-hosted Forgejo** the RFC also envisions
  (ToS-clean, fully under our control). **Resolve this before build.**
- **Private repos can't be public Codeberg mirrors** — either exclude them or push to private
  Codeberg repos (subject to the same policy note).
- Reversible: deleting the CronJob + its Secret stops new mirrors; existing push-mirror rows are
  removed per-repo via the API/UI. Nothing here is load-bearing for the running cluster.

## Alternatives considered

- **Do-once bootstrap Job (Tier 1), like the renovate-forgejo-provisioner.** Lighter (no perpetual
  pod), but new `webgrip/*` repos and post-restore wipes wouldn't self-heal without a manual re-run —
  exactly the self-drift that argues for Tier 2 here. Rejected for the recurring case; the same script
  is the CronJob body, so promotion/demotion stays free.
- **Extend the `gitea-mirror` app.** It's a GitHub→Forgejo *inbound* tool with no Forgejo→Codeberg
  push path. Rejected — wrong direction, and it adds a stateful web UI where a stateless reconcile
  suffices.
- **A `forgesync`-style external sync tool.** More to operate than Forgejo's own push-mirror, which
  already does interval + on-commit pushing with visible status. Rejected in favour of the built-in.
- **Configure push-mirrors by hand in the UI.** Fine for one repo; doesn't scale to an org and isn't
  GitOps-tracked or self-healing. Rejected for org scope.
- **A second off-cluster Forgejo instead of Codeberg.** The RFC's eventual ideal and ToS-clean, but
  unbuilt and needs its own host. Codeberg is reachable today; this reconciler can target either once
  the policy question above is settled — the mechanism is identical (both are Forgejo APIs).
