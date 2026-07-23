# RFC: Forgejo high availability — rolling updates without pretending it's HA-native

> Status: **Proposed** · Date: 2026-07-23

> **TL;DR.** Forgejo is the cluster's git server *and* Flux's source of truth, yet it runs
> single-replica with `strategy: Recreate` — every upgrade is a ~1-minute outage and every
> incident-day restart compounds (2026-07-23: four restarts hit three separate landmines —
> Authentik init coupling, a cross-node Multi-Attach wait, and a full-volume fsGroup chown).
> Upstream Forgejo does **not** support clustering, but a 2-replica deployment behind shared
> storage + a shared queue/cache is a known-working "unsupported" configuration (all other state
> is already externalized here: sessions→Postgres, LFS/packages/attachments→Garage S3). This RFC
> proposes getting there in three gated phases, with the storage decision (Longhorn RWX) called
> out as the real risk. Until Phase 3 lands, the mitigations shipped 2026-07-23 (zero-restart UI
> assets, `fsGroupChangePolicy: OnRootMismatch`, worker-1 preference, VIK-579 init decoupling)
> already shrink the practical windows to seconds-per-upgrade.

## Why now

- **Blast radius**: Forgejo down = git down = Flux source down = the GitOps loop can't ship the
  fix for whatever broke it (seen live 2026-07-23, twice). A second replica breaks that loop.
- **Rolling updates**: `Recreate` exists solely because the repo volume is RWO. With RWX +
  `maxUnavailable: 0` rolling, upgrades become zero-downtime.
- **What HA here does NOT mean**: multi-writer database (stays CNPG single-instance per
  rfc-postgres-data-layer), or surviving loss of both workers. Target: survive one node loss with
  ≤ ~1 min blip, and survive planned rollouts with zero blips.

## Current-state inventory (verified 2026-07-23)

| Concern | Today | Multi-replica ready? |
|---|---|---|
| Repos/config (`forgejo-data` PVC) | Longhorn RWO, `longhorn` SC | ❌ needs RWX or migration |
| Sessions | Postgres (`session.PROVIDER: db`) | ✅ |
| Cache | `ADAPTER: memory` | ❌ needs valkey/redis |
| Queue | `TYPE: level` (file DB **on the data volume**) | ❌ needs redis protocol |
| LFS / packages / attachments / avatars / artifacts | Garage S3 | ✅ |
| DB | CNPG `forgejo-db` | ✅ (own posture) |
| Indexer | default bleve (file) | ⚠️ shared-volume OK; or disable code indexer |
| SSH host keys | on data volume (`APP_DATA_PATH/ssh`) | ✅ shared volume ⇒ identical keys |
| Cron/scheduled tasks | in-process | ⚠️ duplicate execution across replicas (see risks) |

## Proposal — three gated phases

### Phase 1 — externalize queue+cache to valkey (safe now, zero HA commitment)
Deploy a small valkey (existing house pattern, e.g. litellm-valkey) in the forgejo namespace;
set `queue.TYPE: redis` + `cache.ADAPTER: redis` (+ `session` stays db). Wins even at one
replica: the level-queue file DB stops living on the git volume (it has wedged Gitea instances
on unclean shutdown), and restarts stop replaying queue state. Verifiable alone; reversible.

### Phase 2 — repo storage RWO → Longhorn RWX (the decision + the migration)
- **Decision**: `longhorn-rwx` SC is Kyverno-blocked (`disallow-rwx-pvcs`, allowlist-gated —
  ADR-0010). Adding `forgejo-data` to the allowlist is a deliberate policy decision, not an
  exception-waiver (aligns with the no-policy-exceptions stance: amend the policy's allowlist
  with a recorded rationale).
- **Eyes-open trade-off**: Longhorn RWX = a share-manager NFS pod per volume — itself a single
  point that *migrates* on node failure (~30–60s blip). So node-loss tolerance improves from
  minutes to ~a minute, not to zero. Rolling updates DO become truly zero-downtime (both
  replicas mount concurrently during the roll).
- **Migration**: one planned downtime window — scale to 0, mount old RWO + new RWX in a copy
  Job (rsync -a), flip `claimName`, scale up. Rehearse the copy read-only first; keep the RWO
  volume as instant rollback for a week.
- **Alternative considered**: external NFS off-cluster (the Garage box) — rejected for now
  (new SPOF hardware, backup story diverges); revisit if share-manager proves flaky.

### Phase 3 — 2 replicas + RollingUpdate + the duplication audit
`replicaCount: 2`, `strategy: RollingUpdate` (`maxUnavailable: 0`, `maxSurge: 1`), a PDB
(`minAvailable: 1`), pod anti-affinity across the two workers. **Gate before calling it done**:
the duplicate-cron assessment — Forgejo has no leader election, so scheduled tasks (mirror
syncs, cleanup) run on both replicas. Audit each enabled cron for idempotency; disable or
tolerate per item (gitea-mirror push-mirrors are idempotent-push; repo-archive cleanup is
idempotent; document each). Also verify: git push races through two replicas (hooks are
fs-level, expected safe), Actions job scheduling (DB-transactional, expected safe), and a full
rolling upgrade under a continuous clone/push loop as the acceptance test.

## Risks / honest caveats

1. **Unsupported territory**: upstream explicitly doesn't support clustering; Codeberg runs one
   instance. We rely on state externalization + shared fs semantics. Mitigation: the Phase 3
   acceptance test (rolling upgrade under live git traffic) plus easy rollback to 1 replica.
2. **Share-manager SPOF** (above) — "HA" is honestly "fast-failover", which is the actual goal
   ("don't go *truly* down").
3. **Cron duplication** — bounded by the audit; worst plausible effect is duplicate mirror
   pushes (force-push idempotent).
4. **Fringe pressure**: replica 2 lands on fringe-workstation by pool; acceptable for a
   stateless-ish web replica, and the DIMM upgrade (VIK-331) is in flight.

## Rollout & verification

Each phase is its own ticket (Homelab Roadmap, sequenced `precedes`): VIK-582 (valkey) →
VIK-583 (RWX decision+migration, `uncertainty/high` → starts with the rehearsal spike) →
VIK-584 (replicas+rolling+audit). Phase acceptance = the mutation tests named in each ticket,
run live, not proxies. Related: VIK-579 (init decoupling) is independent and stays open.
