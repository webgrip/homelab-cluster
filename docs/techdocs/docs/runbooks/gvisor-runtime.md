# gVisor next to Kata on the workers

This runbook rolls out [ADR-0079](../adr/adr-0079-gvisor-runs-beside-kata-on-the-workers.md): the gVisor extension on every worker, its `gvisor` RuntimeClass and the standing smoke Job. Talos node operations in general are in the `talos` skill and [Talos rolling upgrade](talos-rolling-upgrade.md).

## What changes

| Piece | Where |
| --- | --- |
| Worker schematic `0410def57221…` (adds `siderolabs/gvisor`) | `talos/nodes.yaml` |
| Capability label `runtime.webgrip.io/gvisor: "true"` | `talos/patches/worker/*.yaml` |
| RuntimeClass `gvisor`, handler `runsc` | `kubernetes/apps/kube-system/runtime-classes/app/gvisor.runtimeclass.yaml` |
| Smoke Job `gvisor-smoke` | the same directory |

Merging changes only the Kubernetes objects. The smoke Job stays `Pending` until a node carries the label, which is expected.

## Roll out

Do the workers in the [usual order](talos-rolling-upgrade.md#node-order): `fringe-workstation`, then `worker-2`, then `worker-1`. Start the next node only when Longhorn shows every volume `healthy` again.

1. Render fresh configurations: `just talos-generate-config`. Stale files in `talos/clusterconfig/` carry the old schematic.
2. Upgrade the node to the new installer (one reboot):

    ```sh
    mise exec -- talosctl -n <ip> upgrade --image factory.talos.dev/installer/0410def57221e1a28bef0ad20b8e1fb3190796b7a8402ccea171bb3ecbaec22f:v1.13.10
    ```

3. Check the extension, not the exit code: `mise exec -- talosctl -n <ip> get extensions` lists `gvisor` and still lists `kata-containers`.
4. Apply the rendered configuration, which carries the label: `mise exec -- talosctl -n <ip> apply-config --file talos/clusterconfig/kubernetes-<host>.yaml`.
5. Check the label: `kubectl get node <host> -L runtime.webgrip.io/gvisor` shows `true`.

After the first node, check the smoke Job: `kubectl -n kube-system logs job/gvisor-smoke` prints a kernel ending in `-gvisor` and `Starting gVisor...`. Check that Kata still works: delete `job/kata-smoke` and let Flux recreate it.

## Measure before moving a workload

Run the Unfold kit's bench (`apps/unfold/ops/cluster/sandbox-runtimes/bench`) in a namespace of its own that may reach GitHub and the npm registry. Run its runc, Kata and gVisor Jobs one at a time on the same worker, and record the JSON lines in the Unfold research record of 2026-10-24. Move a workload to `gvisor` only with those numbers in hand.

## Roll back

Remove the label from the node's patch and apply it; gVisor pods then stay `Pending` and nothing else changes. To remove the extension, upgrade the node back to schematic `d1200926df53a3d0c6a8bed8575e9eb212152a2decf792d9dfc7bea484f36be8`.
