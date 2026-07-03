# RFC: Backup & disaster recovery as a program

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** Backups exist per-app (CNPG barman, Longhorn BackupTarget, OpenBao snapshots) but
> nobody ever decided the *program*: what must survive which failure, every copy lands on the same
> single Garage host, the OpenBao unseal key needed to *use* its snapshots lives only inside the
> cluster those snapshots protect, and metrics/logs/traces have no decided durability at all. This
> RFC establishes the data-protection tier map, closes the unseal-key hole, and sets the drill
> cadence — turning a pile of mechanisms into a recovery story.

## Why

What is protected today (verified in-tree 2026-07-02), and the holes:

| Data | Mechanism | Hole |
| --- | --- | --- |
| 10 CNPG databases | barman WAL + `ScheduledBackup` → Garage | single target; restore drilled for some, not all |
| guac DB | nightly `pg_dump` → Garage | no PITR; deviation unrecorded ([Postgres RFC](rfc-postgres-data-layer.md)) |
| Longhorn volumes | `BackupTarget` → Garage | **which** volumes have RecurringJobs is undecided/unaudited |
| OpenBao | nightly raft snapshot → Garage (14 kept) | **unseal key exists only in the in-cluster `openbao-keys` Secret** — the [restore runbook](../runbooks/openbao-restore.md) itself says the snapshots are "not a complete DR story" without it |
| Git (the cluster's definition) | GitHub today; Forgejo→GitHub/Codeberg mirrors planned | solid — [ADR-0012](../adr/adr-0012-external-bootstrap-fallback-source.md)/[0020](../adr/adr-0014-codeberg-offsite-push-mirror.md) own it |
| Docs | Codeberg Pages (off-site) | solid — [ADR-0038](../adr/adr-0038-codeberg-pages-techdocs.md) |
| Metrics (VMSingle, 15d) | **nothing** | explicitly none (ADR-0034); never decided as acceptable |
| Logs (Loki, 30d) / traces (Tempo, 14d) | data *lives on* Garage but Garage has no second copy | loss-tolerance never decided |
| Harbor blobs | on Garage; proxy-cache re-derivable, `webgrip/*` artifacts are not | rebuild-vs-backup never decided |
| The Garage host itself | **nothing backs up the backup target** | the L5 SPOF, in one line |

Three structural problems cut across the table:

1. **Everything converges on one host.** Every backup mechanism, however good, writes to the same
   off-cluster Garage box. A both-worker outage is survivable; a Garage disk failure plus any
   cluster problem is not. The 3-2-1 principle exists in the
   [layered-hardware RFC](rfc-layered-hardware-architecture.md) as L5 aspiration, not as a decision.
2. **The OpenBao circular dependency.** Secrets are the recovery keys for everything else (S3
   creds, tokens), their backup is encrypted, and the key that decrypts it lives in the cluster
   being recovered. (The CLAUDE.md SOPS floor names an "openbao unseal" file — whether that copy
   is current with the live key is exactly the kind of thing only a decided escrow procedure
   guarantees.)
3. **RPO/RTO are undefined outside databases.** The [backup-tiers doc](../general/database-backup-tiers.md)
   classifies *databases* well; nothing classifies volumes, observability data, or registry
   artifacts, so "is this backed up?" has no checkable answer.

## Proposal

1. **Extend the tier model to all data** (new ADR): every durable dataset gets a tier —
   *must survive total cluster + Garage loss* (Git, OpenBao snapshot+key, tier-1 DB backups) /
   *must survive cluster loss* (all DB backups, Longhorn backups of stateful PVCs) /
   *acceptable loss, bounded by retention* (metrics, traces, proxy-cache blobs — decided, not
   defaulted) — recorded next to the existing database tiers, with logs explicitly classified
   (30d of logs may be evidence; decide).
2. **Escrow the unseal key out-of-cluster** (new ADR): a deliberate, verified copy of
   `openbao-keys` outside the cluster — the natural fit is the existing SOPS floor (age-encrypted
   in-repo), refreshed by procedure whenever the key changes, with the check wired into the
   restore drill. This single move converts the nightly snapshots from theater into DR.
3. **Add the second copy for tier-⩾cluster-loss data** (new ADR, mechanism from the
   [object-storage RFC](rfc-object-storage-garage.md)): whether a second Garage node, bucket
   replication, or dual targets — the *requirement* is decided here: no tier-1 dataset with a
   single physical copy.
4. **Audit + declare Longhorn RecurringJob coverage** (new ADR): enumerate PVCs that are the
   *only* home of app state (non-CNPG apps: forgejo-data, freshrss config, n8n, …), ensure each
   has a recurring backup to the target, and make the coverage list a checkable artifact
   (`scripts/posture-counts.sh` style), not tribal knowledge.
5. **Set the drill cadence** (new ADR): the CNPG restore drill exists (skill + runbook); extend to
   a quarterly rotation — one CNPG PITR, one Longhorn volume restore, one OpenBao
   snapshot-restore-and-unseal (proves the escrowed key), and, once per hardware cycle, the
   cold-bootstrap path of ADR-0012. A backup that has never restored is a hypothesis.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Data-protection tier map covering all durable data (new) |
| candidate | — | OpenBao unseal-key escrow out-of-cluster (new) |
| candidate | — | No single-copy tier-1 data — second backup leg required (new) |
| candidate | — | Longhorn RecurringJob coverage list (new) |
| candidate | — | Restore-drill cadence (new) |

## Out of scope

- The Git/GitOps DR ring — decided (ADR-0012/0020), only referenced here.
- The S3 substrate's own architecture — the [object-storage RFC](rfc-object-storage-garage.md).
- Hardware purchases for a second target — [layered-hardware](rfc-layered-hardware-architecture.md) L5.

## References

- [database-backup-tiers](../general/database-backup-tiers.md) ·
  [cnpg-backups runbook](../runbooks/cnpg-backups.md) ·
  [openbao-restore runbook](../runbooks/openbao-restore.md) · the `restore-drill` skill
- [ADR-0008](../adr/adr-0008-confine-longhorn-to-workers.md) — the "DR via external Garage"
  assumption this RFC stress-tests
