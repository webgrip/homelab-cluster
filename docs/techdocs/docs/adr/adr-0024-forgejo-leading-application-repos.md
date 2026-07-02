# Forgejo-authoritative application repos (de-mirror to run write-back CI)

* Status: accepted
* Date: 2026-06-26

## Context and Problem Statement

The forge migration mirrors every `webgrip/*` repo from GitHub into Forgejo with **gitea-mirror**,
as a continuous, read-only pull-mirror — correct for the inbound-copy phase, while GitHub remains
the source of truth. But the in-cluster Forgejo also runs **CI that writes back to the repo**:
`semantic-release` cuts a release by pushing a git tag. A read-only pull-mirror makes that
impossible two ways: the push is rejected outright (`remote: mirror repository is read-only`,
HTTP 403), and even if it weren't, gitea-mirror's periodic sync (every 8h) **force-syncs from
GitHub** and would clobber any Forgejo-side tag. It is the same wall Renovate hit
([ADR-0011](adr-0011-dual-run-renovate-forgejo.md)): "Forgejo runs write-back CI for a repo" and
"Forgejo holds that repo as a read-only mirror" are mutually exclusive. (Background:
[Bringing the Forge Home](../blogs/2026-06-12-bringing-the-forge-home.md).)

## Considered Options

* De-mirror to Forgejo-authoritative the moment Forgejo must write
* Keep the read-only mirror; cut releases only on GitHub
* Writable mirror with bidirectional sync
* GitHub→Forgejo *push*-mirror (GitHub pushes; Forgejo writable)

## Decision Outcome

Chosen option: "De-mirror to Forgejo-authoritative the moment Forgejo must write", because
write-back CI and a read-only pull-mirror are mutually exclusive, and the migration's north star
is to archive GitHub, not re-plumb it.

An application repo becomes **Forgejo-authoritative** (de-mirrored) the moment Forgejo must write
to it (releases, Renovate branches). The cutover per repo, in this order:

1. **Stop gitea-mirror managing it** *(first)* — remove it from gitea-mirror so the periodic
   force-sync can no longer re-assert the mirror or clobber tags. gitea-mirror's repo set lives in
   its own SQLite DB (a UI action), **not** in GitOps.
2. **Convert the Forgejo repo** from a pull-mirror to a normal writable repo (Forgejo → repo
   Settings → Mirror Settings → *convert to regular repository*). It keeps all current content.
3. **Re-point local `origin` to Forgejo**; demote GitHub to a named `github` remote
   (`remote.pushDefault = origin`, `main` tracks `origin/main`).
4. **Archive GitHub** for that repo once Forgejo is confirmed authoritative.

Content-first, cutover-last: de-mirror only after the repo's content is fully in Forgejo. The CI
bot (`webgrip-ci`, org `webgrip/ci` team, write on all repos) already has push rights, so
`semantic-release` works the moment the repo is writable.

### Positive Consequences

* Releases and Renovate work: `semantic-release` pushes tags + creates Forgejo releases;
  `on_release_published` then builds and pushes the image to in-cluster Harbor.

### Negative Consequences

* Tags/releases diverge from GitHub for de-mirrored repos — intended, because GitHub is being
  archived, not kept in sync. (Contrast the *redundancy* ring: outbound Forgejo→Codeberg
  push-mirrors, [ADR-0020](adr-0020-codeberg-offsite-push-mirror.md), built *after* cutover, from
  the new source.)
* gitea-mirror's mirrored count covers only the repos still GitHub-leading; de-mirrored repos are
  authoritative, not copies.
* **`homelab-cluster` follows the same path, last.** It is both the GitOps source and the one repo
  gitea-mirror could never finish mirroring; its de-mirror is gated behind the Flux source cutover
  ([ADR-0014](adr-0014-flux-source-forgejo.md)) — cutover-last so the platform never loses its
  footing.

## Pros and Cons of the Options

### De-mirror to Forgejo-authoritative the moment Forgejo must write

* Good, because `semantic-release` works the moment the repo is writable — the CI bot
  (`webgrip-ci`) already has push rights.
* Bad, because tags/releases diverge from GitHub for de-mirrored repos — intended, since GitHub is
  being archived, not kept in sync.

### Keep the read-only mirror; cut releases only on GitHub

* Bad, because it keeps GitHub load-bearing for the release step; the opposite of the migration's
  north star.

### Writable mirror with bidirectional sync

* Bad, because tag divergence + clobbering; the fragile two-way sync pull-mirrors exist to avoid.

### GitHub→Forgejo *push*-mirror (GitHub pushes; Forgejo writable)

* Good, because workable.
* Bad, because it keeps GitHub the source; the goal is to archive GitHub, not re-plumb it.

## Links

* 2026-06-18 — accepted; `webgrip/infrastructure` de-mirrored as the first repo through the
  cutover (writable, `origin` re-pointed)
* 2026-06-26 — de-mirrored set grown to `webgrip/workflows`, `renovate-config`, `claude-config` and
  `.profile` (tracked in the Renovate Forgejo discovery list); `homelab-cluster` remains
  GitHub-leading, gated on [ADR-0014](adr-0014-flux-source-forgejo.md)
