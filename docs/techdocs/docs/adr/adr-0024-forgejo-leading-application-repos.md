# ADR-0024: Forgejo-authoritative application repos (de-mirror to run write-back CI)

> Status: **Accepted** · Date: 2026-06-18 · Related: [ADR-0011](adr-0011-dual-run-renovate-forgejo.md), [ADR-0014](adr-0014-flux-source-forgejo.md), [Bringing the Forge Home](../blogs/2026-06-12-bringing-the-forge-home.md)

## Context

The forge migration mirrors every `webgrip/*` repo from GitHub into Forgejo with **gitea-mirror**,
as a *continuous, read-only pull-mirror*. That is correct for the inbound-copy phase: content lands
in Forgejo, stays in sync, and GitHub remains the source of truth.

But the in-cluster Forgejo also now **runs the CI that writes back to the repo**. For
`webgrip/infrastructure`, `.forgejo/workflows/on_source_change.yml` runs `semantic-release`, which
cuts a release by **pushing a git tag**. A read-only pull-mirror makes that impossible two ways:

- The push is rejected outright — `remote: mirror repository is read-only` (HTTP 403).
- Even if it weren't, gitea-mirror's periodic sync (every 8h) **force-syncs from GitHub** and would
  clobber any tag Forgejo created. A pull-mirror cannot hold Forgejo-side history.

This is the same wall Renovate hit ([ADR-0011](adr-0011-dual-run-renovate-forgejo.md)): you cannot
open a PR — or cut a release — against a repo you cannot push to. "Forgejo runs write-back CI for a
repo" and "Forgejo holds that repo as a read-only mirror" are mutually exclusive.

## Decision

An application repo becomes **Forgejo-authoritative** (de-mirrored) the moment Forgejo must write to
it (releases, Renovate branches). The cutover per repo:

1. **Stop gitea-mirror managing it** *(first)* — remove it from gitea-mirror so the periodic sync no
   longer re-asserts the mirror or clobbers tags. gitea-mirror's repo set lives in its own SQLite
   DB (a UI action), **not** in GitOps.
2. **Convert the Forgejo repo** from a pull-mirror to a normal writable repo (Forgejo → repo
   Settings → Mirror Settings → *convert to regular repository*). It keeps all current content.
3. **Re-point local `origin` to Forgejo**; demote GitHub to a named `github` remote
   (`remote.pushDefault = origin`, `main` tracks `origin/main`).
4. **Archive GitHub** for that repo once Forgejo is confirmed authoritative.

`webgrip/infrastructure` is the first repo through this (2026-06-18): de-mirrored, writable,
`origin` re-pointed. The CI bot (`webgrip-ci`, org `webgrip/ci` team, write on all repos) already
has push rights, so `semantic-release` can push tags once the repo is writable.

## Consequences

- **Releases and Renovate work.** semantic-release pushes tags + creates Forgejo releases;
  `on_release_published` then builds and pushes the image to in-cluster Harbor.
- **Tags/releases diverge from GitHub** for de-mirrored repos — intended, because GitHub is being
  archived, not kept in sync. (Contrast the *redundancy* ring: outbound Forgejo→Codeberg push-mirrors,
  [ADR-0020](adr-0020-codeberg-offsite-push-mirror.md), built *after* cutover, from the new source.)
- **gitea-mirror's "~71/72 mirrored" count stops including de-mirrored repos** — they are now
  authoritative, not copies. The continuous mirror covers only the repos still on GitHub.
- **Content-first, cutover-last** still holds: de-mirror only after the repo's content is fully in
  Forgejo. The local checkout must already carry the latest (it did — local/GitHub/Forgejo all at the
  same commit before the switch).
- **The `homelab-cluster` repo follows the same path, last.** It is both the GitOps source and the
  one gitea-mirror could never finish mirroring; its de-mirror is gated behind the Flux source
  cutover ([ADR-0014](adr-0014-flux-source-forgejo.md)) — cutover-last so the platform never loses
  its footing.

## Alternatives considered

- **Keep the read-only mirror; cut releases only on GitHub.** Forgejo would only build images on a
  release mirrored down from GitHub. Rejected: it keeps GitHub load-bearing for the release step and
  defeats the whole point of in-cluster, Forgejo-authoritative CI — the opposite of the migration's
  north star.
- **Writable mirror with bidirectional sync.** Rejected: tag divergence + clobbering, and a fragile
  two-way sync is exactly the failure mode pull-mirrors avoid.
- **GitHub→Forgejo *push*-mirror (GitHub pushes; Forgejo writable).** Workable, and it keeps GitHub
  the source. Rejected here because the goal is to **archive** GitHub — de-mirroring and making
  Forgejo the source is simpler and removes the GitHub dependency rather than re-plumbing it.
