# Talos Cluster Reference

_Versions track `talos/talenv.yaml` (Talos v1.13.3 / Kubernetes v1.36.1). Service/etcd/health snapshots below were captured live on 2025-12-08 — re-run the shown commands to refresh._

## Node Inventory

| Node | IP | Roles | Talos | Kubernetes | Kernel | Container Runtime |
| --- | --- | --- | --- | --- | --- | --- |
| soyo-1 | 10.0.0.20 | control-plane, schedulable | v1.13.3 | v1.36.1 | 6.12.57-talos | containerd 2.1.5 |
| soyo-2 | 10.0.0.21 | control-plane, schedulable | v1.13.3 | v1.36.1 | 6.12.57-talos | containerd 2.1.5 |
| soyo-3 | 10.0.0.22 | control-plane, schedulable | v1.13.3 | v1.36.1 | 6.12.57-talos | containerd 2.1.5 |
| fringe-workstation | 10.0.0.23 | worker, schedulable | v1.13.3 | v1.36.1 | 6.12.57-talos | containerd 2.1.5 |

Captured via:

```bash
$ kubectl get nodes -o wide
NAME     STATUS   ROLES           VERSION   INTERNAL-IP   KERNEL-VERSION   CONTAINER-RUNTIME
soyo-1   Ready    control-plane   v1.36.1   10.0.0.20     6.12.57-talos    containerd://2.1.5
soyo-2   Ready    control-plane   v1.36.1   10.0.0.21     6.12.57-talos    containerd://2.1.5
soyo-3   Ready    control-plane   v1.36.1   10.0.0.22     6.12.57-talos    containerd://2.1.5
fringe-workstation   Ready    <none>          v1.36.1   10.0.0.23     6.12.57-talos    containerd://2.1.5
```

## Talos Versions

`talosctl version` confirms every node runs Talos `v1.13.3`:

```bash
$ talosctl version
Client:
   Tag:         v1.13.3
   SHA:         bc34de6e
Server:
   NODE:        10.0.0.21
   Tag:         v1.13.3
   Enabled:     RBAC
   NODE:        10.0.0.20
   Tag:         v1.13.3
   Enabled:     RBAC
   NODE:        10.0.0.22
   Tag:         v1.13.3
   Enabled:     RBAC
```

## Talos Services

`talosctl -n <node> services` shows each controller node is running the same service set. Service health is `OK` everywhere except for `dashboard`, which reports `?` (expected because the dashboard process does not emit health probes).

| Service | Purpose | State |
| --- | --- | --- |
| `apid` | Talos API endpoint | Running / OK on all nodes |
| `auditd` | Kernel + Talos auditing | Running / OK on all nodes |
| `containerd` & `cri` | Workload runtime | Running / OK on all nodes |
| `dashboard` | Minimal on-device UI | Running / health unknown |
| `etcd` | Control-plane datastore | Running / OK on all nodes |
| `kubelet` | Schedules control-plane + workloads | Running / OK on all nodes |
| `machined`, `syslogd`, `trustd`, `udevd` | Core Talos services | Running / OK on all nodes |

Example output (soyo-1):

```bash
$ talosctl -n 10.0.0.20 services
SERVICE      STATE     HEALTH
apid         Running   OK
auditd       Running   OK
containerd   Running   OK
cri          Running   OK
dashboard    Running   ?
etcd         Running   OK
kubelet      Running   OK
machined     Running   OK
syslogd      Running   OK
trustd       Running   OK
udevd        Running   OK
```

## etcd Membership

`talosctl -n 10.0.0.20 etcd members` returns the current quorum:

| Node | Member ID | Peer URL | Client URL |
| --- | --- | --- | --- |
| soyo-3 | `095b01a1ed665202` | `https://10.0.0.22:2380` | `https://10.0.0.22:2379` |
| soyo-2 | `6f0eaeed2ed89b10` | `https://10.0.0.21:2380` | `https://10.0.0.21:2379` |
| soyo-1 | `f159b31c2ef7d8a1` | `https://10.0.0.20:2380` | `https://10.0.0.20:2379` |

Ensure any future membership adjustments (replacements, learners) maintain three healthy voters.

## Cluster Health Snapshot

`talosctl -n 10.0.0.20 health` ran to completion with every check returning `OK`. The kube-proxy probe is skipped because Cilium is deployed in kube-proxy-free mode (`kubernetes/apps/kube-system/cilium`). Re-run this command after any control-plane maintenance to validate boot sequences and Kubernetes readiness end-to-end.

## Configuration Workflow

1. Generate base configs:
   ```bash
   talosctl gen config homelab https://k8s-api.home.arpa:6443 \
     --output ./talos/clusterconfig
   ```
2. Commit the generated `kubernetes-soyo-{1,2,3}.yaml` plus `talosconfig` (encrypted or stored securely) to this repo.
3. Apply edits with `talosctl apply-config --nodes <ip> --file talos/clusterconfig/kubernetes-<node>.yaml`.
4. Use `talosctl etcd members` and `talosctl health` after each change.

## Talos Patches in Use

- `talos/patches/controller/cluster.yaml` enables scheduling on control-plane nodes, turns off the built-in CoreDNS and kube-proxy components, and exposes control-plane metrics on every interface.
- `talos/patches/global/machine-*.yaml` standardize networking (`10.0.0.0/24`), kubelet node IP detection, sysctls, and time sync.

Any new behavior (taints, sysctls, network changes) should be added via these patch files so `make configure` and `talosctl apply-config` remain deterministic.

## Gateway + VIP Assignments

Values from `cluster.yaml`:

| Purpose | Variable | Address |
| --- | --- | --- |
| Talos & Kubernetes API VIP | `cluster_api_addr` | `10.0.0.25` |
| Split-DNS LoadBalancer (`k8s-gateway`) | `cluster_dns_gateway_addr` | `10.0.0.26` |
| Internal Envoy gateway | `cluster_gateway_addr` | `10.0.0.27` |
| External Envoy / Cloudflare tunnel | `cloudflare_gateway_addr` | `10.0.0.28` |

Update the table whenever the load-balancer IPs shift so downstream split-DNS instructions stay correct.

## Hardware

The cluster is four bare-metal Talos nodes: three identical **SOYO N150 mini-PCs** as control-plane/etcd (also schedulable), and one **HP Z230 tower** as a dedicated worker. Aggregate capacity is **20 vCPU** and **~52 GiB RAM**.

Specs below were captured live on **2026-06-19** with `talosctl get` (see [Re-capturing hardware specs](#re-capturing-hardware-specs)). At capture every node was running **Talos v1.13.2 / kernel 6.18.29-talos** (kubelet v1.36.1) — note `talos/talenv.yaml` declares `v1.13.3`, so the running OS is one patch behind the desired version.

| Node | IP | Chassis / board | CPU | Cores / threads | RAM | Boot SSD | Extra physical disk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| soyo-1 | 10.0.0.20 | SOYO N150 mini-PC (M4) | Intel N150 (Twin Lake) | 4C / 4T | 12 GiB | 512 GB SATA SSD (WUXIN G15) | — |
| soyo-2 | 10.0.0.21 | SOYO N150 mini-PC (M4) | Intel N150 (Twin Lake) | 4C / 4T | 12 GiB | 512 GB SATA SSD (WUXIN G15) | — |
| soyo-3 | 10.0.0.22 | SOYO N150 mini-PC (M4) | Intel N150 (Twin Lake) | 4C / 4T | 12 GiB | 512 GB SATA SSD (WUXIN G15) | — |
| fringe-workstation | 10.0.0.23 | HP Z230 Tower Workstation (SKU `WM572ET#ABB`) | Intel Core i7-4770 @ 3.40 GHz (Haswell) | 4C / 8T | 16 GiB | 256 GB SATA SSD (Micron `MTFDDAK256MAM-1K`) | 1 TB SATA HDD (Seagate `ST1000DM003`, 7200 rpm) + DVD-RAM (`sr0`) |

The SOYO boards report no SMBIOS vendor/product strings (`Default string`); the `M4` model name comes from the purchase, not firmware. Wi-Fi/Bluetooth radios on the SOYO units remain disabled in firmware. Kubernetes-reported _allocatable_ memory is slightly below physical (firmware/kernel reserve): soyo ≈ 11.4 GiB of 12 GiB, fringe ≈ 15.3 GiB of 16 GiB.

### Memory modules

| Node | Populated | Modules | Total |
| --- | --- | --- | --- |
| soyo-1/2/3 | 4 channels | 4 × 3 GiB Samsung — LPDDR5, soldered (SMBIOS `Controller0-ChannelA…D`) | 12 GiB |
| fringe-workstation | 3 of 4 DIMMs | Micron DDR3-1600 UDIMM: 8 GiB (`DIMM2`) + 4 GiB (`DIMM1`) + 4 GiB (`DIMM3`); `DIMM4` empty | 16 GiB |

`fringe-workstation` has **one free DIMM slot** (DDR3 UDIMM on the Z230/Haswell platform), so it can still be expanded.

### Storage — physical vs. Longhorn

`talosctl get disks` is dominated by noise: every Longhorn replica is attached to its node as an **iSCSI `VIRTUAL-DISK`** (the `iscsi-tools` system extension), and runtime device letters (`sda`, `sdb`, …) shift as those volumes attach/detach. **Only rows with `transport: sata` are physical hardware:**

- **soyo-1/2/3** — a single 512 GB SATA SSD each. etcd, the OS, _and_ every Longhorn replica share this one disk, which is the cluster's primary I/O bottleneck and the reason write-heavy workloads are pinned off the control plane (see below). At capture soyo-2 had ~17 and soyo-3 ~20 iSCSI virtual disks attached.
- **fringe-workstation** — a 256 GB Micron SSD (OS / install disk) plus a **dedicated 1 TB Seagate HDD** (rotational) and a DVD-RAM drive. That separate spindle is why this node absorbs bulk/write-heavy storage.

Install disks are pinned in `talos/talconfig.yaml` (`installDisk:` — `/dev/sdb` on soyo, `/dev/sda` on fringe). Because runtime letters are unstable, treat `installDisk` as an install-time selector only, not a way to identify a disk on a running node.

### Workload placement consequence

Three control-plane nodes share one SSD apiece; only `fringe-workstation` has a dedicated data disk _and_ the most RAM (16 GiB) _and_ SMT (8 threads). Write-heavy workloads must therefore land on it via hard nodeAffinity (`node-role.kubernetes.io/control-plane DoesNotExist`). See the `talos` skill and [Adding a workstation node](talos-add-workstation-node.md).

### Re-capturing hardware specs

All read-only and safe to run any time:

```bash
TC=talos/clusterconfig/talosconfig
NODES=10.0.0.20,10.0.0.21,10.0.0.22,10.0.0.23

mise exec -- talosctl --talosconfig "$TC" -n "$NODES" get systeminformation  # chassis / board / SKU
mise exec -- talosctl --talosconfig "$TC" -n "$NODES" get processors         # CPU model, cores, threads
mise exec -- talosctl --talosconfig "$TC" -n "$NODES" get memorymodules      # per-DIMM size + vendor
mise exec -- talosctl --talosconfig "$TC" -n "$NODES" get disks              # disks (keep transport=sata for physical)

# Kubernetes-reported capacity / kernel / kubelet:
mise exec -- kubectl get nodes -o wide
```

## Network Wiring

- Protectli V1410 running OPNsense terminates Odido fiber, WireGuard, and split-horizon DNS at `10.0.0.1`.
- Switching path mirrors the README diagram: TP-Link TL-SG108PE (`10.0.0.2`) uplinks the Protectli and Zyxel VMG8825-T50 AP, while a downstream Q-Link switch fans out to the SOYO nodes, NAS, Proxmox, and Home Assistant.

**Port map (summarized):**

- TP-Link TL-SG108PE
   - Port 1 → Protectli/ONT uplink
   - Port 2 → Zyxel AP
   - Port 3 → Q-Link downstream switch
- Q-Link switch
   - Port 8 ← uplink from TP-Link switch
   - Ports 7/6/5 → `soyo-1`/`soyo-2`/`soyo-3`
   - Port 2 → NAS
   - Port 1 → Proxmox host
- Zyxel VMG8825-T50
   - Port 4 ← uplink from TP-Link switch
   - Port 1 → Philips Hue bridge
   - Port 2 → Raspberry Pi Home Assistant

Replicate these assignments any time hardware is replaced so the TechDocs, README, and wiring closet labels stay synchronized.
