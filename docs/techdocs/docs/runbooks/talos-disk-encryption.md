# Talos disk encryption, one node at a time

This runbook encrypts each node's STATE and EPHEMERAL with LUKS2, as [ADR-0080](../adr/adr-0080-node-disks-are-encrypted-with-luks2.md) decides. Talos cannot encrypt a partition that holds data. Each node is wiped and re-joins the cluster with the encrypted configuration. EPHEMERAL holds `/var`: on the workers that includes `/var/lib/longhorn`, on the control planes etcd's data.

## Before the first node

1. **Check each worker's firmware for a TPM.** Intel PTT is usually off by default on desktop boards. If `talosctl -n <ip> ls /sys/class/tpm` shows `tpm0` after turning it on, use `controlplane-tpm.yaml` for that worker instead of `worker-nodeid.yaml`.
2. **Take an etcd snapshot** and keep it outside the repository: `mise exec -- talosctl -n 10.0.0.20 etcd snapshot <file>`.
3. **Check Longhorn.** Every volume must be `healthy`:

    ```sh
    kubectl -n longhorn-system get volumes.longhorn.io -o custom-columns=N:.metadata.name,R:.spec.numberOfReplicas,H:.status.robustness
    ```

## Node order

| Order | Node | Watch for |
| --- | --- | --- |
| 1 | `fringe-workstation` (10.0.0.30) | No Longhorn replicas; a good first node |
| 2 | `worker-2` (10.0.0.32) | Longhorn replicas; wait for every volume `healthy` afterwards |
| 3 | `worker-1` (10.0.0.31) | The **only** replica of `garage/data-garage-0` (100 GiB, 94 GB used on 2026-10-24), `garage/meta-garage-0` and `ai/tei-embeddings-models`; see the next section |
| 4–6 | `soyo-1`, `soyo-2`, `soyo-3` | etcd; the current leader (`talosctl etcd status`) goes last |

### Single-replica volumes on worker-1

Wiping worker-1's EPHEMERAL deletes every replica stored there. Before worker-1:

1. Raise those three volumes to two replicas, so Longhorn copies them to worker-2, which had 1.3 TB available on 2026-10-24:

    ```sh
    for v in pvc-3b5bfd70-a65e-4405-a6f6-949f60b97ac9 pvc-ec70a81e-ee19-487c-8f19-b3a19dd68f6f pvc-184b8eae-8034-4000-878c-7bf8be9a929a; do
      kubectl -n longhorn-system patch volumes.longhorn.io "$v" --type merge -p '{"spec":{"numberOfReplicas":2}}'
    done
    ```

2. Wait until all three report `healthy` with two replicas.
3. Encrypt worker-1 as below.
4. After worker-1 is back and every volume is `healthy`, set the three back to one replica if the extra disk use matters.

Check the volume names against `kubectl get pvc -n garage` and `-n ai` first; they change if a claim is recreated.

## Encrypt one node

1. In `talos/nodes.yaml`, add the node's encryption patch as the last entry of its `patches:`:
   * `patches/encryption/controlplane-tpm.yaml` for `soyo-*`;
   * `patches/encryption/worker-nodeid.yaml` for the workers.
2. Render: `just talos-generate-config`. Check that `talos/clusterconfig/kubernetes-<host>.yaml` contains two `kind: VolumeConfig` documents.
3. Wipe both volumes. A control plane leaves etcd gracefully first:

    ```sh
    mise exec -- talosctl -n <ip> reset --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --reboot
    ```

4. The node comes back in maintenance mode, because its configuration was on STATE. Apply the rendered configuration:

    ```sh
    mise exec -- talosctl -n <ip> apply-config --insecure --file talos/clusterconfig/kubernetes-<host>.yaml
    ```

5. Check the result:
   * `mise exec -- talosctl -n <ip> get volumestatus STATE -o yaml` shows `encryptionProvider: luks2`, and so does `EPHEMERAL`.
   * `kubectl get node <host>` is `Ready`.
   * For a control plane, `talosctl etcd members` lists it again.
6. For a worker: wait until Longhorn shows every volume `healthy`, and check the rebuild wedge ([longhorn-rebuild-wedge](longhorn-rebuild-wedge.md)).
7. Commit the `nodes.yaml` change for that node, then go on to the next node.

## When it goes wrong

* **A node stays in maintenance mode after the wipe.** Re-run step 4 with the same file.
* **A control plane does not rejoin etcd.** Remove its stale member from a healthy control plane with `talosctl etcd remove-member <id>`, then reset that node again. Never wipe a second control plane while one is out.
* **A TPM-sealed node no longer unlocks after a firmware change.** Its PCR 7 moved. Wipe it and apply its configuration again; the TPM seals a new key.
