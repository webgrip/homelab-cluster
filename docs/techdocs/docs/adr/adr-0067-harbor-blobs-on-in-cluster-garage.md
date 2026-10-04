---
status: accepted
date: 2026-10-04
---

# Harbor keeps its registry blobs on the in-cluster Garage, on Longhorn

Technical Story: ADR audit of 2026-10-04, which found
[ADR-0018](adr-0018-registry-blob-storage-garage-s3.md) describing an endpoint and a reason that no
longer held.

## Context and Problem Statement

[ADR-0018](adr-0018-registry-blob-storage-garage-s3.md) put Harbor's blobs in a Garage bucket on the
Proxmox box at `10.0.0.110:3900`, with one main reason: keep bulk registry data off the replicated,
capacity-constrained Longhorn SSD tier. In July 2026 that box was reclaimed for worker-2. Harbor's
blobs needed a new home before the box went, and the only other Garage, the off-site one on
garage-fsn1, is a backup target reached over the WAN and has already filled up once.

## Considered Options

* An in-cluster Garage StatefulSet on a Longhorn volume
* The off-site Garage on garage-fsn1
* Harbor's filesystem storage on a Longhorn PVC

## Decision Outcome

Chosen option: "An in-cluster Garage StatefulSet on a Longhorn volume", because it keeps Harbor's
S3 configuration and the bucket model unchanged, keeps blob traffic inside the cluster, and leaves
the off-site Garage to hold backups only ([ADR-0065](adr-0065-forgejo-objects-on-its-own-volume.md)).

* `kubernetes/apps/garage/garage/app/garage.yaml` runs Garage with its data on a 100Gi
  `longhorn-single` PVC.
* Harbor's `imageChartStorage` points at `http://garage-s3.garage.svc.cluster.local:3900`, with
  credentials from `secret/harbor/s3-cluster`.

### Consequences

* Good, because blob reads and writes stay on the LAN and in the cluster's failure domain.
* Good, because the off-site Garage stops carrying registry data.
* Bad, because the blobs are back on the Longhorn SSD tier ADR-0018 set out to avoid: about 66 GiB on
  2026-10-01, mostly Harbor ([ADR-0065](adr-0065-forgejo-objects-on-its-own-volume.md)).
* Bad, because `longhorn-single` keeps one replica, so losing that volume loses every first-party
  image not rebuilt or re-pulled; proxied third-party images re-fill from upstream.
* Bad, because Garage pulls its own image through Harbor while Harbor stores its blobs in Garage,
  a cold-start loop that holds until Garage's image reference falls back to upstream
  ([ADR-0023](adr-0023-harbor-pull-through-proxy-cache.md)).

### Confirmation

* Harbor's HelmRelease `imageChartStorage.s3.regionendpoint` names the in-cluster Garage Service.
* `kubectl -n garage get pvc` shows the Garage data volume Bound on `longhorn-single`.

## Pros and Cons of the Options

### The off-site Garage on garage-fsn1

* Good, because the blobs leave Longhorn entirely.
* Bad, because every pull crosses the WAN, and that disk already filled once with backup traffic.

### Harbor's filesystem storage on a Longhorn PVC

* Good, because it drops a component.
* Bad, because it changes Harbor's storage driver and loses the S3 path the migration Jobs relied on.

## More Information

* Supersedes [ADR-0018](adr-0018-registry-blob-storage-garage-s3.md).
* 2026-07-31 — in-cluster Garage StatefulSet added (c43d3992).
* 2026-08-01 — blobs copied (e89a400f) and Harbor cut over to the in-cluster Garage (631ac343).
* 2026-10-04 — recorded in the ADR audit; in effect since 2026-08-01 without a record.
