# Tutorial: Add a workstation node to the Talos cluster

This guide walks through adding a new **workstation** machine to this Talos-managed Kubernetes cluster when the machine is currently booted into **Talos maintenance mode**.

It’s intentionally detailed and written as a “follow along” tutorial.

---

## What you’re trying to do

You have a new machine on your LAN (example IP: `10.0.0.23`) booted into Talos maintenance mode. You want to:

- Identify the correct install disk and NIC MAC address.
- Add the node to `talos/talconfig.yaml`.
- Regenerate Talos machine configs via `talhelper`.
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

With Talos v1.11.x, `--insecure` is a flag on certain subcommands (e.g. `talosctl get`, `talosctl apply-config`).

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

## Step 2 — Add the node to `talos/talconfig.yaml`

Edit:

- `talos/talconfig.yaml`

Add a new entry under `nodes:`.

At minimum you need:

- `hostname`
- `ipAddress`
- `installDisk` (from Step 1A)
- `networkInterfaces[].deviceSelector.hardwareAddr` (from Step 1B)

This repo uses static addressing with routes; mirror the pattern from the existing nodes.

### Example shape (do not copy blindly)

```yaml
- hostname: "fringe-workstation"
  ipAddress: "10.0.0.23"
  installDisk: "/dev/sda"
  controlPlane: true
  networkInterfaces:
    - deviceSelector:
        hardwareAddr: "f0:92:1c:e0:ec:3b"
      dhcp: false
      addresses:
        - "10.0.0.23/24"
      routes:
        - network: "0.0.0.0/0"
          gateway: "10.0.0.1"
```

Notes:

- If this is truly a workstation (not intended to be a control-plane member), set `controlPlane: false` and ensure your cluster design supports it. In this repository, all nodes are often configured to run workloads and can be controllers.
- `vip.ip` is only meaningful for control-plane nodes that participate in the API VIP configuration; follow existing patterns.

---

## Step 3 — Regenerate Talos configs

From the repo root:

```bash
task talos:generate-config
```

This runs `talhelper genconfig` and regenerates:

- `talos/clusterconfig/kubernetes-<node>.yaml` machine config(s)
- `talos/clusterconfig/talosconfig` (client config)

If this step fails, fix the YAML errors in `talos/talconfig.yaml` first.

---

## Step 4 — Apply config to the new node (maintenance API)

This repo’s task supports applying to a maintenance-mode node by passing `INSECURE=true`.

Run:

```bash
task talos:apply-node IP=10.0.0.23 INSECURE=true
```

What it does (high level):

- Generates a `talosctl apply-config` command via `talhelper`.
- Adds `--insecure` (maintenance service) and `--endpoints=10.0.0.23` (talk directly to the node).

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

- `talos/clusterconfig/talosconfig` is outdated (re-run `task talos:generate-config`).
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

If `talos/talconfig.yaml` changed (and any related repo changes), commit it:

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

This repo’s Talos v1.11 `talosctl` uses `talosctl version`.

```bash
talosctl version
```

---

## Why the repo task uses `INSECURE=true`

When a node is in maintenance mode:

- You often need `--insecure`.
- You also want `--endpoints=<node-ip>` to ensure the command doesn’t try to use cluster endpoints from `talosconfig` that the new node doesn’t trust yet.

This repository wires that behavior into the `talos:apply-node` task.
