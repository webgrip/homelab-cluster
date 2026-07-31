# RFC: Offsite object storage, and reclaiming the Proxmox host as a Talos node

> Status: **Proposed** · Date: 2026-07-31 · Executes the substrate half of
> [object storage — Garage](rfc-object-storage-garage.md) and L5 of the
> [layered hardware architecture](rfc-layered-hardware-architecture.md)
>
> **TL;DR.** The Proxmox host is simultaneously the S3 backbone every durable thing in the cluster
> depends on, the home of Immich and ~13 other guests, and an idle i7-6700K while the cluster is
> short of capacity. The plan: move object storage to **Hetzner** (real offsite, no hardware spend),
> move Immich and the uptime-kuma deadman to a Hetzner VM, delete everything else on the box, then
> wipe it and join it to Talos as a worker. Three things make this more than an endpoint swap —
> Harbor's blobs must **not** go offsite, four namespaces will silently stop archiving WAL, and the
> `guac` bucket can never live on per-object-billed storage.

## Why

Two problems that happen to share one machine.

**The S3 backbone has no redundancy and no succession plan.** `10.0.0.110:3900` is a single
un-replicated Garage node holding every CNPG WAL archive, every Longhorn volume backup, every OpenBao
raft snapshot, all Harbor registry blobs, and all Forgejo LFS.
[rfc-object-storage-garage.md](rfc-object-storage-garage.md) named this the platform's biggest risk
cluster on 2026-07-02.

**The cluster wants the hardware.** The Proxmox host runs at 2% CPU. It is an i7-6700K — the fastest
CPU in the fleet — hosting 8 running LXC guests, nearly all of which are dead weight.

Going **offsite rather than to a second local box** is the decision that makes this worth doing now:
a second box in the same house survives a disk failure but not fire, theft, flood, or a power event.
Hetzner does, costs no capital, and turns a nominal 3-2-1 story into a real one.

## What moves

| Thing | Size | Destination |
| --- | --- | --- |
| `cnpg-backups-bucket` | 32.4 GiB / 25,457 objects | Hetzner Object Storage |
| `forgejo` (LFS, packages, attachments, artifacts) | 1.2 GiB / 4,065 objects | Hetzner Object Storage |
| `harbor` (registry blobs) | 37.3 GiB / 8,855 objects | **Not offsite** — see below |
| `guac` (SBOM blobstore) | 38.1 GiB / **18,235,824 objects** | **Nowhere** — starts empty |
| Immich | unknown | Hetzner VM + volume |
| uptime-kuma (the Alertmanager deadman) | trivial | same Hetzner VM |

`cnpg-backups-bucket` is multi-tenant — 13 CNPG `ObjectStore`s under `homelab-cluster/<app>-db/`,
Longhorn under `longhorn-backups/`, OpenBao under `openbao-snapshots/`, InvoiceNinja under
`invoiceninja-mariadb/`.

**Six of the ten buckets are already dead** — `loki-chunks`, `loki-ruler`, `loki-admin` (superseded by
[ADR-0041](../adr/adr-0041-victorialogs-logging-backend.md)), `tempo`
([ADR-0042](../adr/adr-0042-victoriatraces-tracing-backend.md)), `mimir`
([ADR-0034](../adr/adr-0034-victoriametrics-metrics-backend.md)) and `pyroscope` (suspended,
[ADR-0037](../adr/adr-0037-reenable-pyroscope-worker-pool.md)). Garage reports 174.9 GB used against
117 GB live, so **~58 GB is dead data**. Deleting it needs nothing and can happen immediately.

### Everything else on the host is disposable

14 LXC containers + 1 QEMU VM; only 8 running. Retained: `garage` (data only), `immich`,
`uptimekuma`. Deleted: `minio` (106), `gitea` (201), `gitea-mirror` (202) — both superseded by
in-cluster Forgejo and `apps/forgejo/gitea-mirror` — `alpine-postgresql` (203), `firefly` (204), the
stopped duplicates 101–104, `paperless-*` (108–110), and `speaches-docker` (105).

An exhaustive sweep of every local repo, `.env`, compose file, shell history, `~/.mc`, `~/.aws` and
rclone config found **zero consumers of the MinIO LXC**. It is also absent from the Backstage LXC
inventory while its neighbours are listed — an abandoned artifact of an earlier storage migration.

**There is a third object store on that host**: a Ceph RADOS Gateway at `10.0.0.10:7480`, which is why
`sdd` is a Ceph OSD. It is referenced only by `~/.s3cfg` on the owner's workstation and was never
committed. Confirm it holds nothing before the wipe, and delete those plaintext credentials.

## The three findings that shape the plan

### 1. Harbor's blobs must not go offsite

`talos/patches/global/machine-registries.yaml` makes Harbor the **registry mirror for the Talos nodes
themselves**, and per [ADR-0023](../adr/adr-0023-harbor-pull-through-proxy-cache.md) most of its
content is pull-through cache. Sending it to Hetzner means every in-cluster image pull becomes WAN
egress — for a cache whose entire purpose is avoiding exactly that — makes node image pulls
ISP-dependent (a bootstrap hazard), and would plausibly dominate the egress allowance alone.

Since Garage is going away, Harbor's blobs need a new home. Options: an **in-cluster S3** (Garage or
MinIO on Longhorn), a **large Longhorn PVC** (the option ADR-0018 explicitly rejected as consuming
constrained replicated SSD), or offsite anyway. This RFC recommends in-cluster S3, gated on the
pod-CIDR NetworkPolicy fix below, and records it as the one genuinely open decision.

Separately, and regardless of destination: Harbor's GC is DB-driven and never reconciles against
storage, so blobs that are absent at the new endpoint produce `blob unknown to registry` on pull with
**no fallback to re-fetch upstream**. Any move must be followed by **deleting the repositories in the
seven proxy projects** (`dockerhub`, `ghcr`, `quay`, `gcrmirror`, `k8s`, `forgejo`, `mcr`) via the
API, so the DB records go away with the blobs and Harbor re-populates cleanly.

### 2. Four namespaces will silently stop archiving WAL

App egress to S3 is permitted by **LAN CIDR**. An offsite endpoint is not on the LAN.

| Namespace | Rule | Verdict |
| --- | --- | --- |
| `authentik` (`networkpolicy.yaml:87`), `vikunja` (`:94`), `ploeg` (`:77`), `sparkyfitness` (`:80`) | `ipBlock: 10.0.0.0/24` only | **breaks** |
| `backstage`, `forgejo`, `freshrss`, `harbor`, `n8n`, `invoiceninja` | `0.0.0.0/0` except pod + service CIDR | fine |
| `ai`, `observability`, `security`, `longhorn-system` | no NetworkPolicy (default-deny is opt-in) | fine |

The databases keep serving traffic while this happens; the failure surfaces hours later when `pg_wal`
fills. This is the same class as the 2026-07-15 gap recorded in forgejo's `cluster.yaml`
(*"5Gi filled in ~1.5 days"*) and the 2026-07-17 identity-vs-CIDR outage. The rules must land and be
verified **before** the endpoint moves — which is safe, because adding internet egress is a no-op
while the endpoint is still on the LAN.

This is also a deliberate [ADR-0006](../adr/adr-0006-default-deny-network-policies.md) posture change:
four namespaces gain internet egress. The tightest form is a `CiliumNetworkPolicy` with `toFQDNs`
scoped to the object-storage endpoint on 443 rather than a blanket `0.0.0.0/0`.

### 3. `guac` cannot live on per-object-billed storage

18,235,824 objects averaging 2.2 KB. Providers that bill a minimum object size — Hetzner's is 64 KB —
would charge for roughly **1.16 TiB against 38 GiB of real data**, and the bucket would sit at 36% of
the per-bucket object cap. It is also uncopyable in practice: at that object count the transfer is
bounded by API round-trips, not bandwidth.

It is regenerable — the graph lives in Postgres and SBOMs are re-uploaded by the trivy-sbom-uploader
CronJob — so it starts empty. That 18.2M object count is itself a defect worth separate investigation.

## The cost of going offsite: a ~10-hour fuse

`archive_timeout` defaults to 5 minutes and nothing in this repo overrides it, so every cluster ships
a 16 MB segment every 5 minutes even when idle — a **~4.6 GB/day floor**. Against `walStorage`:

| Cluster | `walStorage` | Survives failed archiving for |
| --- | --- | --- |
| `devex-db`, `ploeg-db` | 2Gi | **~10 hours** |
| litellm, authentik, n8n, freshrss, vikunja, sparkyfitness, backstage, guac | 5Gi | ~26 h (forgejo measured ~1.5 days) |
| grafana, harbor, forgejo | 10Gi | ~2 days |

Today that fuse is lit only by a Garage outage, which is within the owner's control. Offsite, **any
ISP outage lights it**, and a 10-hour fibre outage is ordinary. Mitigations, in order of leverage:

1. **Raise `archive_timeout` 5min → 20min** — cuts the idle floor 4×, taking the 2Gi clusters from
   ~10 h to ~40 h. Costs RPO 5 min → 20 min, an easy trade at homelab scale.
2. **Lift the two 2Gi outliers to 5Gi** — noting that a `walStorage.size` bump in git does **not**
   resize the live PVC, and restarting an instance whose backlog exceeds the size kills the
   instance-manager before Postgres starts. Do it before it is needed, never during.
3. **Alert on WAL volume fullness.** `CNPGWALArchivingFailed` says archiving broke; nothing said how
   long you had left. `CNPGWALVolumeFillingUp` (75%, warning) and `CNPGWALVolumeCritical` (90%,
   critical) close that gap in `components/cnpg-monitoring`. Worth having regardless of this RFC.
4. **`maxParallel: 1` → `4`** — a recovery-rate knob that drains a backlog faster; it does not prevent
   one.

Steady-state latency is a non-issue: ~15 ms RTT against a 5-minute cadence has three orders of
magnitude of headroom, and WAL is already double-compressed (`wal_compression: zstd` at the Postgres
level, `compression: gzip` at the barman level).

## Migration mechanics worth recording

- **CNPG needs no restart.** The barman sidecar bypasses the informer cache and re-reads the
  `ObjectStore` on every WAL-archive call through a 10-second TTL cache, so an `endpointURL` change
  takes effect on the next segment with no rollout.
- **The backup catalog is endpoint-independent** — it lives under `<destinationPath>/<serverName>/`,
  so a byte-copy to the same bucket and prefix preserves every base backup and PITR chain.
- **The empty-WAL-archive check will not fire** on running clusters: it is gated by a
  `.check-empty-wal-archive` marker in PGDATA that is removed after the first successful archive. It
  *does* bite anything bootstrapped afterwards (restore-test temp clusters, DR rebuilds); the escape
  hatch is the `cnpg.io/skipEmptyWalArchiveCheck: enabled` annotation.
- **A delta-sync after the flip is mandatory.** WAL archived between the bulk copy and the endpoint
  change exists only on the old server, and Postgres will never re-archive it because
  `archive_command` already returned success. Skipping this leaves a hole in the WAL sequence that
  breaks PITR across it.
- **`PushSecret` will revert the OpenBao write.** Three PushSecrets push Secrets back into OpenBao —
  the `cnpg-backup` one rendered into 12 namespaces — and `updatePolicy` defaults to `Replace`
  (verified against the live CRD; the manifests omit the field). Any controller reconciling before
  its namespace's ExternalSecret refreshes pushes the stale endpoint back over the change. Suspend all
  three for the cutover.
- **Credentials for a new store go to a NEW KV path, never the live one.** The in-cluster Garage
  publishes to `secret/harbor/s3-cluster` while the off-cluster store keeps `secret/harbor/s3`, and
  Harbor carries a parallel ExternalSecret for each. Writing the new key over the live path would
  destroy the only copy of the old credentials — i.e. destroy the ability to roll back at all. With
  two paths the cutover is a two-line helmrelease change (`regionendpoint` + `existingSecret`) and
  the rollback is reverting that commit. The same rule applies to every consumer moved to offsite S3.
- **`secretKeyRef` env vars never hot-reload**, so GUAC and its s3-collector need an explicit
  `rollout restart`; CronJobs self-heal.
- **Forgejo's `MINIO_ENDPOINT` carries no scheme** — TLS is selected *solely* by `MINIO_USE_SSL`, so
  changing the host without that flag leaves the connection in plaintext.
- **The OpenBao snapshot uploader defaulted to `http://`** when `S3_ENDPOINT` lacked a scheme, which
  would have shipped raft snapshots in plaintext over the WAN. Fixed to default to `https://`.
- **A single OpenBao path forces all-or-nothing.** `s3/cnpg-backup` serves CNPG, Longhorn, OpenBao
  snapshots and InvoiceNinja with a single-valued `S3_ENDPOINT`/`S3_REGION`. A phased migration
  requires splitting it first.
- **Path-style addressing survives** — boto3 defaults to path-style for custom endpoints. Scheme,
  region name and bucket names all change; addressing style does not.

## Reclaiming the node

The host is an **i7-6700K with 15.58 GiB** — the fastest CPU in the cluster, and its smallest-RAM
worker. That matters because two capability labels currently resolve to exactly one node each:
`cpu=high` → `fringe-workstation` (authentik is hard-pinned to it) and `ram=high` → `worker-1`
(forgejo, VMSingle, n8n, litellm, backstage and three more). With
`components/placement/worker-pool` using a **hard** affinity, either node's loss strands its tenants.

Label the reclaimed host **`pool=worker`, `cpu=high`, `ram=standard`**. `cpu=high` dissolves the
authentik pin and gives `fringe-workstation` — the only node under real memory pressure (90.2% used,
4.73% PSI) — somewhere to shed load. Withhold `ram=high`: at 16 GB it must not attract forgejo or the
metrics backend. The README's hardware table claims 32 GB and needs correcting.

Note that reclaiming the node does **not** fix the cluster's flapping, which is a crashloop
concentrated on `fringe-workstation` (cilium restarting ~25×/3h) plus ~400 cgroup-limit OOM kills per
week on `worker-1` — not a capacity shortage. Cluster-wide requests are 31% of allocatable while nodes
run at 70–90%, which is its own problem.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Adopt offsite object storage as the backup substrate, superseding LAN Garage |
| candidate | — | Harbor blob storage stays on-LAN; pick its new home (supersedes/amends ADR-0018) |
| candidate | — | Four namespaces gain scoped internet egress (amends ADR-0006) |
| candidate | — | Reclaim the Proxmox host as a bare-metal Talos worker |

## Out of scope

- **Which workloads move onto the reclaimed node** — `workload-placement` and the soyo placement
  doctrine.
- **Fixing the flapping** — separate, and not solved by this RFC.
- **Splitting `cnpg-backups-bucket`** into per-consumer buckets —
  [rfc-object-storage-garage.md](rfc-object-storage-garage.md) owns that convention.
- **Why GUAC has 18.2M objects.**

## References

- [RFC: object storage — Garage](rfc-object-storage-garage.md) · [RFC: layered hardware
  architecture](rfc-layered-hardware-architecture.md) · [RFC: backup & DR](rfc-backup-dr.md)
- [ADR-0006 default-deny network policies](../adr/adr-0006-default-deny-network-policies.md) ·
  [ADR-0008 confine Longhorn to workers](../adr/adr-0008-confine-longhorn-to-workers.md) ·
  [ADR-0018 registry blob storage on Garage](../adr/adr-0018-registry-blob-storage-garage-s3.md) ·
  [ADR-0023 Harbor pull-through cache](../adr/adr-0023-harbor-pull-through-proxy-cache.md)
- [cnpg-backups runbook](../runbooks/cnpg-backups.md) · [openbao-restore
  runbook](../runbooks/openbao-restore.md) · [Talos cluster](../general/talos-cluster.md) ·
  [add a workstation node](../general/talos-add-workstation-node.md)
- 2026-07-31 — drafted. S3 inventory, Garage statistics, NetworkPolicy audit, `walStorage` sizes and
  the `PushSecret` `updatePolicy` default all verified against the tree and the live cluster.
