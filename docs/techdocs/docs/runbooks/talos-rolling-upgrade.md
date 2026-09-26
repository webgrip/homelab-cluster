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

`talosctl` is also the config generator ([ADR-0062](../adr/adr-0062-talos-configs-from-plain-talosctl.md)),
so bump the tool pin **with or before** `talosVersion`; `just talos-generate-config` renders the
installer tag from `talosVersion` for each node's `schematic` in `talos/nodes.yaml`. The machine
config shape is pinned separately by `configContract` in `talenv.yaml` (currently `v1.13`). A
Talos upgrade leaves it alone. Raising it to `v1.14` means moving our `cluster.apiServer` /
`machine.*` patches onto the 1.14 `Kube*Config` documents, which is its own change with its own
dry-run diff.

Check a render before upgrading: `mise exec -- just talos-generate-config`, then
`talosctl validate --mode metal --config talos/clusterconfig/kubernetes-<node>.yaml`, and a
`talosctl apply-config --dry-run` against the node.

## Preflight checks

- `mise exec -- kubectl get nodes -o wide`
- `mise exec -- talosctl health --endpoints <any-node-ip> --nodes <same-node-ip>`
- etcd members via a single node:
  - `mise exec -- talosctl etcd members --endpoints <any-node-ip> --nodes <same-node-ip>`

## Upgrade one node

The recipe drains through talosctl, which evicts and retries, reboots, and uncordons. That drain
stalls on any pod whose PodDisruptionBudget allows zero disruptions, and the node then never
reboots onto the new image. List them first:

```sh
mise exec -- kubectl get pdb -A -o json | jq -r '.items[] | select(.status.disruptionsAllowed==0) | "\(.metadata.namespace)/\(.metadata.name)"'
```

Longhorn `instance-manager` budgets are expected and release by themselves once the node's volumes
detach. Single-instance CNPG primaries never release. On 2026-09-25/26 the control planes had none
and ran the recipe alone; every worker had several and needed the pre-drain below.

### Workers: pre-drain

1. **Probe the CNPG relabel.** A recreated primary only gets its `-rw` endpoint once the operator's
   label PATCH passes admission. On 2026-09-25 Kyverno denied it and took Forgejo, Harbor and Flux
   down ([incident](../incidents/2026-09-25-cnpg-relabel-denied-gitops-deadlock.md)). For each CNPG pod on the node, the probe must be
   admitted (a server dry run persists nothing):
   `mise exec -- kubectl -n <ns> label pod <pod> probe.webgrip.io/admission-test=1 --dry-run=server`
2. **Stop single-replica volumes whose only replica is on the node.** Garage (`longhorn-single`)
   is the one today. Check where the replica lives, not where the pod runs, because the pod can
   attach remotely:
   `mise exec -- kubectl -n longhorn-system get replicas.longhorn.io -o json | jq -r '.items[] | select(.spec.volumeName=="<pv>") | .spec.nodeID'`.
   If it is the node, run `kubectl -n garage scale statefulset garage --replicas=0` and let Flux
   restore it afterwards (`flux reconcile ks garage -n garage`).
3. **Drain everything except the instance-manager.** Eviction is disabled, so budgets are bypassed,
   and the instance-manager leaves last through the recipe's own drain:

   ```sh
   mise exec -- kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --disable-eviction \
     --pod-selector='longhorn.io/component!=instance-manager' --timeout=300s
   ```

   It prints `node/<node> cordoned` first. If it does not, it never reached the cluster. A timeout
   while Postgres finishes its clean shutdown is harmless. Wait until no workload pods remain on the
   node and no Longhorn volume reports it as `currentNodeID`, then run the recipe.

Expect with one worker out: the other two cannot hold its memory requests, so some pods, including
CNPG primaries, stay `Pending` until it returns. Forgejo's `configure-gitea` init container syncs
its Authentik OIDC provider and fails while Authentik is down, so an Authentik database stuck
`Pending` also takes down Forgejo and, with it, Flux. Both recover on their own once the node is back.

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

At `talosVersion: v1.13.10` the bundled etcd is `v3.6.14` (read with `talosctl etcd status`).

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
