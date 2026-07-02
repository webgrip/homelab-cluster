# RFC: Object storage — Garage is the S3 backbone, on the record

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** A single off-cluster Garage host (`10.0.0.110:3900`) is the S3 endpoint behind
> everything durable this cluster does: all CNPG WAL/backups, Longhorn volume backups, OpenBao
> snapshots, Loki chunks, Tempo traces, Harbor blobs, Forgejo LFS, GUAC blobs — and it has no
> decision record, no GitOps management, no monitoring beyond a blackbox probe, and no redundancy.
> This RFC backfills the adoption ADR and decides how the biggest single point of failure in the
> platform gets managed, watched, and eventually mirrored.

## Why

Every consumer verified in-tree (2026-07-02):

| Consumer | What lands on Garage |
| --- | --- |
| 10 CNPG `ObjectStore`s | WAL archives + base backups (`cnpg-backups-bucket`) |
| Longhorn `BackupTarget` | volume backups (`s3://cnpg-backups-bucket@garage/longhorn-backups`) |
| OpenBao snapshot CronJob | nightly raft snapshots (same bucket, `openbao-snapshots/`) |
| Loki | `loki-chunks` / `loki-ruler` / `loki-admin` (30d of logs) |
| Tempo | `tempo` (14d of traces) |
| Harbor | registry blobs, `harbor` bucket ([ADR-0002](../adr/adr-0002-registry-blob-storage-garage-s3.md)) |
| Forgejo | LFS/attachments (MinIO-mode config) |
| GUAC | `guac` blobstore (SBOMs) |
| Backstage TechDocs (planned) | `techdocs` ([ADR-0023](../adr/adr-0023-backstage-techdocs.md)) |

Individual ADRs treat Garage as a given ("the cluster already runs Garage") — but adopting Garage,
running it *outside* the cluster, and running it *un-replicated* were all real decisions with real
alternatives (MinIO, SeaweedFS, in-cluster via an operator, rook-ceph RGW), and their consequences
are the platform's biggest known risk cluster: the CNPG↔Garage **WAL SPOF** has already caused
SEVs (Garage down → all WAL archiving fails → disks fill), and the
[layered-hardware RFC](rfc-layered-hardware-architecture.md) names the single backup target as
the L5 root cause. Meanwhile the host itself is invisible to GitOps: nothing in this repo says
what hardware it runs on, how it's upgraded, how its layout/keys are provisioned, or who backs
*it* up. Monitoring exists but is thin: a blackbox `Probe`, a Sloth SLO, and PrometheusRules — all
of which watch the S3 endpoint, not disk health or capacity on the host.

Conventions have also drifted ad hoc: `cnpg-backups-bucket` holds CNPG backups *and* Longhorn
backups *and* OpenBao snapshots; per-app buckets (`loki-*`, `tempo`, `harbor`, `guac`) follow a
different one-bucket-per-consumer shape; credentials arrive variously via `observability-s3`,
`cnpg-backup`, `security-s3` components and app-specific ExternalSecrets.

## Proposal

1. **Backfill the adoption ADR**: Garage as the S3 provider, deliberately **off-cluster** (so
   storage-of-last-resort survives a cluster loss — the property ADR-0026 leans on for DR), with
   the accepted consequence that it is a hard dependency for WAL, backups, logs, traces, and
   registry blobs. Alternatives and why they lost, as originally reasoned.
2. **Bring the host under declared management** (new decision): record the host's hardware, OS,
   Garage version/config, and upgrade procedure in a runbook + `general/` doc; decide whether its
   config becomes IaC (even a committed `garage.toml` + layout snapshot beats nothing). The host
   stays outside Flux — but stops being undocumented.
3. **Monitor the host, not just the endpoint** (new decision): scrape Garage's native Prometheus
   metrics (capacity, per-bucket usage, resync queue) into VictoriaMetrics via a `VMStaticScrape`,
   with alerts on capacity and staleness — feeding the [alert-delivery RFC](rfc-alert-delivery.md)
   so they actually reach a human.
4. **Decide the redundancy path** (new decision, sequenced with L5): options are a second Garage
   node (Garage replicates natively; the cheapest 3-2-1 leg), garage-to-garage bucket replication
   to a second box, or per-consumer second targets (e.g. CNPG barman to two ObjectStores). This
   RFC's role is to pick the *mechanism*; the hardware itself rides the layered-hardware program.
5. **Write down the bucket + credential conventions**: one bucket per consumer domain, keys in
   OpenBao under `s3/<consumer>`, surfaced via the existing components — and name the
   `cnpg-backups-bucket` multi-tenancy as either accepted or to-be-split.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Adopt Garage as the off-cluster S3 backbone (retroactive) |
| candidate | — | Garage host lifecycle: documented, monitored, version-managed (new) |
| candidate | — | Redundancy mechanism for the S3 layer (new; gated on L5 hardware) |
| candidate | — | Bucket & credential conventions (new) |

## Out of scope

- What *data* must survive *which* failure — the [backup & DR RFC](rfc-backup-dr.md) owns the
  tier map; this RFC owns the substrate.
- In-cluster storage (Longhorn) — ADR-0026/0027/0029/0037.
- Buying hardware — [layered-hardware RFC](rfc-layered-hardware-architecture.md) L5.

## References

- [ADR-0002](../adr/adr-0002-registry-blob-storage-garage-s3.md) — the first "Garage is already
  there" decision · [cnpg-backups runbook](../runbooks/cnpg-backups.md) ·
  [openbao-restore runbook](../runbooks/openbao-restore.md)
