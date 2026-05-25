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

- `mise exec -- just talos-upgrade-node IP=<node-ip>`

Verify:

- `mise exec -- talosctl version --nodes <node-ip>`
- `mise exec -- kubectl get node <node-name> -o wide`

## Troubleshooting

- If `etcd members` is flaky or gets canceled, always pin to a single endpoint/node:
  - `mise exec -- talosctl etcd members --endpoints <ip> --nodes <ip>`
- If you need to upgrade a maintenance-mode node, the tasks support `INSECURE=true`:
  - `mise exec -- just talos-upgrade-node IP=<ip> INSECURE=true`
