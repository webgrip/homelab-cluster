# RFC: Backup and disaster recovery program

> Status: **Accepted** for Phase 1 (built 2026-10-25) · **Proposed** for Phase 2 (paid) and Phase 3 ·
> Owner: Ryan Grippeling · Decision record: [ADR-0081](../adr/adr-0081-backups-land-on-a-capped-garage-are-proven-by-canary-drills-and-lock-elsewhere.md) ·
> Part of the [decision-landscape gap register](../adr/landscape.md) · Shares its contract with
> [Unfold RFC 0001, Object storage](https://forgejo.webgrip.dev/webgrip/unfold-cluster/src/branch/main/docs/rfc/0001-security-architecture.md#object-storage)
>
> **TL;DR.** Every backup the homelab makes lands on one rented host, garage-fsn1, under one key
> that can also delete it, and that host was 9% from full on 2026-10-25. Six of eight restore
> drills were switched off and the alert that should have noticed could never fire. This RFC
> turns the pile of mechanisms into a program: every dataset gets a tier with an RPO and RTO,
> every tier gets a copy count, every copy gets a drill that restores real data and proves a
> canary came back, and every drill result is a metric with an alert. Phase 1 (free) is built:
> fixed alerts, declared enrolment, canary drills for databases, volumes, OpenBao and etcd, a
> homelab etcd backup, read-only and write-only Garage keys where Garage allows it, a 14-day
> capacity forecast and a Backups dashboard. Phase 2 (about € 5,50 per month) adds the copy the
> cluster cannot delete: a Hetzner Storage Box in a separate account and an OVHcloud bucket with a
> 30-day compliance lock.

## Terms

| Term | Meaning here |
| --- | --- |
| RPO | Recovery point objective: how much recent data a restore may lose |
| RTO | Recovery time objective: how long a restore may take, from decision to working service |
| Landing copy | The first off-cluster copy, written continuously by the cluster (garage-fsn1 today) |
| Vault copy | A copy whose history the cluster cannot delete: API-only snapshots or a compliance object lock |
| Canary | A small value written just before a backup and checked after a restore, which proves the restore holds recent data |
| Drill | A scheduled job that restores a backup into scratch space, checks it, records the result and cleans up |
| Escrow | A copy of a recovery key kept outside every system it protects |

## Why

The [backup audit of 2026-10-25](#evidence) found:

1. **One host, one key.** CNPG (12 clusters), Longhorn (22 volumes), the OpenBao snapshots, the
   InvoiceNinja dumps and Unfold's etcd and OpenTofu state all land on garage-fsn1 (Garage v2.1,
   `replication_factor = 1`, RAID1). The key `cnpg-backup` writes and deletes all homelab data.
   Garage has no versioning and no object lock, so a delete is final.
2. **The host is nearly full and already losing blocks.** 44.0 GB free of 484.8 GB, minus 29 GB
   in one day, and 769 blocks that fail resync. On a full disk Garage acknowledges a PUT and
   stores an empty block, so a full disk corrupts backups silently.
3. **Restores were unproven.** Six of eight CNPG drills were suspended; Forgejo's last passed 135
   days earlier. No Longhorn volume and no OpenBao snapshot had ever been restored.
   `CNPGRestoreTestStale` matched on `namespace` while kube-state-metrics puts the app namespace in
   `exported_namespace`, so one suspended drill silenced the alert for every namespace.
4. **Hand-made state.** forgejo-data, gitea-mirror, data-garage-0 and meta-garage-0 were backed up
   only because someone had labelled their Longhorn volumes by hand. A volume that has never been
   backed up reports `longhorn_volume_last_backup_at = 0`, which `LonghornVolumeBackupStale`
   excluded, so a recreated volume would have dropped out silently.
5. **No etcd backup** and **the OpenBao unseal key existed only inside the cluster**, the hole the
   2026-07-02 version of this RFC named. The owner is escrowing the unseal key, the age key and
   the Unfold passwords by hand on 2026-10-25.
6. **The audit trail was not backed up.** `vlsingle-victorialogs-audit` holds the evidence of an
   attack and had zero copies.

## Principles

1. **3-2-1-1-0.** Three copies of every T1 dataset, on two different systems, one off-site, one
   immutable or offline, and zero errors in the last verified restore. The live volume is not a
   copy.
2. **The cluster writes, it never erases history.** Every credential the cluster holds for a
   backup store either cannot delete or deletes only on a store that has a copy the cluster cannot
   reach. The control plane of the vault (Hetzner account, OVH account) is never in the cluster,
   in OpenBao or in CI.
3. **A backup is a hypothesis until a drill restores it.** A drill restores real bytes, checks a
   canary, fails on stale or corrupt data, and publishes its last success as a metric with an alert.
   Each drill is mutation-tested: corrupt must fail, stale must fail, good must pass.
4. **Hard caps everywhere.** Every bucket has a quota, every writer has bounded retention, and the
   capacity forecast warns 14 days ahead, long enough for a person to act.
5. **Same contract as Unfold.** The four portability rules of Unfold RFC 0001 apply to both
   clusters: data is encrypted before upload where the tool allows it (age, restic, kopia); copies
   between providers are made with rclone under separate write-only credentials, never with a
   provider's replication feature; only versioning and a bucket-default object lock are used;
   provider-specific features (SSE-KMS, lifecycle beyond expiry, replication APIs, IAM dialects)
   are avoided. Tier names and metric names are shared.

## Tiers

| Tier | Must survive | RPO | RTO | Copies | Immutable copy |
| --- | --- | --- | --- | --- | --- |
| **T0** recovery keys | everything, including the loss of the owner's workstation | change-driven | 1 h | 2 offline, outside every system they unlock | paper or hardware token |
| **T1** precious and critical | cluster loss **and** garage-fsn1 loss | 5 min for Postgres (WAL), 24 h for volumes and snapshots | 4–8 h | 3 (landing + 2 vaults) | yes, Phase 2 |
| **T2** worth keeping | cluster loss | 24 h | 1 day | 2 off-cluster (landing + 1 vault) | yes, Phase 2 |
| **T3** accepted loss | nothing; rebuilt or re-downloaded | n/a | rebuild | 0 | no |

These recovery tiers are a different axis from the Postgres retention tiers in
[database-backup-tiers](../general/database-backup-tiers.md), which decide how long WAL is kept.
A T1 database can sit in retention tier 2 (14 days of PITR).

### Every dataset

Sizes and times are from the audit (2026-10-25). "Drill" names the restore check that proves the
dataset, and how often it runs.

| Dataset | Kind | Tier | Mechanism | RPO | RTO | Drill |
| --- | --- | --- | --- | --- | --- | --- |
| OpenBao unseal key | escrow | T0 | password manager + sealed paper; fingerprint in git | change | 1 h | weekly fingerprint match, quarterly by hand |
| SOPS age key (`age.key`) | escrow | T0 | password manager + sealed paper | change | 1 h | quarterly by hand (decrypt `talsecret`) |
| homelab etcd age identity | escrow | T0 | password manager + sealed paper | change | 1 h | quarterly by hand (decrypt + restore a snapshot) |
| Unfold state passphrase, Unfold etcd age identity | escrow | T0 | password manager + sealed paper (+ OpenBao) | change | 1 h | Unfold's daily etcd check; quarterly by hand |
| Owner SSH key, Hetzner/OVH 2FA recovery codes | escrow | T0 | password manager + sealed paper | change | 1 h | yearly |
| forgejo/forgejo-db | cnpg | T1 | barman WAL + daily base, 14 d | 5 min | 4 h | weekly canary restore (Mon 10:00 UTC) |
| forgejo/forgejo-data (repos, LFS, packages) | longhorn | T1 | `gitops-backup`, daily, retain 7 | 24 h | 8 h | weekly restore (Sat 10:00) |
| security/openbao-raft | openbao | T1 | raft snapshot 03:00, keep 14; also Longhorn `data-openbao-0` | 24 h | 2 h | weekly restore + unseal (Sun 11:00) |
| talos/homelab-etcd | etcd | T1 | talos-backup every 6 h, age-encrypted | 6 h | 4 h | daily freshness check, quarterly decrypt + restore by hand |
| authentik/authentik-db | cnpg | T1 | barman, 30 d | 5 min | 4 h | weekly (Mon 13:00) |
| vikunja/vikunja-db | cnpg | T1 | barman, 14 d, plus DR standby | 5 min | 4 h | weekly (Tue 10:00) |
| ploeg/ploeg-db | cnpg | T1 | barman, 14 d, plus DR standby | 5 min | 4 h | weekly (Tue 13:00) |
| n8n/n8n-db | cnpg | T1 | barman, hibernated since 2026-10-10 | static | 4 h | suspended while hibernated |
| sparkyfitness/sparkyfitness-db | cnpg | T1 | barman, hibernated since 2026-10-24 | static | 4 h | suspended while hibernated |
| vikunja/vikunja (attachments) | longhorn | T1 | `gitops-backup` | 24 h | 4 h | weekly restore (Sat 14:00) |
| invoiceninja/invoiceninja-storage | longhorn | T1 | `gitops-backup` | 24 h | 1 day | weekly restore (Sun 14:00), no freshness check (app at 0) |
| invoiceninja/invoiceninja-mariadb | longhorn | T1 | `gitops-backup` + dump (suspended) | 24 h | 1 day | Phase 3 rotation |
| authentik/authentik-media | longhorn | T1 | `gitops-backup` | 24 h | 1 day | Phase 3 rotation |
| ploeg/unfold-data | longhorn | T1 | `gitops-backup` | 24 h | 4 h | Phase 3 rotation |
| ai/omnigraph-014-state | longhorn | T1 | `gitops-backup` | 24 h | 1 day | Phase 3 rotation |
| n8n/n8n-data, sparkyfitness/sparkyfitness-uploads | longhorn | T1 | `gitops-backup` | 24 h | 1 day | Phase 3 rotation |
| security/data-openbao-0 | longhorn | T1 | `gitops-backup` (second form of OpenBao) | 24 h | 2 h | covered by the OpenBao drill |
| Git refs (webgrip org) | git | T1 | Forgejo volume + GitHub push-mirror | minutes | 4 h | cold bootstrap from GitHub, yearly |
| ai/litellm-db | cnpg | T2 | barman, 30 d | 5 min | 1 day | weekly (Wed 10:00) |
| harbor/harbor-db | cnpg | T2 | barman, 3 d | 5 min | 1 day | weekly (Wed 13:00) |
| freshrss/freshrss-db | cnpg | T2 | barman, 3 d | 5 min | 1 day | weekly (Thu 10:00) |
| observability/grafana-db | cnpg | T2 | barman, 3 d | 5 min | 1 day | weekly (Thu 13:00) |
| security/dependency-track-db | cnpg | T2 | barman, 3 d | 5 min | 1 day | weekly (Fri 10:00) |
| backstage/backstage-db | cnpg | T2 | barman, hibernated | static | 1 day | suspended while hibernated |
| observability/vlsingle-victorialogs-audit | longhorn | T2 | `gitops-backup`, retain 7 (new) | 24 h | 1 day | Phase 3 rotation |
| garage/data-garage-0, garage/meta-garage-0 (Harbor, techdocs, omnigraph-archive) | longhorn | T2 | `gitops-backup-bulk`, retain 2 (was 7 by hand) | 24 h | 1 day | Phase 3 rotation |
| forgejo/gitea-mirror | longhorn | T2 | `gitops-backup-bulk`, retain 2 | 24 h | 1 day | none |
| freshrss/freshrss, minecraft/minecraft, ai/open-webui-data, ai/omnigraph-state, ai/omnigraph-brain-eval-store, sparkyfitness/sparkyfitness-backup | longhorn | T2 | `gitops-backup` (brain-eval: own group, retain 14) | 24 h | 1 day | none |
| Unfold etcd, Unfold OpenTofu state | etcd / state | T2 | garage-fsn1 until Unfold delivery step 3, then RFC 0001 targets | 6 h / per apply | 1 day | Unfold's daily `etcd-backup-check` |
| Immich photos (garage-fsn1 `/srv/immich`) | host | T1 (personal) | **none today** | n/a | n/a | Phase 2: restic to the Storage Box |
| observability/vmsingle-vmsingle, vlsingle-victorialogs, vtsingle-victoriatraces | longhorn | **T3** | unenrolled 2026-10-25 | n/a | rebuild | none |
| Harbor proxy cache, forgejo-cache-server-data, trivy DBs, harbor-redis, searxng, tei models, unfold-workspaces, pewter-claude-login | various | T3 | none | n/a | rebuild | none |
| Headscale state (Unfold) | host | T2 | **none today**; Unfold's to fix | n/a | 1 day | Unfold ticket |

Harbor's own `webgrip/*` images sit inside data-garage-0 next to the proxy cache. They are
rebuildable from CI, but a rebuild gives new digests that no pinned manifest or signature
matches, so the volume stays T2 rather than T3. Phase 3 moves the proxy cache to a bucket on a
separate, unbacked-up volume.

## 3-2-1-1-0 on real targets

| Rule | Today (Phase 1) | Phase 2 |
| --- | --- | --- |
| 3 copies | live + garage-fsn1 (2) | live + garage-fsn1 + Storage Box + OVH (4 for T1, 3 for T2) |
| 2 systems | Longhorn/CNPG + Garage | + SFTP Storage Box (ZFS snapshots) + OVH S3 |
| 1 off-site | garage-fsn1 (Falkenstein) | + Storage Box (Helsinki, other account) + OVH (Gravelines, France) |
| 1 immutable | **none** | Storage Box snapshots (API-only, weekly, 10 kept) and OVH compliance lock 30 days |
| 0 errors | canary drills with alerts (built) | + a monthly restore from each vault |

Phase 1 cannot meet "1 immutable": Garage cannot hold one (next section). That gap is the reason
Phase 2 exists, and it stays open until the owner buys it.

## Threat model

| Threat | What it can do today | Control in Phase 1 | Control in Phase 2 | Residual |
| --- | --- | --- | --- | --- |
| **Cluster compromise** (every Secret readable, every in-cluster credential usable, incl. a rogue agent) | Delete or overwrite every homelab backup with `cnpg-backup`; replace lifecycle rules; delete Longhorn BackupVolumes | New writers get write-only keys; drills get read-only keys; `cnpg-backup` loses `owner`; alerts on missing backups and failed drills | Vault copies the cluster cannot delete: Storage Box snapshots are created and deleted only through the Hetzner API of another account; OVH objects are locked in compliance mode for 30 days | Detection must happen inside 30 days (the lock window is the detection deadline) |
| **Stolen owner credential** (SSH key, OpenBao admin, laptop) | Root on garage-fsn1; every key there | Escrow keeps recovery possible | Compliance lock: not even the OVH account owner can purge a locked version before it expires; the Storage Box sits in a separate Hetzner account with its own login and hardware 2FA | A thief holding both the Hetzner vault account and the OVH account can stop new copies but cannot erase locked history |
| **Hetzner account loss** (billing lapse, lockout, abuse report) | garage-fsn1, Unfold and the Storage Box gone together if in one account | none | The vault Storage Box lives in a separate Hetzner account; OVH is another company | Two-provider dependency (both rented) |
| **garage-fsn1 loss** (RAID1 double failure, LMDB corruption, full disk) | Every backup and Immich gone | Quotas, 14-day forecast, `metadata_auto_snapshot_interval` (owner) | Restore from the vaults | Immich has no copy until Phase 2 |
| **Silent corruption** (full disk acks an empty block, bit rot, a bad block of WAL) | A restore fails at the worst moment | Every drill restores real bytes and checks a canary; the OpenBao uploader reads back and compares sha256; `GarageOffsiteBlocksUnreadable` | Monthly restore from each vault | A block lost between drills is found at the next drill (at most 7 days) |
| **Insider with cluster admin deleting evidence** | Delete the audit trail | `vlsingle-victorialogs-audit` is backed up (T2, retain 7) | Evidence copied into the locked OVH bucket (Unfold keeps 365 days for evidence) | Audit events between the last backup and the deletion |

### What Garage can and cannot enforce

Garage v2.1 grants each key one of three permissions per bucket: `read`, `write` and `owner`.

| Garage permission | Allows | Cannot be narrowed to |
| --- | --- | --- |
| `read` | GetObject, HeadObject, ListObjects | a prefix |
| `write` | PutObject, multipart upload, **DeleteObject, DeleteObjects**, **PutBucketLifecycleConfiguration** | put-without-delete, a prefix |
| `owner` | bucket settings: website, CORS, bucket deletion and alias management through S3 | anything finer |
| (admin token only) | quotas (`set-quotas`), key and bucket creation, block repair | not reachable through any S3 key |

So on Garage:

- A "write-only" key is a key **without `read`**. It cannot list or download other backups,
  which protects confidentiality, but it **can still delete** and can replace the bucket's
  lifecycle rules. Unfold's `unfold-cluster-etcd` key is in exactly this position.
- There is no versioning and no object lock in Garage v2. The versioning and lock work (pull
  request #1479) was moved to the `next-v3` branch in June 2026; nothing here assumes it.
- Keys scope by bucket, never by prefix. Separating writers means separate buckets.
- Quotas are the one control a stolen S3 key cannot change, because only the admin token sets them.

What Phase 1 does with that, per key:

| Key | Buckets and permission | Held by | Why |
| --- | --- | --- | --- |
| `cnpg-backup` | `cnpg-backups-bucket`: read + write, **no owner** | CNPG ObjectStores, Longhorn BackupTarget, OpenBao uploader, InvoiceNinja dump | barman retention, Longhorn `retain` and the uploader's prune must delete. Removing `owner` stops bucket-level changes |
| `homelab-etcd-writer` (new) | `homelab-etcd`: write only | `backup/etcd-backup` CronJob | Cannot read old snapshots; deletion stays possible (Garage limit) |
| `backup-verify` (new) | `cnpg-backups-bucket`, `homelab-etcd`, `unfold-cluster-etcd`: read only | the OpenBao and etcd drills | A drill can never delete what it checks |
| `forgejo`, `security` | being retired (VIK-1691, VIK-1405) | n/a | Delete with their buckets |

The immutable copy therefore has to live elsewhere: at a provider with compliance object lock or
with snapshots that only another account's API can delete. That is Phase 2.

## Key escrow (T0)

| Key | Unlocks | Copy 1 | Copy 2 | Check |
| --- | --- | --- | --- | --- |
| OpenBao unseal key | every OpenBao snapshot and volume backup | password manager | sealed paper in a different building | the OpenBao drill compares the live key's sha256 with the fingerprint in git every week; quarterly the owner unseals a restored snapshot with the escrowed copy |
| SOPS age key | `talsecret`, `cluster-secrets`, the in-cluster age Secret | password manager | sealed paper | quarterly: `sops -d talos/talsecret.sops.yaml >/dev/null` with the escrowed key on a clean shell |
| homelab etcd age identity | homelab etcd snapshots | password manager | sealed paper | quarterly: decrypt and `etcdutl snapshot status` the newest snapshot |
| Unfold state passphrase, Unfold etcd identity | Unfold state and etcd | password manager | sealed paper (+ homelab OpenBao) | Unfold's daily check uses the OpenBao copy; quarterly by hand with the escrowed copy |
| Restic/kopia repository passwords (Phase 2) | the vault repositories | password manager | sealed paper | monthly vault restore uses the escrowed password |
| Owner SSH key, Hetzner and OVH 2FA recovery codes | garage-fsn1, both accounts | password manager | sealed paper | yearly |

Rules:

- A T0 key never exists only inside a system it unlocks. The OpenBao unseal key in OpenBao, the
  age key only in the cluster, or the vault passwords only in OpenBao would each be a loop.
- The fingerprint is `sha256` of the key bytes, computed by the owner from the escrowed copy
  (`printf '%s' "$KEY" | sha256sum`) and committed to git. A hash of a 256-bit random key reveals
  nothing useful. The drill alerts if the live key stops matching it, which is the signal that a
  re-key happened without a new escrow.
- The quarterly escrow drill is the only proof that the escrowed copy works. The
  [restore drills runbook](../runbooks/backup-restore-drills.md#quarterly-escrow-drill) has the
  commands. It runs on the workstation, with the escrowed copy, never with the in-cluster one.

## Capacity: quotas and forecast

### The disk today

| Item | GB |
| --- | --- |
| garage-fsn1 root filesystem | 484.8 |
| free (2026-10-25) | 44.0 |
| Immich (`/srv/immich`) | about 70 |
| Docker (`/var/lib/docker`, Immich + uptime-kuma images and volumes) | about 19 |
| OS, journal (capped at 500 MB), Caddy | about 10 |
| Garage data + LMDB metadata (all buckets) | about 340 |
| of which Longhorn backups (sum of `dataStored`) | 293 |

### What Phase 1 frees

| Change | Effect (estimate) |
| --- | --- |
| vmsingle (56.0 GB), vlsingle (23.6 GB), vtsingle (11.9 GB) move to T3 and their BackupVolumes are deleted by the owner | −91.5 GB |
| data-garage-0 (109.6 GB stored, 96 GB live) and meta-garage-0 (7.3 GB) go from retain 7 to retain 2 | −10 to −20 GB; the base dominates, so most of it stays |
| gitea-mirror (0.4 GB) retain 7 to 2 | negligible |
| vlsingle-victorialogs-audit enrolled (8.1 GB live) | +8 to +12 GB |
| homelab etcd, every 6 h, 30 days (about 150 MB per snapshot) | +up to 20 GB, capped by its quota at 5 GB with a 7-day lifecycle (below) |

Net: about −95 GB, which takes free space from 44 GB to about 140 GB (29%).

The old backups do not go away by themselves. Longhorn prunes a recurring job's backups only
when that job runs on the volume. A volume that leaves the `gitops-backup` group keeps its last
seven `gitops-backup` backups forever. The owner removes them with the
[Longhorn hand-over](#4-longhorn-hand-over) once the new group has run twice.

### Quotas (proposed)

Sum of quotas and fixed allocations stays under 80% of the disk (388 GB):

| Bucket or filesystem | Quota | Today | Notes |
| --- | --- | --- | --- |
| `cnpg-backups-bucket` | 242 GiB (260 GB) after the cleanup lands; before that, current size + 20 GB | about 340 GB | Measure with `garage bucket info` first. A quota below current size refuses every write, which stops WAL archiving |
| `homelab-etcd` | 5 GiB | new | 7-day lifecycle expiry; talos-backup does not prune |
| `unfold-cluster-etcd` | 5 GiB | a few MB | 30-day lifecycle (already set) |
| `unfold-cluster-tfstate` | 1 GiB | a few MB | |
| `forgejo` (rollback copy) | delete | | VIK-1691: delete 30 days after the ADR-0065 cutover |
| Immich (`/srv/immich`) | 85 GB ext4 image | about 70 GB | Own filesystem, owner decision; 15 GB of headroom, so Immich needs a home of its own within months |
| uptime-kuma data | 2 GB ext4 image | small | |
| Docker images, OS | not capped | about 29 GB | |
| **Total** | **about 384 GB (79%)** | | |

A Garage quota refuses writes once reached; deletes still work (Garage checks quotas on
PutObject and CompleteMultipartUpload only). When a quota is hit, CNPG keeps unarchived WAL
locally and `CNPGWALArchivingFailed` fires: the same failure as a full disk, minus the silent
corruption.

### Forecast and alerts

- `GarageOffsiteDiskFullIn14Days`: `predict_linear(garage_local_disk_avail[7d], 14 × 86400) < 0`
  for 1 h. Fourteen days is long enough to order capacity or change retention; the existing
  `GarageOffsiteDiskFillingUp` (4 days) stays as the late warning.
- Per-bucket size is not in Garage's metrics (only `table_size` and `block_rc_size`). Phase 3 adds
  a small exporter on the host or the admin API v2 `GetBucketInfo` scraped through Caddy, and then
  `predict_linear` per bucket against its quota.

### Making quotas declarative

Today buckets, keys, quotas, lifecycle rules and Caddy on garage-fsn1 are hand state. Options:

| Option | How | Verdict |
| --- | --- | --- |
| **A. Desired-state file + idempotent apply script, run from the workstation over SSH** | `garage-fsn1/state.yaml` (buckets, quotas, key permissions, lifecycle) in this repo; `just garage-fsn1-plan` prints the diff from `garage bucket info` / `garage key info`; `just garage-fsn1-apply` runs the CLI commands for the differences | **Recommended for Phase 1b.** No new component, the admin token never leaves the host, the plan step makes drift visible, and the commands it runs are the ones in this RFC |
| B. OpenTofu module against the Garage admin API v2, applied from the workstation | A community provider plus the admin token on the workstation | Later. The providers for the v2 admin API are young and third-party, and the token would have to travel over the network |
| C. Reconcile from the cluster | tofu-controller or a CronJob with the admin token in OpenBao | **Rejected.** The cluster would then hold the one credential that can lift its own quotas and delete every key: the exact power the threat model takes away |

Option A gets a ticket. Until it lands, the commands below are the source of truth and the owner
records each run in the [garage-offsite runbook](../runbooks/garage-offsite.md#quotas).

## Restore verification

### The metric contract

All drills report the same way, so one dashboard and one alert set cover every dataset. The
recording rules live in
`kubernetes/apps/observability/victoria-metrics/app/rules/prometheusrule-platform-backups.yaml`.

| Series | Meaning | Source |
| --- | --- | --- |
| `backup:dataset_copies{dataset, kind, tier, drill, targets}` | The inventory: one row per dataset, value = number of independent off-site copies | static recording rules, one per dataset |
| `backup:last_success_timestamp_seconds{dataset, kind}` | Last completed backup | CNPG barman metrics, `longhorn_volume_last_backup_at`, the snapshot CronJobs |
| `backup:restore_last_success_timestamp_seconds{dataset, kind}` | Last verified restore | creation time of the `restore-verified-<kind>-<name>` ConfigMap that a drill re-creates only on success, read through kube-state-metrics |

`dataset` is `<namespace>/<name>`; `kind` is `cnpg`, `longhorn`, `openbao`, `etcd` or `escrow`;
`tier` is `T0`–`T3`. A ConfigMap is used because kube-state-metrics already exports
`kube_configmap_created`, so a drill needs no network path to the metrics backend and no push
gateway. Unfold uses the same series names, so both clusters land in one dashboard.

### The drills

| Drill | Canary | Stale fails when | Corrupt fails when | Schedule |
| --- | --- | --- | --- | --- |
| CNPG (`components/cnpg-restore-test`) | writes a nonce row into `backup_canary` in the source's `postgres` database, switches WAL, waits for that segment to be archived | the newest base backup is older than 36 h, or the canary's WAL segment is not archived in time | the restored cluster does not start, `SELECT 1`, the expected database or role is missing, or the canary nonce is missing or different | weekly per database, daytime UTC |
| Longhorn (`apps/backup/restore-drills`) | the newest file on the restored filesystem must be within N hours of the backup time (no write into production) | the newest completed Backup is older than 36 h, or the restored data is older than allowed | the restore errors, the filesystem does not mount, or a required path is missing | weekly per dataset |
| OpenBao (`security`, openbao bootstrap) | the nightly snapshot job writes a nonce to `secret/backup-canary/openbao` just before the snapshot | the newest snapshot is older than 30 h, or the canary inside it is older than the snapshot window | the snapshot does not restore, the live unseal key does not unseal it, a root token cannot be generated in the scratch copy, or the nonce does not match | weekly |
| OpenBao unseal-key escrow | the owner's sha256 fingerprint in git | n/a | the live key's sha256 differs from the fingerprint (or no fingerprint is set) | weekly, with the OpenBao drill |
| homelab etcd (`apps/backup/etcd`) | each run writes a `canary-<epoch>-<nonce>-end` token into ConfigMap `backup/etcd-backup-canary`; the next run requires it in the restored snapshot | the newest snapshot is older than 7 h, or the restored canary is older than 30 h | the snapshot does not decrypt with the drill identity, `etcdutl` cannot restore it, etcd does not start on it, or a core namespace is missing | daily (drill identity); quarterly with the escrowed identity by hand |

The OpenBao drill uses the real recovery path: the production root token is revoked by design, so
recovering a restored OpenBao means generating a new root token with the unseal key. The drill
does that inside a scratch server in its own pod and throws the copy away.

Hibernated databases (n8n, sparkyfitness, backstage) keep their drills suspended: there is no
running primary to write a canary into, and their data has not changed since their last base
backup. Waking one means un-suspending its drill in the same commit.

Each drill ships a mutation test in `scripts/` that runs the drill's check against a good fixture
(must pass), a corrupted one (must fail) and a stale one (must fail). The
[restore drills runbook](../runbooks/backup-restore-drills.md) lists them.

## Alerts

| Alert | Fires when | Severity |
| --- | --- | --- |
| `BackupRestoreVerificationStale` | a weekly-drilled dataset has no verified restore for 8 days (daily: 2 days) | warning |
| `BackupRestoreNeverVerified` | a drilled dataset has never had a verified restore, for 8 days | warning |
| `BackupDatasetNeverBackedUp` | an inventory dataset has no completed backup for 36 h | critical |
| `HomelabEtcdBackupStale` | the newest homelab etcd snapshot is older than 14 h | warning |
| `GarageOffsiteDiskFullIn14Days` | the 7-day trend fills garage-fsn1 within 14 days | warning |
| `LonghornVolumeBackupStale` (extended) | an attached enrolled volume's last backup is older than 36 h, **or** an inventory volume reports it was never backed up | warning |
| `CNPGRestoreTestStale`, `CNPGRestoreTestFailed` (fixed) | as before, now matched on `exported_namespace` | warning |
| `CNPGOperatorDown` (fixed) | no ready `cloudnative-pg` operator pod; it had the same KSM label trap and could never fire | critical |
| existing: `CNPGNoRecentBackup`, `CNPGBackupFailed`, `CNPGWALArchivingFailed`, `LonghornBackupFailed`, `OpenBaoSnapshotStale`, `GarageOffsite*` | unchanged | |
| Phase 2: `BackupVaultCopyStale`, `BackupVaultObjectCountDrop` | the newest object in a vault is older than 26 h; a vault's object count drops by more than 10% day over day (a delete or ransomware tell) | critical |

The [Backups dashboard](../runbooks/backup-restore-drills.md#reading-the-results) shows one row per
dataset: tier, last backup, last verified restore, copies.

## Costs

Prices are per month, excluding VAT, checked 2026-10-25.

| Item | Phase 1 | Phase 2 now (about 300 GB) | Phase 2 at 1 TB |
| --- | --- | --- | --- |
| garage-fsn1 (existing dedicated server) | unchanged | unchanged | unchanged |
| Hetzner Storage Box BX11, 1 TB, separate account | € 0,00 | € 3,20 | € 10,90 (BX21, 5 TB) |
| OVHcloud Object Storage Standard 1-AZ, € 7,10 per TB, lock overhead about ×1.5 | € 0,00 | € 2,10 to € 3,20 | € 10,65 |
| Requests and egress (OVH: free; Hetzner Storage Box: free) | € 0,00 | € 0,00 | € 0,00 |
| **Total added** | **€ 0,00** | **about € 5,30 to € 6,40** | **about € 21,55** |

The lock overhead is the price of the 30-day window: barman and Longhorn delete old objects every
night, and under a compliance lock those deletes become delete markers that keep the old
versions billable for 30 days plus the 7-day lifecycle tail.

## Rollout

### Phase 1: free, built 2026-10-25

In git (this repository):

1. `CNPGRestoreTestStale` and `CNPGRestoreTestFailed` match on `exported_namespace`, with vmalert
   unit tests.
2. `LonghornVolumeBackupStale` also covers never-backed-up inventory volumes.
3. The hand-labelled volumes are in the Kyverno enrolment policy: forgejo-data in `gitops-backup`;
   gitea-mirror, data-garage-0 and meta-garage-0 in `gitops-backup-bulk` (their hand label is
   removed); vlsingle-victorialogs-audit enrolled; vmsingle, vlsingle and vtsingle unenrolled (T3).
   `gitops-backup-bulk` runs daily again.
4. CNPG canary drills on for nine active databases (four newly wired: authentik, litellm, grafana,
   dependency-track); Longhorn and OpenBao drills added; all emit the restore metric.
5. Homelab etcd snapshots every 6 h, age-encrypted, to bucket `homelab-etcd`; daily freshness drill.
6. The inventory, alert set and Backups dashboard.

Owner hand-over, in this order. **Nothing on garage-fsn1 runs until the compaction has finished
and `garage status` is healthy.**

#### 1. Escrow (in progress)

Finish the escrow the owner started: OpenBao unseal key, age key, Unfold passwords into the
password manager and on sealed paper. Then set the fingerprint the OpenBao drill checks. Compute
it from the escrowed copy, not from the cluster:

```sh
read -rs UNSEAL_KEY && printf '%s' "$UNSEAL_KEY" | sha256sum | cut -d' ' -f1; unset UNSEAL_KEY
```

Put the printed hash into the fingerprint ConfigMap the drill reads (path in the
[runbook](../runbooks/backup-restore-drills.md#openbao-snapshot-drill)) and commit it.

#### 2. homelab etcd: age recipient, bucket and keys

On the workstation, create two identities. The escrow identity is the one recovery uses; its
private half never touches the cluster. The drill identity lets the daily in-cluster drill decrypt
and restore every snapshot; it lives in OpenBao like every other homelab secret, so it adds nothing
an attacker holding OpenBao would not already have (the cluster's own state):

```sh
age-keygen -o homelab-etcd-escrow.age.key
age-keygen -o homelab-etcd-drill.age.key
ESCROW="$(age-keygen -y homelab-etcd-escrow.age.key)"
DRILL="$(age-keygen -y homelab-etcd-drill.age.key)"
bao kv put secret/backup/homelab-etcd \
  AGE_X25519_PUBLIC_KEY="${ESCROW},${DRILL}" \
  AGE_DRILL_IDENTITY=@homelab-etcd-drill.age.key
shred -u homelab-etcd-drill.age.key
```

Store `homelab-etcd-escrow.age.key` in the password manager and on paper, then `shred -u` it.

On garage-fsn1, after the compaction. These commands run from the workstation so the secret goes
straight into OpenBao without being typed or shown:

```sh
ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a; garage bucket create homelab-etcd'

out="$(ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a; garage key create homelab-etcd-writer')"
KEY_ID="$(printf '%s\n' "$out" | awk '/Key ID/ {print $3}')"
printf '%s\n' "$out" | awk '/Secret key/ {print $3}' | bao kv put secret/s3/homelab-etcd-writer \
  S3_ACCESS_KEY_ID="$KEY_ID" S3_SECRET_ACCESS_KEY=- S3_REGION=garage \
  S3_ENDPOINT=https://s3-offsite.webgrip.dev S3_BUCKET=homelab-etcd
unset out KEY_ID
ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a; garage bucket allow --write homelab-etcd --key homelab-etcd-writer'

out="$(ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a; garage key create backup-verify')"
KEY_ID="$(printf '%s\n' "$out" | awk '/Key ID/ {print $3}')"
printf '%s\n' "$out" | awk '/Secret key/ {print $3}' | bao kv put secret/s3/backup-verify-offsite \
  S3_ACCESS_KEY_ID="$KEY_ID" S3_SECRET_ACCESS_KEY=- S3_REGION=garage \
  S3_ENDPOINT=https://s3-offsite.webgrip.dev S3_BUCKET=cnpg-backups-bucket
unset out KEY_ID
for b in cnpg-backups-bucket homelab-etcd unfold-cluster-etcd; do
  ssh root@116.202.53.185 "set -a; . /etc/garage/env; set +a; garage bucket allow --read $b --key backup-verify"
done
```

Every command spells out its own SSH call so each one can be run alone. `bao kv put KEY=-` reads that one value from stdin, so the secret never
appears on a command line.

Lifecycle for `homelab-etcd` (keep 7 days; talos-backup never deletes). Run with the bucket's
own writer key or any key with write on it, from the workstation:

```sh
cat > /tmp/homelab-etcd-lifecycle.json <<'EOF'
{"Rules":[{"ID":"expire-7d","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":7},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}
EOF
AWS_ACCESS_KEY_ID="$(bao kv get -field=S3_ACCESS_KEY_ID secret/s3/homelab-etcd-writer)" \
AWS_SECRET_ACCESS_KEY="$(bao kv get -field=S3_SECRET_ACCESS_KEY secret/s3/homelab-etcd-writer)" \
aws --region garage --endpoint-url https://s3-offsite.webgrip.dev \
  s3api put-bucket-lifecycle-configuration --bucket homelab-etcd \
  --lifecycle-configuration file:///tmp/homelab-etcd-lifecycle.json
rm /tmp/homelab-etcd-lifecycle.json
```

Then apply the Talos patch that lets the `backup` namespace take etcd snapshots
(`talos/patches/controller/kubernetes-talos-api-access.yaml`), one control plane at a time:

```sh
just talos-generate-config
just talos-apply-node soyo-1
just talos-apply-node soyo-2
just talos-apply-node soyo-3
```

#### 3. Take `owner` away from `cnpg-backup`

```sh
ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a; garage key info cnpg-backup'
```

If the bucket line for `cnpg-backups-bucket` shows `O` (owner) next to `R W`:

```sh
ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a; garage bucket deny --owner cnpg-backups-bucket --key cnpg-backup'
```

#### 4. Longhorn hand-over

Wait until `gitops-backup-bulk` has completed twice for data-garage-0, meta-garage-0 and
gitea-mirror (two nights after the policy change lands). Then list, read-only, what will go:

```sh
for v in pvc-3b5bfd70-a65e-4405-a6f6-949f60b97ac9 pvc-ec70a81e-ee19-487c-8f19-b3a19dd68f6f pvc-c4030da3-f0bf-44d6-97d8-09c9e2cb15ef; do
  mise exec -- kubectl -n longhorn-system get backups.longhorn.io -l backup-volume="$v" -o json \
    | jq -r '.items[] | select(.status.labels.RecurringJob == "gitops-backup") | [.metadata.name, .status.volumeName, .status.backupCreatedAt, .status.state] | @tsv'
done
mise exec -- kubectl -n longhorn-system get backupvolumes.longhorn.io \
  pvc-6d204c8b-8560-46ad-87e8-dc28b820fe4d-a8c98d0d \
  pvc-615812d4-52b3-4ee7-95f1-4f1a8ab2aee9-e03a62aa \
  pvc-98a4e2ac-4df4-448b-a752-9db7b77c4128-d85c1976 \
  -o custom-columns=NAME:.metadata.name,VOLUME:.spec.volumeName,STORED:.status.dataStored
```

The first loop prints the old `gitops-backup` backups of the three bulk volumes; the second the
BackupVolumes of vmsingle, vlsingle and vtsingle. Deleting a Backup or BackupVolume CR deletes its
data on garage-fsn1, and that cannot be undone. When the listing is what you expect:

```sh
for v in pvc-3b5bfd70-a65e-4405-a6f6-949f60b97ac9 pvc-ec70a81e-ee19-487c-8f19-b3a19dd68f6f pvc-c4030da3-f0bf-44d6-97d8-09c9e2cb15ef; do
  mise exec -- kubectl -n longhorn-system get backups.longhorn.io -l backup-volume="$v" -o json \
    | jq -r '.items[] | select(.status.labels.RecurringJob == "gitops-backup") | .metadata.name' \
    | xargs -r mise exec -- kubectl -n longhorn-system delete backups.longhorn.io
done
mise exec -- kubectl -n longhorn-system delete backupvolumes.longhorn.io \
  pvc-6d204c8b-8560-46ad-87e8-dc28b820fe4d-a8c98d0d \
  pvc-615812d4-52b3-4ee7-95f1-4f1a8ab2aee9-e03a62aa \
  pvc-98a4e2ac-4df4-448b-a752-9db7b77c4128-d85c1976
```

Run these between 09:00 and 17:00 UTC: a backup deletion holds the volume's deletion lock for an
hour or more (see [garage-offsite](../runbooks/garage-offsite.md#why-the-ttl-is-12-hours-not-24)).
Garage frees the space after the 24-hour tombstone GC; LMDB pages are reused without compaction.

#### 5. Quotas

Measure first. A quota below the current size stops all writes to that bucket:

```sh
ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a; for b in $(garage bucket list | awk "NR>1 {print \$NF}"); do echo "== $b"; garage bucket info "$b" | grep -E "Size|Objects"; done'
```

Before the Longhorn hand-over has freed space, cap `cnpg-backups-bucket` at its current size plus
20 GB (replace `<CURRENT_GB>`):

```sh
ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a; garage bucket set-quotas cnpg-backups-bucket --max-size <CURRENT_GB+20>GB'
```

After the hand-over, set the target quotas:

```sh
ssh root@116.202.53.185 'set -a; . /etc/garage/env; set +a;
garage bucket set-quotas cnpg-backups-bucket --max-size 242GiB
garage bucket set-quotas homelab-etcd --max-size 5GiB
garage bucket set-quotas unfold-cluster-etcd --max-size 5GiB
garage bucket set-quotas unfold-cluster-tfstate --max-size 1GiB
garage bucket list'
```

Undo for any bucket: `garage bucket set-quotas <bucket> --max-size none`.

Turn on metadata snapshots, the only way back from a corrupt `data.mdb` on a single node. In
`/etc/garage/garage.toml`, add `metadata_auto_snapshot_interval = "6h"`, then
`systemctl restart garage`.

#### 6. Capped filesystems for Immich and uptime-kuma

Only after step 4 has freed space: the image files reserve their full size at creation. Immich and
uptime-kuma are down while their data moves (minutes for 70 GB on local NVMe).

```sh
ssh root@116.202.53.185
docker ps --format '{{.Names}}'
docker inspect --format '{{range .Mounts}}{{.Source}} {{end}}' "$(docker ps --format '{{.Names}}' | grep -i uptime)"
```

Set `UPTIME_KUMA_DIR` to the data directory that printed, then:

```sh
set -eu
UPTIME_KUMA_DIR=<path printed above>
cd /srv && docker compose -f /srv/immich/docker-compose.yml down
docker stop "$(docker ps --format '{{.Names}}' | grep -i uptime)"

fallocate -l 85G /srv/immich.img && mkfs.ext4 -q -m 0 /srv/immich.img
fallocate -l 2G /srv/uptime-kuma.img && mkfs.ext4 -q -m 0 /srv/uptime-kuma.img

mv /srv/immich /srv/immich.old && mkdir /srv/immich
mount -o loop /srv/immich.img /srv/immich
cp -a /srv/immich.old/. /srv/immich/
mv "$UPTIME_KUMA_DIR" "$UPTIME_KUMA_DIR.old" && mkdir "$UPTIME_KUMA_DIR"
mount -o loop /srv/uptime-kuma.img "$UPTIME_KUMA_DIR"
cp -a "$UPTIME_KUMA_DIR.old/." "$UPTIME_KUMA_DIR/"

printf '/srv/immich.img /srv/immich ext4 loop,nofail 0 2\n/srv/uptime-kuma.img %s ext4 loop,nofail 0 2\n' "$UPTIME_KUMA_DIR" >> /etc/fstab
mount -a
docker compose -f /srv/immich/docker-compose.yml up -d
docker start "$(docker ps -a --format '{{.Names}}' | grep -i uptime)"
```

Check Immich and uptime-kuma in the browser, then `rm -rf /srv/immich.old "$UPTIME_KUMA_DIR.old"`.
If Immich's compose file lives elsewhere, use that path; the point is that its data directory
becomes a mount of its own fixed size. Rollback: stop the app, `umount`, move the `.old`
directory back, remove the fstab lines.

### Phase 2: the vault copies (paid, about € 5,50 per month, owner buys)

#### Hetzner Storage Box in a separate account

1. Create a new Hetzner account with a different e-mail address and a hardware security key as
   second factor. It holds nothing but the vault. Record its recovery codes in T0 escrow.
2. In that account, order a **Storage Box BX11** (1 TB, € 3,20 per month) in **Helsinki (HEL1)**,
   so it shares neither the account nor the site with garage-fsn1. Check the location list on the
   order page; if HEL1 is not offered, any location other than FSN1.
3. Enable SSH support. Create a sub-account `homelab-restic` with its own directory and SSH
   access only (no Samba, no WebDAV). The sub-account can write and delete files in its directory
   but cannot create, delete or roll back snapshots.
4. Snapshot plan (Console, Storage Box > Snapshots > Automatic snapshots): weekly, Sunday 06:00
   UTC, keep 10. BX11 has 10 snapshot slots, so this gives 10 weeks of history at weekly
   granularity; the 30-day daily window comes from OVH. Snapshot space counts against the 1 TB.
5. Declare it: an OpenTofu stack `vault/` in this repo with the `hcloud` provider's Storage Box,
   sub-account and snapshot-plan resources, applied from the workstation with that account's API
   token. The token goes into the password manager, never into OpenBao or CI.
6. The cluster gets only the sub-account's SSH key and the restic repository password
   (OpenBao `secret/backup/storage-box`, both provided by the owner). A nightly restic job copies
   the landing buckets (read with `backup-verify`) and, from garage-fsn1 itself, `/srv/immich`.

#### OVHcloud Object Storage with compliance lock

1. Create an OVHcloud account (or reuse Unfold's, with its own Public Cloud project) and a project
   `webgrip-backup-vault`. Two-factor with a hardware key; recovery codes into T0 escrow.
2. Create the bucket with Object Lock, in Gravelines, Standard 1-AZ, using the project's admin S3
   credentials on the workstation:

    ```sh
    E=https://s3.gra.io.cloud.ovh.net
    aws --endpoint-url $E --region gra s3api create-bucket --bucket webgrip-homelab-vault --object-lock-enabled-for-bucket
    aws --endpoint-url $E --region gra s3api put-object-lock-configuration --bucket webgrip-homelab-vault \
      --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":30}}}'
    aws --endpoint-url $E --region gra s3api put-bucket-lifecycle-configuration --bucket webgrip-homelab-vault \
      --lifecycle-configuration '{"Rules":[{"ID":"noncurrent-37d","Status":"Enabled","Filter":{"Prefix":""},"NoncurrentVersionExpiration":{"NoncurrentDays":37},"Expiration":{"ExpiredObjectDeleteMarker":true}}]}'
    aws --endpoint-url $E --region gra s3api get-object-lock-configuration --bucket webgrip-homelab-vault
    ```

3. Create an S3 user `homelab-vault-writer` with a policy that allows only `s3:PutObject`,
   `s3:GetObject`, `s3:ListBucket`, `s3:GetBucketLocation` and `s3:AbortMultipartUpload` on
   `webgrip-homelab-vault`. No `s3:DeleteObjectVersion`, no `s3:PutBucketObjectLockConfiguration`,
   no lifecycle or policy actions. Put its credentials into OpenBao:

    ```sh
    printf '%s' "$OVH_SECRET" | bao kv put secret/s3/ovh-homelab-vault \
      S3_ACCESS_KEY_ID="$OVH_ACCESS" S3_SECRET_ACCESS_KEY=- S3_REGION=gra \
      S3_ENDPOINT=https://s3.gra.io.cloud.ovh.net S3_BUCKET=webgrip-homelab-vault
    unset OVH_SECRET OVH_ACCESS
    ```

4. Unfold uses the same project with its own bucket and user (`webgrip-unfold-vault`,
   `unfold-vault-writer`); neither cluster can read or write the other's bucket.
5. In-cluster (a Phase 2 commit): an rclone `crypt` copy of `cnpg-backups-bucket` prefixes and
   `homelab-etcd` nightly, with `--s3-object-lock-mode COMPLIANCE
   --s3-object-lock-retain-until-date 30d` set per object (do not trust the bucket default
   alone), and kopia with `--retention-mode COMPLIANCE --retention-period 30d` and
   `maintenance set --extend-object-locks true` for volume data. The rclone crypt password and
   the kopia repository password are T0 keys.
6. Drills: a monthly restore from each vault (`target` label `storage-box` and `ovh`) feeds
   `backup:restore_last_success_timestamp_seconds`; `backup:dataset_copies` rises to 3 for T1.

### Phase 3: hardening (free, later)

- Longhorn drills rotate over every T1 and T2 volume, one volume per day.
- CNPG drills read through a read-only ObjectStore per database (the `backup-verify` key), so a
  drill can never touch the archive it checks.
- `cnpg-backups-bucket` splits into one bucket per writer (CNPG, Longhorn, OpenBao), each with its
  own key, so one stolen key reaches one kind of backup. This starts new backup chains, so it
  happens at a base-backup boundary, one writer at a time.
- Harbor's proxy cache moves to a bucket on a volume that is not backed up (T3).
- Per-bucket size exporter and `predict_linear` per quota.
- Unfold moves etcd and state off garage-fsn1 to its RFC 0001 targets (its delivery step 3).
- A Forgejo push-mirror lag alert and the Headscale state backup (audit gaps 4 and 9).

## Decisions

| Record | Decision |
| --- | --- |
| [ADR-0081](../adr/adr-0081-backups-land-on-a-capped-garage-are-proven-by-canary-drills-and-lock-elsewhere.md) | Backups land on a capped garage-fsn1, are proven by canary restore drills, and their immutable copy lives at providers the cluster cannot delete from |

Owner decisions taken as defaults on 2026-10-25, to confirm:

1. garage-fsn1 stays as the landing tier.
2. Immich and uptime-kuma get their own capped filesystems on it.
3. The Storage Box vault lives in a separate Hetzner account.
4. The lock window is 30 days.
5. Audit logs are T2; other logs are T3. Metrics and traces are T3 as well (the research's
   default; backing them up cost 91.5 GB on a host with 44 GB free).

## Out of scope

- The Git ring (ADR-0011, ADR-0012) beyond the yearly cold-bootstrap drill.
- The workstation's own backup (Timeshift schedules off, no restic). The T0 keys are covered by
  escrow; the rest of the workstation is a separate ticket.
- Buying hardware (a home ZFS box was weighed in the research and loses on the threat model: the
  owner is admin on both self-hosted copies).

## Evidence

- Audit and research of 2026-10-25 (session scratch, summarised above); live reads through
  `kubectl` and VictoriaMetrics: `garage_local_disk_avail{job="garage-offsite"}` 43.7 GB,
  `kube_cronjob_spec_suspend{cronjob="cnpg-restore-test"}` on `namespace="observability"`,
  `longhorn_volume_last_backup_at` 0 for `vlsingle-victorialogs-audit`, BackupVolume `dataStored`.
- [garage-offsite runbook](../runbooks/garage-offsite.md), [cnpg-backups runbook](../runbooks/cnpg-backups.md),
  [openbao-restore runbook](../runbooks/openbao-restore.md), [secrets level 0](../runbooks/secrets-level-0-floor.md).

## History

- 2026-07-02: Proposed as a program sketch (tier map, unseal-key escrow, second leg, coverage list,
  drill cadence). It named the holes; nothing was built.
- 2026-10-25: Rewritten after the backup audit. Phase 1 accepted and built; Phase 2 and 3 proposed.
  Replaces the five candidate ADRs of the 2026-07-02 version with ADR-0081.
