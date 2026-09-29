# Off-site Garage (garage-fsn1)

The off-site Garage behind `https://s3-offsite.webgrip.dev` holds every backup the cluster makes:
CNPG WAL and base backups, Longhorn volume backups, OpenBao raft snapshots, Forgejo LFS,
attachments and Actions logs, and the invoiceninja dumps. When its disk fills, all of those fail
at once. This runbook covers the host, the checks, the capacity alerts, emptying and deleting a
bucket, reclaiming disk after a mass deletion, and data blocks lost to a full disk.

Outage triage for "Garage unreachable" lives in the
[blackbox runbook](synthetic-probes-blackbox.md#garage-s3-cnpg-backup-wal-target-unavailable).
The 2026-09-28 disk-full incident is VIK-1405; its cause, GUAC's blob store, is removed by
[ADR-0064](../adr/adr-0064-dependency-track-only-sbom-platform.md).

## Host facts

| Item | Value |
| --- | --- |
| Host | `garage-fsn1`, Hetzner dedicated, Falkenstein. `116.202.53.185` |
| Hardware | i7-6700 (4C/8T), 62 GB RAM, 2 × 512 GB Samsung NVMe in RAID1 (`/dev/md2`, 452 GB, mounted on `/`), Debian 12 |
| Garage | v2.1.0, systemd unit `garage.service`, runs as user `garage` |
| Garage config | `/etc/garage/garage.toml`, secrets in `/etc/garage/env` (`GARAGE_CONFIG_FILE`, `GARAGE_RPC_SECRET`, `GARAGE_ADMIN_TOKEN`) |
| Metadata | `db_engine = "lmdb"`, `/var/lib/garage/meta/db.lmdb/data.mdb`, same filesystem as data |
| Data | `/var/lib/garage/data` |
| Listeners | S3 `127.0.0.1:3900`, RPC `127.0.0.1:3901`, admin and `/metrics` `127.0.0.1:3903`. Nothing Garage-related listens publicly |
| Front door | Caddy v2.11 terminates TLS for `s3-offsite.webgrip.dev` and proxies to `127.0.0.1:3900`. The same Caddy serves `immich.webgrip.dev` and `uptime.webgrip.dev` (Docker, about 19 GB under `/var/lib/docker`, Immich data under `/srv/immich`) |
| Buckets | `cnpg-backups-bucket` (key `cnpg-backup`), `forgejo` (key `forgejo`), `guac` (key `security`, being deleted) |
| Replication | `replication_factor = 1`. The RAID1 pair is the only redundancy; a lost block is lost |

## Access and checks

```sh
ssh root@116.202.53.185
set -a; . /etc/garage/env; set +a      # loads the CLI's RPC secret into this shell only; prints nothing
garage status
garage bucket list
garage bucket info cnpg-backups-bucket
garage worker list
garage block list-errors
df -h /; du -sh /var/lib/garage/meta /var/lib/garage/data
curl -s http://127.0.0.1:3903/metrics | grep -E '^garage_local_disk|^cluster_healthy|^table_size|^block_resync'
```

Never `cat` `/etc/garage/env` or `garage.toml` into a shared terminal or a log; both hold secrets.

## Metrics scrape

vmagent scrapes Garage's own metrics as `job="garage-offsite"`
(`victoria-metrics/app/scrapes/vmstaticscrape-garage-offsite.yaml`) at
`https://s3-offsite.webgrip.dev/_garage/metrics`. Caddy maps that path to the admin listener's
`/metrics` behind basic auth. S3 bucket names cannot start with `_`, so the path can never shadow a
bucket. The password is generated in-cluster (`observability/garage-offsite-metrics`,
generate-once); only its bcrypt hash lives on the host.

One-time setup, from a machine with cluster access, Docker and the SSH key. The bcrypt hash is computed locally with the same Caddy version as the host, so the password never leaves the machine; `caddy hash-password` on the host does not read a piped password (it fails with `Error: EOF` and yields an empty hash). The new config is validated as a separate file before it replaces the live one, so a bad hash can never leave an invalid Caddyfile behind:

```sh
HASH="$(kubectl -n observability get secret garage-offsite-metrics -o jsonpath='{.data.password}' \
  | base64 -d | docker run --rm -i caddy:2.11.4 sh -c 'caddy hash-password --algorithm bcrypt --plaintext "$(cat)"')"
ssh root@116.202.53.185 "HASH='$HASH' sh -s" <<'EOF'
set -eu
f=/etc/caddy/Caddyfile
if grep -q '_garage/metrics' "$f"; then echo "handler already present"; exit 0; fi
[ -n "$HASH" ] || { echo "empty hash, aborting"; exit 1; }
cp "$f" "$f.bak-vik62"
awk -v h="$HASH" '
  { print }
  /^s3-offsite\.webgrip\.dev \{/ {
    print "\thandle /_garage/metrics {"
    print "\t\tbasic_auth bcrypt {"
    print "\t\t\tvmagent " h
    print "\t\t}"
    print "\t\trewrite * /metrics"
    print "\t\treverse_proxy 127.0.0.1:3903"
    print "\t}"
  }' "$f" > "$f.new"
caddy validate --config "$f.new" --adapter caddyfile >/dev/null 2>&1 || { echo "new config invalid, left untouched"; rm -f "$f.new"; exit 1; }
mv "$f.new" "$f"
systemctl reload caddy
EOF
```

Applied 2026-09-29; `up{job="garage-offsite"}` is 1 and `garage_local_disk_avail` reports both volumes.

Verify: `curl -s -o /dev/null -w '%{http_code}\n' https://s3-offsite.webgrip.dev/_garage/metrics`
returns `401`, and in Grafana `up{job="garage-offsite"}` is `1` within two minutes. If the
ExternalSecret is ever regenerated, the hash no longer matches and `GarageOffsiteMetricsMissing`
fires: restore `/etc/caddy/Caddyfile.bak-vik62`, reload Caddy and run the setup again. The same
restore is the rollback.

## Disk capacity

Alerts (`victoria-metrics/app/rules/prometheusrule-platform-garage-offsite.yaml`):

| Alert | Fires when |
| --- | --- |
| `GarageOffsiteDiskLow` | the tightest Garage volume has less than 15% free for 30m |
| `GarageOffsiteDiskCritical` | less than 5% free for 10m |
| `GarageOffsiteDiskFillingUp` | the last 2 days' trend reaches zero within 4 days |
| `GarageOffsiteQueueBacklog` | a table insert queue or the resync queue holds more than 100k entries |
| `GarageOffsiteBlocksUnreadable` | any block keeps failing resync |
| `GarageOffsiteUnhealthy` | `cluster_healthy` is 0 |
| `GarageOffsiteMetricsMissing` | no successful scrape for 15m |

Metadata and data share `/`, so `garage_local_disk_avail{volume="metadata"}` and `{volume="data"}`
report the same number here.

Find the grower: compare `garage bucket info <bucket>` object counts and sizes over a day. Objects
smaller than 3 KB are stored inline in the LMDB metadata, so millions of tiny objects grow
`data.mdb`, not `/var/lib/garage/data`. That was the 2026-09-28 failure: 36.8 million GUAC
documents averaging 2.4 KB made `data.mdb` 115 GB.

## Emergency relief

Used on 2026-09-29, when `/` was at 100% and every write failed with
`LMDB: No space left on device`. Each step is reversible.

1. Stop the inflow. Cap the growing bucket at its current object count; deletes still work under
   a quota, only writes are refused (Garage checks quotas on PutObject and CompleteMultipartUpload
   only).

    ```sh
    garage bucket info <bucket> | grep Objects
    garage bucket set-quotas <bucket> --max-objects <that count>
    # undo: garage bucket set-quotas <bucket> --max-objects none
    ```

2. Cap the journal (freed about 3.9 GB):

    ```sh
    mkdir -p /etc/systemd/journald.conf.d
    printf '[Journal]\nSystemMaxUse=500M\n' > /etc/systemd/journald.conf.d/size.conf
    systemctl restart systemd-journald && journalctl --vacuum-size=500M
    ```

3. Release most of ext4's root reserve (5% to 1%, about 18 GB). Garage runs as `garage` and
   cannot use reserved blocks, so they are wasted headroom for it:

    ```sh
    tune2fs -m 1 /dev/md2
    # undo once the disk has room again: tune2fs -m 5 /dev/md2
    ```

Result on 2026-09-29: 10.4 GB free, no `No space left` after 20:09:30 local time, and WAL
archiving recovered in all 11 CNPG clusters.

## Lifecycle and deletion

Garage v2.1 supports S3 lifecycle rules with `Filter` on `Prefix` and object size, `Expiration`
in days or at a date, and `AbortIncompleteMultipartUpload`. `PutBucketLifecycleConfiguration`
needs write permission on the bucket, not owner. The lifecycle worker starts once a day at
midnight UTC (`use_local_tz` is unset) and records its last pass in
`/var/lib/garage/meta/lifecycle_worker_state`. An object written on day D with `Days: N` is
deleted by the pass on day D+N+1 at the latest.

Do not use a lifecycle rule to delete millions of objects at once on this host. The worker writes
each expiry into the object table's insert queue, which lives in the same LMDB file and has no
backpressure; the inline data is only freed when the queue worker applies the entry. With a few
GB free, a large backlog can fill the disk again. Delete in batches with `DeleteObjects` instead:
each delete applies synchronously and frees the inline data in the same transaction.

Deleted objects stay as tombstones in the object table for 24 hours, then the table GC removes
them. `garage bucket delete` only requires that no object in the bucket still has data, so it
works right after the batch delete, but the disk space is not reusable by the filesystem until
the compaction below.

### Emptying and deleting the `guac` bucket

State on 2026-09-29: 36,841,849 objects, 83.4 GiB, keys `sha256_<hash>` at the bucket root
(GUAC documents), plus `_db-backups/` (guac-db dumps) and a quota of `--max-objects 36841849`.
The purge is a one-shot in-cluster Job with the bucket's own key: list 1,000 keys, delete them
with one `DeleteObjects` call, repeat, in eight parallel workers over the sixteen `sha256_<hex>`
prefixes, then delete everything else and abort pending multipart uploads. It was tested against
a local Garage v2.1.0 and waits for the owner's go-ahead (VIK-1405). Expect a few hours for 36.8M
objects; progress is the Job log and `garage bucket info guac | grep Objects`.

When the Job logs `purge: bucket guac is empty`:

```sh
garage bucket info guac | grep -E 'Objects|Size'     # Objects: 0
garage bucket delete --yes guac
garage key info security                              # confirm it has no other bucket
garage key delete --yes security
```

Then retire the OpenBao path `secret/s3/security-offsite` (`bao kv metadata delete secret/s3/security-offsite`)
after removing the Job and its ExternalSecret from git.

## Reclaiming disk: LMDB compaction

LMDB never shrinks `data.mdb`. Deleted objects free pages inside the file, which Garage reuses,
but the filesystem sees no change. To give the space back, copy the live pages into a new file
with Garage stopped.

Run this only when all of these hold:

```sh
garage bucket list                                        # no guac
curl -s http://127.0.0.1:3903/metrics | grep -E '^table_size\{table_name="object"\}|^table_gc_todo_queue_length\{table_name="object"\}|^table_insert_queue_length\{table_name="object"\}|^table_merkle_updater_todo_queue_length\{table_name="object"\}'
```

- `table_size{table_name="object"}` is in the low hundreds of thousands (it was 36,994,802 on
  2026-09-29; about 150,000 of those are not GUAC). A value still in the millions means the
  tombstone GC has not finished; wait.
- The three queue lengths are 0 or close to it.
- It is between 09:00 and 17:00 UTC. Longhorn backups run 02:00 to about 04:00 UTC, the OpenBao
  snapshot at 03:00, CNPG base backups at night.

Procedure (downtime is the copy time, expected a few minutes on NVMe):

```sh
apt-get install -y lmdb-utils
M=/var/lib/garage/meta
mdb_stat -ef "$M/db.lmdb" | grep -E 'Page size|Number of pages used|Free pages'
df -B1 / | tail -1
# live bytes = (pages used - free pages) x page size; continue only if df's free column is at
# least twice that

systemctl stop garage
sync
mkdir "$M/db.lmdb.compact"
mdb_copy -c "$M/db.lmdb" "$M/db.lmdb.compact"
ls -la "$M/db.lmdb.compact"
mv "$M/db.lmdb" "$M/db.lmdb.old"
mv "$M/db.lmdb.compact" "$M/db.lmdb"
chown -R garage:garage "$M/db.lmdb"
chmod 600 "$M/db.lmdb/data.mdb"
systemctl start garage

garage status
garage bucket info cnpg-backups-bucket | grep -E 'Objects|Size'   # same as before the stop
df -h /
```

Clients see 502 from Caddy while Garage is stopped. CNPG retries WAL archiving on its own and
keeps unarchived WAL locally, so minutes are harmless. Verify from the cluster that
`CNPGWALArchivingFailed` stays clear and the next Longhorn backup completes. Keep
`db.lmdb.old` for a day, then `rm -rf /var/lib/garage/meta/db.lmdb.old`.

Rollback: `systemctl stop garage`, move `db.lmdb` aside, `mv db.lmdb.old db.lmdb`, start.

Afterwards, consider `metadata_auto_snapshot_interval = "6h"` in `garage.toml`: with a single node
and `metadata_fsync` off, a metadata snapshot is the only way back from a corrupted `data.mdb`.
Each snapshot is a compacted copy of the live metadata, and Garage keeps two.

## Unreadable blocks

With one node, a block that fails resync is gone. `GarageOffsiteBlocksUnreadable` fires on
`block_resync_errored_blocks > 0`. Map blocks to objects:

```sh
garage block list-errors
garage block info <hash>          # lists bucket, key and version of every reference
```

On 2026-09-29 the full disk had left 41 such blocks: 31 in `guac` (they go with the bucket) and
10 elsewhere:

| Bucket | Object | Remedy |
| --- | --- | --- |
| `cnpg-backups-bucket` | forgejo-db WAL `0000000100000079000000AB` | Take a new base backup, then purge the block |
| `cnpg-backups-bucket` | ploeg-db WAL `0000000500000001000000CD`, `000000050000000200000047`, `000000050000000200000048` | same |
| `cnpg-backups-bucket` | vikunja-db WAL `0000000400000013000000EA` to `…ED` | same |
| `cnpg-backups-bucket` | Longhorn block of `pvc-6d204c8b` (vmsingle) | Purge; the next backup uploads the block again |
| `forgejo` | `repo-archive/53/60/60c78830….bundle` | Purge; Forgejo regenerates archives on request |

A WAL segment that cannot be read breaks point-in-time recovery across it: a restore can reach the
last base backup before the gap, or a time after the next base backup, but nothing in between.
A base backup taken after the gap makes the cluster fully recoverable again. `garage block purge
--yes <hash>` deletes every object that references the block, so the gap becomes an explicit
missing file instead of a read error.

## Longhorn backups

The Longhorn `BackupTarget` reports `AVAILABLE` even when every backup fails, so the alerts look at
the backups themselves: `LonghornBackupFailed` (a Backup CR in state Error, from
`longhorn_backup_state == 4`) and `LonghornVolumeBackupStale` (an attached volume whose last
completed backup is older than 36 hours; all backup recurring jobs run daily).

```sh
kubectl -n longhorn-system get backups.longhorn.io -o custom-columns=NAME:.metadata.name,STATE:.status.state,VOLUME:.status.volumeName,ERROR:.status.error
```

Failed Backup CRs are deleted after the `failed-backup-ttl` setting (1440 minutes). To prove
recovery after a Garage problem, run a backup on demand:
`kubectl -n longhorn-system create job --from=cronjob/<backup-cronjob> <name>-manual`.
