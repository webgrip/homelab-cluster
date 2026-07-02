# RFC: GitHub Actions runner infrastructure — retire it on purpose

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** The in-cluster GitHub Actions runners (ARC + two scale sets) have been throttled to
> **`minRunners: 0, maxRunners: 0`** since the 2026-06-18 Longhorn incident, with a "TEMP" comment
> and restore notes. Two weeks on, the Forgejo runner is the proven CI path and repos are migrating
> off GitHub — the "temporary" zero is a retirement that nobody has decided. This RFC decides it:
> either ARC comes back at low counts to serve the GitHub-leading tail, or it is retired now with a
> clean teardown list. Carrying a dead, privileged-capable runner stack labelled "TEMP" is the
> worst available option.

## Why

Verified state (2026-07-02), `kubernetes/apps/arc-systems/`:

- `actions-runner-controller` runs; both scale sets — `arc-runner-set` (plain) and
  `arc-runner-set-heavy` (hand-rolled **privileged DinD** sidecar) — are pinned `0/0` with the
  comment "TEMP (2026-06-18 Longhorn IM-cpu detonation) … suspended to 0 runners" and restore
  notes (light 1/3, heavy 0/2). GitHub App credentials ride OpenBao (`arc/runners`).
- Meanwhile the **Forgejo runner** (KEDA ScaledJob, 2–6, [ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md)
  step 1) is proven on real jobs, and repos become Forgejo-authoritative one by one
  ([ADR-0024](../adr/adr-0024-forgejo-leading-application-repos.md)).

The undecided part is what the zero *means*:

- **If GitHub-leading repos still need self-hosted CI**, ARC at 0/0 means their workflows have
  been queueing or failing (or silently falling back to GitHub-hosted runners, where the
  workflows allow it) for two weeks — either it matters, and ARC should come back at the restore
  counts, or it demonstrably hasn't mattered, which is the strongest possible evidence the
  dependency is already gone.
- **If it is retirement**, the current state is untidy and mildly risky: a controller with org
  credentials and a privileged-DinD pod template sit live in the cluster serving no purpose —
  surface without function. The forge-exit RFCs plan the *Renovate* and *Flux* GitHub retirements
  precisely; the runner leg has no plan at all.

There is also a policy echo: the heavy set's privileged DinD predates the ADR-0008 analysis and
carries none of its topology reasoning — if ARC *did* return, it should return under the same
"privilege and secrets never share a container" rule, not the 2026-06-12 shape.

## Proposal

**Decide from evidence, then do one of two things** (single new ADR either way):

1. Enumerate what actually consumed `arc-runner-set*` labels: which GitHub-resident `webgrip/*`
   workflows target self-hosted runners, and what has happened to them since 06-18 (two weeks of
   real-world data answers this — check Actions queues/failures on the still-GitHub-leading
   repos, `homelab-cluster` included).
2. **Path A — Retire now** (the leaning, if step 1 shows no queued/failing consumers): delete
   `kubernetes/apps/arc-systems/`, revoke + remove the GitHub App / `arc/runners` OpenBao entry,
   and record that GitHub-hosted runners serve any straggler workflow until its repo migrates
   (public repos: free minutes; nothing in the tail is build-heavy once images build on Forgejo).
   The [ADR-0011](../adr/adr-0011-dual-run-renovate-forgejo.md) precedent applies: retirement is
   a deletion, proven safe by the period in which the thing was already effectively off.
3. **Path B — Restore deliberately** (if step 1 finds real consumers): un-throttle to the restore
   counts as an explicit bridge with a sunset tied to the last consumer repo's Forgejo cutover —
   and re-shape the heavy set per ADR-0008's topology rules rather than resurrecting the old
   privileged template unchanged.

Either path ends the "TEMP" state with a record; the teardown list (namespace, App credential,
OpenBao path, any org runner-group config) is the ADR's checklist so nothing orphaned survives.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | ARC end-state: retire now vs bridge-until-cutover, with teardown/sunset list (new) |

## Out of scope

- The Forgejo runner and its hardening — [ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md).
- Repo migration order — [ADR-0024](../adr/adr-0024-forgejo-leading-application-repos.md).
- CI performance — the [CI-pipeline RFC](rfc-ci-pipeline-performance.md).

## References

- [arc-runners doc](../general/arc-runners.md) ·
  [Bringing the Forge Home](../blogs/2026-06-12-bringing-the-forge-home.md)
- Incident: [2026-06-18 Longhorn IM-cpu detonation](../incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md)
  — the trigger of the current 0/0 state
