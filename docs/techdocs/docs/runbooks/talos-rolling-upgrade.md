# Runbook: Talos rolling upgrade

Detailed procedure for upgrading Talos across the cluster, one node at a time. Node ops in general (apply-config, drains, adding nodes): `talos` skill.

## Safety model

- Upgrade one control-plane node at a time.
- Do not proceed until the upgraded node is back to `Ready` in Kubernetes and Talos health is clean.

## Update pins

1) Tool pin (client) — `.mise.toml`: `aqua:siderolabs/talos = <version>`
2) Cluster target — `talos/talenv.yaml`: `talosVersion: vX.Y.Z`

Then `mise install` and confirm: `mise exec -- talosctl version --client`

## Preflight checks

- `mise exec -- kubectl get nodes -o wide`
- `mise exec -- talosctl health --endpoints <any-node-ip> --nodes <same-node-ip>`
- etcd members via a single node:
  - `mise exec -- talosctl etcd members --endpoints <any-node-ip> --nodes <same-node-ip>`

## Upgrade one node

> **Force-drain single-replica-PDB workloads first.** The drain built into the
> Talos node-upgrade flow stalls indefinitely on single-replica workloads
> protected by a PodDisruptionBudget — it cannot evict them, so it hits the
> internal drain timeout and the node never actually reboots onto the new image
> (even though the task may print "upgrade completed"). This has bitten all 5
> nodes. The two recurring offenders are the kyverno admission/background
> controllers and the single-instance CNPG databases. Remedy: **before** running
> the upgrade, drain the node yourself with eviction disabled (which bypasses
> the PDB by deleting pods directly):
>
> ```sh
> mise exec -- kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --disable-eviction
> ```
>
> Alternatively, temporarily scale down or relocate the single-replica
> workloads. A stalled upgrade is safe to Ctrl+C; retry it after the node is
> drained.

```bash
mise exec -- just talos-upgrade-node <node-ip>
# equivalently: mise exec -- task talos:upgrade-node IP=<node-ip>
```

> **`IP` is a positional just argument.** `just talos-upgrade-node IP=<node-ip>` is broken — just
> treats `IP=…` as a variable override, so the recipe's yq selector receives the literal string
> `IP=<node-ip>` and matches no node. Only the `task` form takes `IP=` as a named var.

Verify:

- `mise exec -- talosctl version --nodes <node-ip>`
- `mise exec -- kubectl get node <node-name> -o wide`

At `talosVersion: v1.13.4` the bundled etcd is `v3.6.12`.

## Troubleshooting

- If `etcd members` is flaky or gets canceled, always pin to a single endpoint/node:
  - `mise exec -- talosctl etcd members --endpoints <ip> --nodes <ip>`
- Upgrading a maintenance-mode node (no machine config yet) needs the insecure variant —
  `INSECURE` is the second positional argument to just:
  - `mise exec -- just talos-upgrade-node <ip> true`
  - (or `mise exec -- task talos:upgrade-node IP=<ip> INSECURE=true`)
