# Talos Cluster Reference

_Last updated: 2025-12-08 using live `talosctl` and `kubectl` output._

## Node Inventory

| Node | IP | Roles | Talos | Kubernetes | Kernel | Container Runtime |
| --- | --- | --- | --- | --- | --- | --- |
| soyo-1 | 10.0.0.20 | control-plane, schedulable | v1.11.5 | v1.34.2 | 6.12.57-talos | containerd 2.1.5 |
| soyo-2 | 10.0.0.21 | control-plane, schedulable | v1.11.5 | v1.34.2 | 6.12.57-talos | containerd 2.1.5 |
| soyo-3 | 10.0.0.22 | control-plane, schedulable | v1.11.5 | v1.34.2 | 6.12.57-talos | containerd 2.1.5 |

Captured via:

```bash
$ kubectl get nodes -o wide
NAME     STATUS   ROLES           VERSION   INTERNAL-IP   KERNEL-VERSION   CONTAINER-RUNTIME
soyo-1   Ready    control-plane   v1.34.2   10.0.0.20     6.12.57-talos    containerd://2.1.5
soyo-2   Ready    control-plane   v1.34.2   10.0.0.21     6.12.57-talos    containerd://2.1.5
soyo-3   Ready    control-plane   v1.34.2   10.0.0.22     6.12.57-talos    containerd://2.1.5
```

## Talos Versions

`talosctl version` confirms every node runs Talos `v1.11.5`:

```bash
$ talosctl version
Client:
   Tag:         v1.11.5
   SHA:         bc34de6e
Server:
   NODE:        10.0.0.21
   Tag:         v1.11.5
   Enabled:     RBAC
   NODE:        10.0.0.20
   Tag:         v1.11.5
   Enabled:     RBAC
   NODE:        10.0.0.22
   Tag:         v1.11.5
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
*** End Patch
