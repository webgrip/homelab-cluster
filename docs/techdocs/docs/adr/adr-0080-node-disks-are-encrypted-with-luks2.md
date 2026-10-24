---
status: accepted
date: 2026-10-24
decision-makers: Ryan Grippeling
---

# Node disks are encrypted with LUKS2: TPM-sealed on the control planes, node-derived on the workers until their TPM is on

## Context and Problem Statement

etcd's Secrets are encrypted (`secretbox`). Pod traffic between nodes is WireGuard ([ADR-0004](adr-0004-cilium-wireguard-encryption.md)). The disks are not encrypted. On 2026-10-24 no node carried a `VolumeConfig` with encryption, and the workers keep Longhorn's data in `/var/lib/longhorn` on EPHEMERAL. So every volume (Forgejo, the databases, Garage, agent workspaces with cloned source) sits in plain text on a disk that could be sold, returned for repair or taken.

Unfold's system ADR-0045 makes disk encryption part of the setup it tells self-hosters to run. What should the homelab encrypt, with which key, and how does a running node get there?

## Decision Drivers

* A disk that leaves the house must not carry readable data.
* A key is only as strong as what holds it. The three N150 control planes expose a TPM 2.0 (`tpm0`). The three workers (i7-4770, i5-4670K, i7-6700K) expose none. Secure Boot is off everywhere.
* Talos cannot encrypt a partition that holds data: each node is wiped and re-joined, so the rollout must never lose Longhorn's only replica of a volume.

## Considered Options

* LUKS2 on STATE and EPHEMERAL of every node: a TPM key on the control planes, a node-derived key on the workers, rolled out one node at a time
* TPM keys only, and leave the workers unencrypted until their TPM is on
* Longhorn per-volume encryption instead of disk encryption
* A network KMS for every node

## Decision Outcome

Chosen option: **"LUKS2 on STATE and EPHEMERAL of every node"**, because it covers every volume, scratch directory, image and log at once, with the strongest key each machine can hold today.

* **Control planes:** [`talos/patches/encryption/controlplane-tpm.yaml`](../../../../talos/patches/encryption/controlplane-tpm.yaml). TPM key bound to PCR 7; `lockToState` on EPHEMERAL.
* **Workers:** [`talos/patches/encryption/worker-nodeid.yaml`](../../../../talos/patches/encryption/worker-nodeid.yaml). Node-derived key; `lockToState` on EPHEMERAL.
  * This protects a disk that leaves on its own, not a stolen machine.
  * Each worker moves to the TPM patch once its firmware TPM (Intel PTT) is enabled and `tpm0` appears. That move is another wipe.
* **Wiring:** a patch is added to a node's `patches:` in `talos/nodes.yaml` only in the commit that wipes that node. A render of an unwiped node must never ask for encryption its disk does not have.
* **Rollout:** [Talos disk encryption runbook](../runbooks/talos-disk-encryption.md).
  * One node at a time.
  * Every single-replica Longhorn volume on a worker gets a second replica before that worker is wiped.
  * The control planes go one at a time, with the etcd leader last.

### Consequences

* Good, because a disk out of any node holds nothing readable.
* Good, because the TPM-sealed control planes resist a stolen machine booted into another system, too.
* Bad, because each node is wiped once now, and each worker again when its TPM is turned on.
* Bad, because a firmware Secure Boot or TPM reset on a control plane locks its disks; recovery is a wipe and re-join, which the cluster survives one node at a time.
* Bad, because the workers' node-derived key gives no protection against someone who takes the whole machine.

### Confirmation

* `talosctl -n <node> get volumestatus STATE -o yaml` and the same for `EPHEMERAL` show `encryptionProvider: luks2` on all six nodes.
* `talos/nodes.yaml` lists an encryption patch on every node.

## Pros and Cons of the Options

### TPM keys only, workers unencrypted

* Good, because no key is weaker than a TPM.
* Bad, because the disks that hold the data, the workers', stay plain text indefinitely.

### Longhorn per-volume encryption

* Good, because each volume gets its own key and backups are encrypted.
* Bad, because emptyDirs, container images, logs and the Talos STATE stay plain text, and Longhorn documents no key rotation.

### A network KMS

* Good, because the key never sits on the machine.
* Bad, because a KMS reachable at boot is one more always-on service, and STATE cannot take its network settings from the machine configuration.

## More Information

* Ticket: [VIK-2408](https://vikunja.webgrip.dev/tasks/2408).
* Unfold's guide: [Protect data at rest and in transit](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/docs/how-to/protect-data-at-rest-and-in-transit.md).
* Re-evaluate when the workers' TPM is enabled, or when hardware with SEV-SNP or TDX joins.
* 2026-10-24 — Accepted by Ryan Grippeling. No node is wiped yet.
