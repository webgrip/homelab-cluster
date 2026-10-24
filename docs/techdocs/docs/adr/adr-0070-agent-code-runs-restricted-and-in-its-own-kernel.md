---
status: accepted
date: 2026-10-24
decision-makers: Ryan Grippeling
---

# Agent code runs under the restricted Pod Security Standard and in a kernel of its own

## Context and Problem Statement

Two kinds of pod run code an AI agent wrote or fetched: Ploeg's worker pods (namespace `ploeg`,
including the Kata sandboxes its SandboxTemplates create) and Unfold's agent workspaces (namespace
`unfold-workspaces`).

The security review of 2026-10-18 found that both stopped short of what the cluster can enforce:

* The `ploeg` namespace enforced only the `baseline` Pod Security Standard; `restricted` was set to
  warn and audit. The reason was the harness container in every worker pod: it had no
  `securityContext`, so it ran as the image's user, root for the shared agent image, with privilege
  escalation allowed and the runtime's default capabilities.
* Unfold's workspaces were hardened (non-root, read-only root filesystem, no capabilities, seccomp)
  but ran on the node's default runtime, sharing the node's kernel. Only Unfold's `sandbox`
  provisioner could use Kata, and that provisioner is not qualified on this cluster.

What should agent-executing pods be held to?

## Decision Drivers

* Agent code is the least trusted code in the cluster, so it gets the strongest boundary the cluster
  supports.
* A rule a namespace only warns about protects nothing.
* Kata already runs here: the Unfold delivery verifier and Ploeg's sandboxes use it.

## Considered Options

* Enforce `restricted` in `ploeg` and run Unfold's pod-provisioner workspaces under Kata
* Enforce `restricted` only, leave workspaces on the default runtime
* Move Unfold to its `sandbox` provisioner on Kata

## Decision Outcome

Chosen option: **enforce `restricted` in `ploeg` and run Unfold's pod-provisioner workspaces under
Kata**, because it closes both gaps with changes that already ship and are tested.

1. Ploeg's chart gives the harness container a restricted context by default (Ploeg ADR-0120,
   release 0.2.0-rc.31): uid and gid 1000, no privilege escalation, all capabilities dropped,
   `RuntimeDefault` seccomp. The same template feeds the KEDA workers and the SandboxTemplates.
2. Namespace `ploeg` enforces `restricted`. `unfold-workspaces` and `unfold-verifier` already did.
3. Unfold's pod provisioner runs the agent and candidate-export pods under the `kata` RuntimeClass
   (Unfold's `workspacePodRuntimeClassName`, from release 0.4.0-rc.91; the homelab runs 0.4.0-rc.110), so each workspace is a
   lightweight VM with its own kernel.
4. The `sandbox` provisioner stays unused until it is qualified here; this decision does not depend
   on it.

### Consequences

* Good, because a pod in `ploeg` that asks for root, escalation or extra capabilities is refused at
  admission instead of logged.
* Good, because an agent that escapes its workspace container lands in a VM, not on the node.
* Bad, because a harness image that needs root at run time fails until its image or the chart's
  `executor.workerSecurityContext` changes; setting that value to `{}` also needs this namespace
  back on `baseline`.
* Bad, because each workspace pays the Kata VM's memory and start-up cost.

### Confirmation

* `kubectl label --dry-run=server --overwrite ns ploeg pod-security.kubernetes.io/enforce=restricted`
  printed no warning for the pods running on 2026-10-19 or on 2026-10-24, and a server dry run of every worker and
  sandbox template from the deployed chart, wrapped as Jobs, printed no `restricted` violation.
* After merge: `kubectl get ns ploeg -o jsonpath='{.metadata.labels}'` shows `enforce: restricted`,
  a new Run's worker pod starts, and a new Unfold session's pod in `unfold-workspaces` shows
  `runtimeClassName: kata` and reaches Running.

## Pros and Cons of the Options

### Enforce `restricted` only, leave workspaces on the default runtime

* Good, because workspaces start faster and cost less memory.
* Bad, because agent code keeps sharing the node's kernel.

### Move Unfold to its `sandbox` provisioner on Kata

* Good, because warm pools would hide the Kata start-up cost.
* Bad, because the provisioner and its agent-sandbox wiring are not qualified on this cluster.

## More Information

* Technical story: [RFC: Agent plane hardening](../rfc/rfc-agent-plane-hardening.md).
* Ploeg ADR-0120 (restricted harness container) and Unfold's pod `runtimeClassName` support
  (`kubernetes.runtimeClassName`) are the upstream halves.
* Re-evaluate when a supported harness needs root, or when the `sandbox` provisioner is qualified.
* 2026-10-19 — accepted by Ryan Grippeling.
* 2026-10-24 — merged onto main, after Ploeg moved into the Unfold release.
* 2026-10-24 — Refined by [ADR-0079](adr-0079-gvisor-runs-beside-kata-on-the-workers.md): gVisor joins Kata on the workers; Kata stays the runtime for workspaces and writers.
