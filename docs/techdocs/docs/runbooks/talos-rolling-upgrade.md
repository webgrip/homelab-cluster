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

## Upgrade one node

- `mise exec -- task talos:upgrade-node IP=<node-ip>`

Verify:

- `mise exec -- talosctl version --nodes <node-ip>`
- `mise exec -- kubectl get node <node-name> -o wide`

## Troubleshooting

- If `etcd members` is flaky or gets canceled, always pin to a single endpoint/node:
  - `mise exec -- talosctl etcd members --endpoints <ip> --nodes <ip>`
- If you need to upgrade a maintenance-mode node, the tasks support `INSECURE=true`:
  - `mise exec -- task talos:upgrade-node IP=<ip> INSECURE=true`
