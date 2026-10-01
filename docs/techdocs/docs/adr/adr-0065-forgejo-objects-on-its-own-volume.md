---
status: proposed
date: 2026-10-01
---

# Forgejo keeps its objects on its own volume; the off-site Garage holds only backups

Technical Story: [VIK-1691](https://vikunja.webgrip.dev/tasks/1691). Follows the off-site Garage disk-full incidents of 2026-09-28
(VIK-1405), 2026-09-30 and 2026-10-01.

## Context and Problem Statement

Forgejo stores git repositories on the `forgejo-data` Longhorn volume and everything else in
`[storage]`: packages (the npm, container and Helm registry), LFS objects, release
attachments, avatars and repository archives. Since 2026-08-01 `[storage]` points at the
off-site Garage behind `https://s3-offsite.webgrip.dev` (commit `857f147c`).

That move happened because the Proxmox host that carried the old Garage was being turned into a
Talos node, and the rule for where its buckets went was "regenerable data stays local,
irreplaceable data goes off-site" (commit `c43d3992`). The `forgejo` bucket sat next to
`cnpg-backups-bucket` on that host and moved with it. It is not a backup, though. It is the
primary and only copy of live data that CI reads and writes on every release.

The off-site host shares one 452 GB disk between Garage and Immich, with `replication_factor = 1`.
When the backups on that disk grow, Forgejo fails too:

| Date | What broke in Forgejo |
| --- | --- |
| 2026-09-28 | Off-site disk full for about 38 hours (VIK-1405). Actions lost job logs. |
| 2026-09-29 | Actions logs and artifacts moved to `forgejo-data` to stop jobs being reported as failed (commit `d9ab1bf0`). |
| 2026-09-30 | Glide rc.15–rc.17 release assets answered HTTP 500 (`unable to seek`). |
| 2026-10-01 | Off-site disk full again at about 12:35Z. `npm publish` of `@webgrip/semantic-release-config` 1.3.2 failed with `Error saving package blob in content store: 502 Bad Gateway`, and avatars failed to load. |

The bucket is small. Forgejo's database, read on 2026-10-01, records:

| Object type | Count | Size |
| --- | --- | --- |
| Package blobs | 2,504 | 4.96 GB |
| LFS objects | 150 | 0.67 GB |
| Attachments | 162 | 0.004 GB |
| Avatars, repo avatars, repo archives | — | not recorded; small |

3.94 GB of the package blobs were written in the last 30 days. Nearly all of that is the Glide
container images mirrored into Forgejo's registry on every release: `de-vloer-agent` (156
versions), `de-vloer` (353) and `ploegd` (474). Deployments pull those images from Harbor, so the
Forgejo copies are a mirror.

`forgejo-data` is a 20 Gi `longhorn-general` volume with 2 replicas and 2.7 GB used. It is in the
`gitops-backup` recurring job, which backs it up to the off-site store every night at 02:00 and
keeps 7 backups.

Where should Forgejo's objects live so that a full backup disk cannot break CI, and so that
they are not a single unbacked copy?

## Decision Drivers

* A full or unreachable backup target must not break Forgejo's packages, LFS or releases.
* Forgejo's objects need a second copy, and that copy must be off-site.
* Use what the cluster already runs and already backs up before adding a component.
* Package growth of about 4 GB a month must be bounded.
* The migration must be reversible.

## Considered Options

* Local storage on the `forgejo-data` volume
* A `forgejo` bucket on the in-cluster Garage, copied off-site every night
* The in-cluster Garage on a 2-replica volume
* Stay on the off-site Garage and alert on its capacity

## Decision Outcome

Chosen option: "Local storage on the `forgejo-data` volume", because it is the only option
that gives Forgejo's objects a second local replica and a nightly off-site copy without
building anything new. `forgejo-data` already has both, and git repositories, Actions logs
and artifacts already live there.

* `[storage]` in `kubernetes/apps/forgejo/forgejo/app/helmrelease.yaml` becomes
  `STORAGE_TYPE: local`. Forgejo then uses its default per-type paths under `APP_DATA_PATH`
  (`/data/gitea`). The `MINIO_*` keys and the `FORGEJO__storage__MINIO_*` environment variables
  are removed, and so is `forgejo-s3-secret.externalsecret.yaml`.
* `forgejo-data` grows from 20 Gi to 40 Gi before the cutover (`longhorn-general` allows
  expansion). That fits today's 2.7 GB of repositories and logs, about 6 GB of objects, and
  headroom for package growth under the cleanup rule.
* The `webgrip` organisation gets a package cleanup rule for container packages. It keeps the
  newest versions of each image and removes older ones. The exact keep count is set during
  implementation, after checking what the Glide release and promotion jobs still read from
  Forgejo's registry.
* The data moves with Forgejo's own copier while the off-site Garage is reachable, one type at
  a time: `forgejo migrate-storage --type <type> --storage local` for `packages`, `lfs`,
  `attachments`, `avatars`, `repo-avatars` and `repo-archivers`. Then the configuration flips,
  and a second copy pass picks up anything written in between.
* The `forgejo` bucket on the off-site Garage stays read-only for 30 days as the rollback copy,
  then it is deleted. After that, the off-site Garage holds only backups.

### Consequences

* Good, because a full or unreachable off-site Garage no longer breaks package publishes,
  release assets, LFS or avatars. It can only delay that night's backup.
* Good, because Forgejo's objects get the same protection as its repositories: 2 Longhorn
  replicas plus 7 nightly off-site backups. Today they have one copy.
* Good, because there is nothing new to run: no bucket, no key, no OpenBao path, no egress rule
  and no copy CronJob. One ExternalSecret goes away.
* Good, because the package cleanup rule bounds the fastest-growing data, wherever it lives.
* Bad, because `forgejo-data` triples in size, so its nightly backups and any restore take
  longer. Backups are incremental, so the nightly cost is about the day's new objects.
* Bad, because Forgejo stays limited to one pod by its RWO volume. That is already true for the
  git repositories, so nothing is lost.
* Bad, because restoring a single object now means restoring the volume, not reading one key
  from S3.

### Confirmation

* `kubectl -n forgejo exec deploy/forgejo -c forgejo -- grep -A3 '^\[storage\]' /data/gitea/conf/app.ini`
  shows `STORAGE_TYPE = local` and no `MINIO_` keys.
* `npm publish` of a test package, `docker push` to `forgejo.webgrip.dev`, an LFS push and a
  release attachment upload all succeed while the off-site Garage's S3 port is blocked.
* `kubectl -n longhorn-system get backups.longhorn.io -l backup-volume=<forgejo-data PV>` shows
  a `Completed` backup taken after the cutover.
* On the off-site host, `garage bucket info forgejo` shows no writes after the cutover date.
* The organisation's package settings list the cleanup rule, and the next day's
  `cleanup_packages` cron run logs removed versions.

## Pros and Cons of the Options

### A `forgejo` bucket on the in-cluster Garage, copied off-site every night

The in-cluster Garage (`garage-0`, namespace `garage`) already serves Harbor, TechDocs, the docs
site and the omnigraph archive, and its bootstrap Jobs create a bucket, a key and an OpenBao
PushSecret per consumer.

* Good, because Forgejo keeps S3 semantics, which a later move to more than one pod would need.
* Good, because the bucket, key and PushSecret follow an existing pattern.
* Bad, because Garage's data volume is `longhorn-single`: one replica on one node. Forgejo's
  objects would have one local copy, so the nightly copy would be the only protection between
  runs.
* Bad, because it needs a new copy CronJob with credentials and egress to both stores, which
  then has to be monitored.
* Bad, because the volume is 100 Gi with 66 GiB written, mostly Harbor, so it shares headroom
  with a pull-through cache.

### The in-cluster Garage on a 2-replica volume

* Good, because it fixes the single-replica weakness of the option above.
* Bad, because the Garage data volume cannot change storage class in place. Moving it means
  migrating Harbor's blobs as well, which takes the cluster's image mirror down.
* Bad, because it doubles Harbor's cache footprint to protect about 6 GB of Forgejo data.

### Stay on the off-site Garage and alert on its capacity

* Good, because nothing moves.
* Bad, because CI still depends on a single remote host for its working data, the inversion
  that commit `c43d3992` rejected for Harbor.
* Bad, because the objects stay a single copy with no backup.
* Bad, because alerts only shorten an outage like the ones in the table above; they do not
  prevent it.

## More Information

* 2026-08-01 — Forgejo's `[storage]` repointed to the off-site Garage with the other Proxmox
  buckets (`857f147c`).
* 2026-09-29 — Actions logs and artifacts moved to `forgejo-data` after the first disk-full
  incident (`d9ab1bf0`).
* 2026-10-01 — Proposed after the off-site disk filled for the third time and failed an npm
  publish.
* Related: [ADR-0018](adr-0018-registry-blob-storage-garage-s3.md) (Harbor blobs on Garage),
  [ADR-0064](adr-0064-dependency-track-only-sbom-platform.md) (the 2026-09-28 disk-full
  incident), [off-site Garage runbook](../runbooks/garage-offsite.md).
