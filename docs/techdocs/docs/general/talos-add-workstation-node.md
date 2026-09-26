# Tutorial: Add a workstation node to the Talos cluster

This guide walks through adding a new **workstation** machine to this Talos-managed Kubernetes cluster when the machine is currently booted into **Talos maintenance mode**.

It’s intentionally detailed and written as a “follow along” tutorial.

---

## What you’re trying to do

You have a new machine on your LAN (example IP: `10.0.0.23`) booted into Talos maintenance mode. You want to:

- Identify the correct install disk and NIC MAC address.
- Add the node to `talos/nodes.yaml` and give it a network file under `talos/nodes/`.
- Regenerate Talos machine configs with `just talos-generate-config`.
- Apply the config to the node using the **maintenance API** (`--insecure`).
- Verify Talos + Kubernetes see the node as healthy.

---

## Background (why you hit TLS errors)

Talos maintenance mode exposes an API on port `50000`, but it uses an **insecure maintenance service**:

- Traffic is encrypted, but **not authenticated**.
- The server presents a certificate which is not signed by your cluster CA.

So a normal command like this often fails when the node is in maintenance mode:

```bash
talosctl --nodes 10.0.0.23 get machineconfig
```

With an error like:

- `x509: certificate signed by unknown authority`

### Important: `--insecure` is not a global flag

In this repo's `talosctl` (v1.13 line), `--insecure` is a flag on certain subcommands (e.g. `talosctl get`, `talosctl apply-config`).

This is **wrong** (it won’t parse the way you expect):

```bash
talosctl --insecure get disks
```

This is **correct**:

```bash
talosctl get disks --insecure
```

---

## Prerequisites

- You can reach the node’s Talos API on port `50000`.
- You have the repo checked out and your usual tooling installed (via `mise`).
- Your repo already has a working cluster (or at least the existing Talos configs are valid).

### Quick sanity check: port 50000 reachable

```bash
nmap -Pn -n -p 50000 10.0.0.23 -vv
```

Expected:

- `50000/tcp open`

If port 50000 is not open, stop and fix networking first (wrong VLAN, wrong IP, firewall, etc.).

---

## Step 1 — Collect disk + NIC info (maintenance mode)

In maintenance mode, prefer reading **hardware resources** (disks, links) rather than `machineconfig`.

### 1A) Identify the install disk

Run:

```bash
talosctl get disks \
  --nodes 10.0.0.23 \
  --endpoints 10.0.0.23 \
  --insecure
```

What you’re looking for:

- The disk you want Talos installed to (often `/dev/sda` or `/dev/nvme0n1`).
- Avoid the USB installer media (often small and marked as `usb`).

Tip: if you see both an SSD and a large spinning disk, double-check you’re choosing the disk you actually intend to wipe and dedicate to Talos.

### 1B) Get the NIC MAC address used for networking

Run:

```bash
talosctl get links \
  --nodes 10.0.0.23 \
  --endpoints 10.0.0.23 \
  --insecure
```

Find the interface that is `up true` (example: `eno1`) and note its `HW ADDR`.

---

## Step 2 — Add the node to `talos/nodes.yaml`

The generator is plain `talosctl gen config` driven by an inventory
([ADR-0062](../adr/adr-0062-talos-configs-from-plain-talosctl.md)). A node is two edits:

1. An entry under `nodes:` in `talos/nodes.yaml`:

    ```yaml
    - hostname: worker-3
      address: 10.0.0.33
      role: worker
      installDisk: /dev/sda
      schematic: d1200926df53a3d0c6a8bed8575e9eb212152a2decf792d9dfc7bea484f36be8
      patches:
        - nodes/worker-3.yaml
    ```

    - `installDisk` comes from Step 1A.
    - `schematic` is the Image Factory ID: kata (`d1200926…`) on workers, base (`1da3394e…`) on control planes.
    - `patches` lists this node's own patches, applied after the global and role patches.

2. A network file, `talos/nodes/<hostname>.yaml`. Copy an existing node's file and change the
   hostname, the MAC address (from Step 1B) and the IP address. A control plane also carries the
   `Layer2VIPConfig` document for the API VIP `10.0.0.25`:

    ```yaml
    ---
    apiVersion: v1alpha1
    kind: HostnameConfig
    auto: "off"
    hostname: worker-3
    ---
    apiVersion: v1alpha1
    kind: LinkAliasConfig
    name: ethSel0
    selector:
      match: glob("aa:bb:cc:dd:ee:ff", mac(link.hardware_addr))
    ---
    apiVersion: v1alpha1
    kind: LinkConfig
    name: ethSel0
    mtu: 1500
    addresses:
      - address: 10.0.0.33/24
    routes:
      - gateway: 10.0.0.1
    ```

Workers take addresses from the `.30`–`.39` block and control planes from `.20`–`.24`.

---

## Step 3 — Regenerate Talos configs

From the repo root:

```bash
mise exec -- just talos-generate-config
```

This runs `scripts/talos-genconfig.sh`, which regenerates:

- `talos/clusterconfig/kubernetes-<node>.yaml` machine config(s)
- `talos/clusterconfig/talosconfig` (client config)

If this step fails, fix the YAML in `talos/nodes.yaml` or in the node's patch file first.

---

## Step 4 — Apply config to the new node (maintenance API)

The `talos-apply-node` recipe applies to a maintenance-mode node when you pass the address the
node answers on right now, followed by `insecure=true`.

Run:

```bash
mise exec -- just talos-apply-node <hostname> <maintenance-mode-ip> auto true
```

What it does (high level):

- Looks the node up in `talos/nodes.yaml` and picks `talos/clusterconfig/kubernetes-<hostname>.yaml`.
- Applies it with `--insecure` (maintenance service), talking directly to the maintenance-mode address.

### Expected behavior

- The node will typically reboot after the config applies.
- During reboot you may see transient failures like `connection refused`.

---

## Step 5 — Verify Talos is healthy (authenticated API)

Once port `50000` is open again, verify Talos can connect without `--insecure`:

```bash
talosctl get machinestatus --nodes 10.0.0.23
```

Expected:

- `READY` should be `true`
- `STAGE` should be `running`

If you still get TLS errors here, you may be hitting one of these:

- `talos/clusterconfig/talosconfig` is outdated (re-run `just talos-generate-config`).
- You’re connecting to the wrong node IP.

---

## Step 6 — Verify Kubernetes sees the node

```bash
kubectl get nodes -o wide
```

Expected:

- The new node appears (e.g. `fringe-workstation`)
- `STATUS` becomes `Ready`

If it shows up but stays `NotReady`, check:

- `kubectl describe node <name>`
- `kubectl -n kube-system get pods -o wide` (CNI, kube-proxy if present, etc.)

---

## Step 7 — Commit and push (GitOps)

If `talos/nodes.yaml` or `talos/nodes/` changed (and any related repo changes), commit them:

```bash
git add -A
git commit -m "chore(talos): add workstation node"
git push
```

Note: generated `talos/clusterconfig/kubernetes-*.yaml` files are typically ignored in this repo; that’s expected.

---

## Troubleshooting

### A) `x509: certificate signed by unknown authority`

- In maintenance mode, this is expected if you do not use `--insecure`.
- Use the maintenance service for discovery:

```bash
talosctl get disks --nodes <ip> --endpoints <ip> --insecure
```

### B) `not authorized`

This often happens when trying to read privileged resources over the maintenance API (for example `machineconfig`).

Use `disks` and `links` for maintenance-mode checks, and only query `machineconfig` once the node is fully configured and joined.

### C) `connection refused`

Usually indicates the node is rebooting or the API service is restarting after `apply-config`.

- Wait 10–60 seconds, then re-check with `nmap -p 50000 <ip>`.

### D) `talosctl --version` fails

`talosctl` has no `--version` flag — use `talosctl version`.

```bash
talosctl version
```

---

## Why the repo just recipe uses `INSECURE=true`

When a node is in maintenance mode:

- You often need `--insecure`.
- You also want `--endpoints=<node-ip>` to ensure the command doesn’t try to use cluster endpoints from `talosconfig` that the new node doesn’t trust yet.

This repository wires that behavior into the `talos-apply-node` recipe.

---

## Gotchas after the node has joined

### Later config changes: `apply-node` only reboots on reboot-requiring drift

A **label/annotation-only** change (e.g. adding `node.webgrip.io/*` capability labels) applies **live**
on a freshly-added node — but on an *older* node whose stored `install.image` has drifted from
`talenv.yaml`, `--mode=auto` will **reboot** to reconcile it. For label-only changes on etcd/control-plane
nodes, force the live path:

```bash
mise exec -- just talos-apply-node <hostname> '' no-reboot
```

`no-reboot` applies what it can live and **stages** any reboot-requiring drift (it refuses, never
reboots). Rebooting a storage node also churns Longhorn (degraded waves) — see
[incident 2026-06-19](../incidents/2026-06-19-node-taxonomy-migration-storage-churn.md).

### Existing Longhorn PVs do **not** include the new node

Longhorn writes each PV's `spec.nodeAffinity` from the nodes that existed when the volume was created and
**does not refresh it** when a node joins. So **existing stateful volumes cannot attach on the new node**
— a pod with such a PVC, hard-pinned to a pool that resolves only to the new node, goes `Pending`
(`didn't match PersistentVolume's node affinity`). The new node becomes a valid attach point for an
existing volume only once Longhorn places a **replica** there (e.g. via eviction from another node, or a
new replica scheduled to it). Practically: **migrate/evict replicas onto the new node before pinning
existing stateful workloads to it.** New volumes created after the node joined are unaffected.

```bash
# inspect a volume's PV node affinity (which nodes it may attach to)
mise exec -- kubectl get pv <pv-name> -o jsonpath='{.spec.nodeAffinity}{"\n"}'
```
