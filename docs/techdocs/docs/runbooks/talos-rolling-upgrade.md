# Runbook: Talos rolling upgrade

Detailed procedure for upgrading Talos across the cluster, one node at a time. Node ops in general (apply-config, drains, adding nodes): `talos` skill.

## Safety model

- Upgrade one control-plane node at a time.
- Do not proceed until the upgraded node is back to `Ready` in Kubernetes and Talos health is clean.
- Take an etcd snapshot before the first control plane: `mise exec -- talosctl -n 10.0.0.20 etcd snapshot <file>`.
  Keep it outside the repo — it holds the whole cluster state.
- Run `just talos-generate-config` before any upgrade or apply. The files in `talos/clusterconfig/` are
  gitignored and only as fresh as the last run; stale ones carry old installer images and schematics
  (on 2026-09-25 they would have stripped the kata extension from every worker).
- Move to the latest patch of the current minor before the next minor.

## Node order

1. `soyo-1`, `soyo-2`, then `soyo-3` (`10.0.0.22`) — whichever control plane is etcd leader goes last
   (`talosctl etcd status`).
2. `fringe-workstation` — holds no Longhorn replicas.
3. `worker-2`, then `worker-1` — the two Longhorn storage nodes. Almost every volume keeps one replica on
   each, so rebooting one leaves them all `degraded`. Start the second only when every volume is
   `healthy` again, or volumes lose their last good replica. Check for the rebuild wedge after each:
   `degraded > 0` with **zero** rebuilding means zombie replicas —
   [longhorn-rebuild-wedge](longhorn-rebuild-wedge.md).

## Version floors

| Floor | Why |
| --- | --- |
| Never below **v1.13.9** once any node ran v1.13.8 or later | `iscsi-tools` in v1.13.8 moved open-iscsi 2.1.11 → 2.1.12, which renamed the persisted node-record key `conn_reopen_log_freq` → `sess_reopen_log_freq` with no alias. Each version fails (exit 7) on records the other wrote, `/var/lib/iscsi` survives upgrades and downgrades, and Longhorn drives the host's `iscsiadm`, so every engine operation on the node fault-loops. The cluster sat on v1.13.7 from 2026-08-12 after fringe and soyo-1 hit it. The compat patch ([siderolabs/extensions#1182](https://github.com/siderolabs/extensions/issues/1182), commit `12c403379657`) ships from v1.13.9; v1.14.1 moves to open-iscsi 2.1.13, which writes both spellings. |
| etcd is one-way after the minor that bumps it | Talos v1.14 carries etcd 3.7. Once all three control planes run it, `talosctl rollback` no longer returns etcd to 3.6; recovery is the pre-upgrade snapshot. |

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
# equivalently: mise exec -- just talos-upgrade-node <hostname>
```

> **`IP` is a positional just argument.** `just talos-upgrade-node IP=<node-ip>` is broken — just
> treats `IP=…` as a variable override, so the recipe's yq selector receives the literal string
> `IP=<node-ip>` and matches no node. Only the `task` form takes `IP=` as a named var.

Verify:

- `mise exec -- talosctl version --nodes <node-ip>`
- `mise exec -- kubectl get node <node-name> -o wide`

At `talosVersion: v1.13.4` the bundled etcd is `v3.6.12`.

## Troubleshooting

- `error creating Kubernetes client for drain: … kubeconfig is only available on control plane nodes`
  means talosctl was pointed at a worker as its endpoint. It fetches the drain kubeconfig from the
  endpoint, so the image installs, the drain fails, and the node never reboots. The recipe keeps the
  control-plane endpoints from the talosconfig for every upgrade except `insecure`; re-running it
  finishes a node left in that state.

- If `etcd members` is flaky or gets canceled, always pin to a single endpoint/node:
  - `mise exec -- talosctl etcd members --endpoints <ip> --nodes <ip>`
- Upgrading a maintenance-mode node (no machine config yet) needs the insecure variant. The
  arguments are positional `<node> [at] [insecure]`, so `insecure` is the **third**:
  - `mise exec -- just talos-upgrade-node <hostname> '' true`
  - (or `mise exec -- just talos-upgrade-node <hostname> <current-ip> true`)
