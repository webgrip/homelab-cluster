---
status: accepted
date: 2026-10-24
decision-makers: Ryan Grippeling
---

# gVisor runs beside Kata on the workers, and each agent workload takes the runtime that fits it

## Context and Problem Statement

[ADR-0070](adr-0070-agent-code-runs-restricted-and-in-its-own-kernel.md) puts Unfold's workspaces and Ploeg's sandbox teams under Kata, so agent code runs in a guest kernel. Kata is the only sandbox runtime on the workers. Every sandboxed pod therefore pays a VM's overhead (160Mi and 100m in the RuntimeClass) and is invisible to Tetragon ([ADR-0072](adr-0072-tetragon-watches-agent-pods.md)), including short, light pods such as the delivery verifier's checks.

On 2026-10-24 Unfold's system [ADR-0045](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/docs/adr/adr-0045-agent-code-runs-under-kata-or-gvisor-chosen-by-what-the-node-and-the-work-need.md) was accepted. It makes Kata (Cloud Hypervisor) and gVisor equal sandbox runtimes, chosen by node and work, and ships a cluster kit for self-hosters. Should the homelab, as Unfold's staging and first install, run both?

## Decision Drivers

* The homelab should run what Unfold tells self-hosters to run, so the guide is proven here first.
* Light agent pods should not pay a VM's memory on nodes that are already memory-tight.
* gVisor needs no KVM, so the rented cloud cluster's VM workers ([Unfold ADR-0040](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/docs/adr/adr-0040-unfold-production-runs-on-a-rented-eu-talos-cluster-and-the-homelab-is-staging.md)) can use what is qualified here.
* A runtime is added only to nodes where its extension is verified, the rule ADR-0070's Kata rollout learned.

## Considered Options

* Add gVisor to the worker schematic next to Kata, with its own RuntimeClass, capability label and smoke Job
* Keep Kata only
* Replace Kata with gVisor

## Decision Outcome

Chosen option: **"Add gVisor next to Kata"**, because it costs one schematic change and proves on our own hardware the path Unfold's guide gives everyone else.

* **Schematic.** Workers move from `d1200926df53…` to `0410def57221e1a28bef0ad20b8e1fb3190796b7a8402ccea171bb3ecbaec22f`: binfmt-misc, gvisor, iscsi-tools, util-linux-tools and kata-containers. On Talos v1.13.10 the factory carries gvisor 20260810.0 and kata-containers 3.32.0.
* **Prerequisite.** `user.max_user_namespaces` is already set for every node (`talos/patches/global/machine-sysctls.yaml`).
* **RuntimeClass.** `gvisor`, handler `runsc`, overhead 64Mi and 50m, scheduled on `runtime.webgrip.io/gvisor: "true"` (`kubernetes/apps/kube-system/runtime-classes/app/gvisor.runtimeclass.yaml`). A standing `gvisor-smoke` Job sits next to `kata-smoke`.
* **Labels.** `runtime.webgrip.io/gvisor` sits in each worker's patch and is applied only after `talosctl get extensions` lists gvisor on that node.
* **Who moves.** Nothing moves at merge. Kata stays the runtime for Unfold workspaces and Ploeg's writing teams. Candidates for gVisor, each after the Unfold kit's bench on a worker:
  * Unfold's delivery verifier (`delivery.verifier.runtimeClassName`);
  * reading-only Ploeg Roles.

### Consequences

* Good, because the homelab proves gVisor on Talos before a self-hoster or the cloud cluster depends on it.
* Good, because light agent pods can drop from 160Mi to 64Mi of runtime overhead.
* Good, because gVisor pods can feed Falco-compatible syscall events through gVisor's Runtime Monitoring, where Kata pods show nothing.
* Bad, because each worker needs a Talos upgrade (one reboot), and two runtimes mean two extensions and advisory feeds to follow.
* Bad, because `user.max_user_namespaces` stays above Talos's hardened default; that was already true for user-namespace pods.

### Confirmation

* `talosctl -n <worker> get extensions` lists `gvisor` on each labelled worker.
* `kubectl -n kube-system logs job/gvisor-smoke` prints a kernel ending in `-gvisor` and `Starting gVisor...`.
* `kubectl get runtimeclass` lists `kata` and `gvisor`.

## Pros and Cons of the Options

### Keep Kata only

* Good, because there is one runtime less.
* Bad, because the guide Unfold publishes would be unproven on the estate that stages Unfold.

### Replace Kata with gVisor

* Good, because pods start faster and cost less.
* Bad, because workspaces that build containers or need kernel features gVisor lacks would break, and on bare metal the VM boundary is available and stronger against a kernel escape.

## More Information

* Rollout: [gVisor runtime runbook](../runbooks/gvisor-runtime.md).
* Unfold's guide and kit: [Run agent code in a sandbox runtime](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/docs/how-to/run-agent-code-in-a-sandbox-runtime.md), `apps/unfold/ops/cluster/sandbox-runtimes`.
* Ticket: [VIK-2408](https://vikunja.webgrip.dev/tasks/2408).
* Refines ADR-0070.
* 2026-10-24 — Accepted by Ryan Grippeling.
