---
status: accepted
date: 2026-10-25
decision-makers: Ryan Grippeling
---

# Backups land on a capped Garage, are proven by canary drills, and lock elsewhere

## Context and Problem Statement

Every homelab backup (CNPG WAL and base backups, Longhorn volumes, OpenBao snapshots, InvoiceNinja
dumps) and Unfold's etcd and OpenTofu state land on one rented host, garage-fsn1: Garage v2.1, one
node, RAID1. On 2026-10-25 it had 44 GB of 484.8 GB free and 769 unreadable blocks. One key,
`cnpg-backup`, writes and deletes all homelab backups, and Garage has neither versioning nor object
lock, so the cluster can erase its own history. Six of eight database restore drills were
suspended, no volume or OpenBao snapshot had ever been restored, and the stale-drill alert could
not fire. Where should backups land, what makes one copy immutable, and how is a backup proven to
restore? The full program, tiers and owner steps are in the
[backup and DR RFC](../rfc/rfc-backup-dr.md).

## Decision Drivers

* A compromised cluster, or a rogue agent inside it, must not be able to delete every copy.
* A stolen owner credential must not be able to purge history inside the detection window.
* A backup counts only once a drill has restored it and found a fresh canary.
* The backup host must never fill silently again; a full Garage disk acknowledges writes and stores
  empty blocks.
* No SaaS in the operations path; plain EU storage only. Spending is the owner's call.
* Unfold and the homelab share one contract (Unfold RFC 0001).

## Considered Options

* Garage stays the capped landing copy; drills prove every tier; the immutable copy is a Hetzner
  Storage Box in a separate account plus an OVHcloud bucket with a compliance lock
* Object-lock first: barman and Longhorn write straight to Hetzner Object Storage with a lock,
  OVH as the second copy, garage-fsn1 retired from the backup path
* A second self-hosted box at home (ZFS snapshots, restic append-only) plus one small locked bucket
* Keep garage-fsn1 alone and add more drills

## Decision Outcome

Chosen option: **"Garage stays the capped landing copy; drills prove every tier; the immutable copy
is a Storage Box in a separate account plus an OVH compliance lock"**, because it is the only
option that survives both a cluster compromise and a stolen owner credential, it costs about
€ 5,50 a month, and it keeps the fast WAL landing that CNPG already uses.

* **Tiers.** Every dataset is T0 (recovery keys, escrowed twice offline), T1 (survives cluster and
  garage-fsn1 loss, three copies, one immutable), T2 (survives cluster loss) or T3 (accepted loss).
  Metrics, traces and non-audit logs are T3; the Kubernetes audit trail is T2.
* **Landing.** garage-fsn1 keeps CNPG, Longhorn, OpenBao and homelab etcd backups. Every bucket gets
  a Garage quota (only the admin token can change it), and `GarageOffsiteDiskFullIn14Days` warns
  two weeks ahead.
* **Keys.** Garage cannot separate put from delete: its `write` permission includes DeleteObject
  and lifecycle changes, keys scope by bucket and not by prefix, and there is no lock. So new
  writers get keys without `read`, drills get keys with only `read`, `cnpg-backup` loses `owner`,
  and nothing on Garage is called immutable.
* **Immutable copy (Phase 2, owner buys).** A Storage Box BX11 in a separate Hetzner account with
  API-only weekly snapshots, and an OVHcloud Standard 1-AZ bucket with a 30-day compliance lock.
  The cluster holds only write credentials for both; the accounts' control planes live with the
  owner, never in the cluster, OpenBao or CI.
* **Proof.** Drills restore real data and check a canary: CNPG writes a nonce row and waits for its
  WAL to archive; Longhorn checks that restored files are as fresh as the backup; OpenBao restores
  a snapshot into a scratch server, unseals it with the live key, generates a root token there and
  reads a nonce; etcd checks freshness in-cluster and is decrypted by hand quarterly with the
  escrowed identity. Each drill re-creates a `restore-verified-<kind>-<name>` ConfigMap on success,
  which becomes `backup:restore_last_success_timestamp_seconds`. Each drill is mutation-tested:
  corrupt fails, stale fails, good passes.
* **Enrolment.** Longhorn backup membership lives only in the `longhorn-backup-enrollment` Kyverno
  policy; hand labels are gone.

### Consequences

* Good, because every dataset has a stated tier, RPO, RTO and copy count that a dashboard checks.
* Good, because a drill failure or a dataset that was never backed up raises an alert within days,
  not at restore time.
* Good, because in Phase 2 neither a compromised cluster nor a stolen owner credential can erase
  the last 30 days.
* Bad, because until the owner buys Phase 2 there is still no immutable copy; a cluster compromise
  can still delete everything on garage-fsn1.
* Bad, because a compliance lock bills deleted versions for the lock window (about 1.5 times the
  live set), and the lock window is also the detection deadline.
* Bad, because the owner runs the garage-fsn1 commands by hand until the declarative apply script
  (Phase 1b) exists.
* Bad, because the drills add load: one full database restore a weekday and up to three volume
  restores a weekend, all in daytime UTC.

### Confirmation

* `backup:restore_last_success_timestamp_seconds` exists for every dataset whose
  `backup:dataset_copies` row has `drill="weekly"` or `drill="daily"`, and the Backups dashboard
  shows no dataset older than its interval.
* `./scripts/test-vmalert-rules.sh` passes, including the cases that prove `CNPGRestoreTestStale`
  fires per `exported_namespace` and `LonghornVolumeBackupStale` fires for a never-backed-up volume.
* `garage bucket info <bucket>` on garage-fsn1 shows a quota on every bucket, and `garage key info
  cnpg-backup` shows no owner permission.
* Phase 2: `aws s3api get-object-lock-configuration --bucket webgrip-homelab-vault` returns
  `COMPLIANCE` and 30 days; a delete of a locked version with the writer key returns 403.

## Pros and Cons of the Options

### Object-lock first at Hetzner Object Storage

* Good, because no self-operated storage remains in the backup path.
* Good, because it matches Unfold's primary target.
* Bad, because barman and Longhorn delete every night, so the lock grows storage by the window,
  and Hetzner has no hard quota.
* Bad, because Hetzner rejects conditional writes on versioned buckets and bills objects under
  64 KB as 64 KB.
* Bad, because the vault and the landing copy would sit at the same provider as Unfold and
  garage-fsn1.

### A second self-hosted box at home

* Good, because it costs no per-GB fees and restores at LAN speed.
* Bad, because the owner is admin on every copy, so a stolen owner credential reaches all of them.
* Bad, because it shares fire and theft risk with the cluster and is one more machine to run.

### garage-fsn1 alone, more drills

* Good, because it costs nothing.
* Bad, because a full disk, a host loss or the cluster's own key still takes every copy.

## More Information

* Technical story: [Backup and disaster recovery program](../rfc/rfc-backup-dr.md).
* Runbooks: [restore drills](../runbooks/backup-restore-drills.md),
  [garage-offsite](../runbooks/garage-offsite.md).
* Shares tiers, metric names and the four portability rules with Unfold RFC 0001 (Object storage).
* Re-evaluate when Garage ships versioning and object lock (v3), or when the landing copy fills
  again despite quotas (then move the landing to option B).
* 2026-10-25 — Accepted by Ryan Grippeling for Phase 1. Phase 2 waits for the owner's purchase.
