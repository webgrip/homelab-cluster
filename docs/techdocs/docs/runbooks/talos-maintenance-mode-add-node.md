# Runbook: Talos add node (maintenance mode)

This runbook is a short index entry for adding a new node that boots into Talos maintenance mode.

- Full tutorial: [docs/techdocs/docs/talos-add-workstation-node.md](../general/talos-add-workstation-node.md)

If you are seeing `x509: certificate signed by unknown authority`, the key rule is that maintenance mode requires `--insecure` on the **subcommand** and usually `--endpoints <ip>` to talk directly to the node.

## After renumbering: purge META key 0x0a

Talos persists the maintenance-mode/interim network config in **META key
`0x0a`**, and it survives every reboot and config apply. If the node is later
renumbered (worker-2: interim `.70` → final `.32`, 2026-08), the stale META
address is re-injected at each boot as an `AddressSpec` on the kernel link
name, fighting the machine config's spec on the link alias for the same NIC.
Symptom: `AddressSpecController` remove/assign loops in dmesg, `NodeAddress`/
`KubeletSpec` re-rendering continuously, and **machined restarting the kubelet
about once a minute** (SIGTERM, not health failure) — surfacing as `StartError:
context canceled` pods, `object … not registered` FailedMounts, flapping
probes, and missing node metrics (incident 2026-08-27/28, worker-2).

Check and fix (fix needs a reboot to take effect):

```bash
talosctl -n <ip> meta read 0x0a        # stale addresses: block = the trap
talosctl -n <ip> meta delete 0x0a
# cordon → reboot → uncordon
```
