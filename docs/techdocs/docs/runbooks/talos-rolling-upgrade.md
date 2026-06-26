# Runbook: Talos rolling upgrade

This is the detailed procedure for upgrading Talos across the cluster, one node at a time.

## Safety model

- Upgrade one control-plane node at a time.
- Do not proceed until the upgraded node is back to `Ready` in Kubernetes and Talos health is clean.

## Update pins

1) Update tool pin (client)

- Edit `.mise.toml`:
  - `aqua:siderolabs/talos = <version>`

2) Update cluster target version

- Edit `talos/talenv.yaml`:
  - `talosVersion: vX.Y.Z`

## Install tools

- `mise install`
- Confirm:
  - `mise exec -- talosctl version --client`

## Preflight checks

- `mise exec -- kubectl get nodes -o wide`
- `mise exec -- talosctl health --endpoints <any-node-ip> --nodes <same-node-ip>`
- etcd members via a single node:
  - `mise exec -- talosctl etcd members --endpoints <any-node-ip> --nodes <same-node-ip>`

### Talos 1.13 preflight (v1.12 -> v1.13)

Run these checks before upgrading to `talosVersion: v1.13.x`:

- Confirm no legacy `.machine.env` usage (migrate to `EnvironmentConfig` if found):
  - `grep -RniE "machine\\.env|EnvironmentConfig" talos/`
- If GPU workloads are used, migrate from NVIDIA device plugin/runtime class to GPU Operator (CDI-based) before upgrading:
  - `mise exec -- kubectl get ds -A | grep -i nvidia`
  - `mise exec -- kubectl get runtimeclass`
- Validate Talos API automation and upgrade tasks still use standard `talosctl upgrade`/`talhelper` flows (LifecycleService-backed in 1.13):
  - `grep -RniE "upgrade-node|talosctl upgrade|talhelper gencommand upgrade" justfile .taskfiles talos docs`

Recommended follow-up improvements after upgrade:

- When custom Talos component env vars are needed, manage them explicitly via `EnvironmentConfig` documents.
- For future GPU enablement, prefer CDI-compatible deployment patterns (GPU Operator) over legacy device plugin-only setup.

## Upgrade one node

> **Force-drain single-replica-PDB workloads first.** The drain built into the
> Talos node-upgrade flow (`task talos:upgrade-node`) stalls indefinitely on
> single-replica workloads protected by a PodDisruptionBudget — it cannot evict
> them, so it hits the internal drain timeout and the node never actually
> reboots onto the new image (even though the task may print "upgrade
> completed"). This has bitten all 5 nodes. The two recurring offenders are the
> kyverno admission/background controllers and the single-instance CNPG
> databases. Remedy: **before** running the upgrade, drain the node yourself
> with eviction disabled (which bypasses the PDB by deleting pods directly):
>
> ```sh
> mise exec -- kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --disable-eviction
> ```
>
> Alternatively, temporarily scale down or relocate the single-replica
> workloads. A stalled upgrade is safe to Ctrl+C; retry it after the node is
> drained.

- `mise exec -- just talos-upgrade-node IP=<node-ip>`

Verify:

- `mise exec -- talosctl version --nodes <node-ip>`
- `mise exec -- kubectl get node <node-name> -o wide`

At `talosVersion: v1.13.4` the bundled etcd is `v3.6.12`.

## Troubleshooting

- If `etcd members` is flaky or gets canceled, always pin to a single endpoint/node:
  - `mise exec -- talosctl etcd members --endpoints <ip> --nodes <ip>`
- If you need to upgrade a maintenance-mode node, the tasks support `INSECURE=true`:
  - `mise exec -- just talos-upgrade-node IP=<ip> INSECURE=true`
