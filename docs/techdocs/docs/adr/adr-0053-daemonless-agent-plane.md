---
status: accepted
date: 2026-10-04
---

# The agent plane is daemonless: dind stays false everywhere, gates run in CI

Technical Story: [RFC: CI isolation on Talos](../rfc/rfc-ci-isolation-talos.md); cross-estate
alignment with code14 staging-cluster ADR-0038 (their twin of this record).

## Context and Problem Statement

The ploeg agent plane carried a privileged Docker-in-Docker sidecar per worker so agents could
run language gates in CI's own images. Three artifacts held that door open: the chart-default
`executor.harness.dind: true` (which bronze's builder role and the silver team inherited
*silently* — neither had a `harness:` block in the HelmRelease, which is exactly why the
`exception-ploeg-worker-privileged-cel` waiver named those two ScaledJobs), the ploeg
namespace's PSA carve-out (`enforce: privileged`), and the Kyverno waiver itself.

The cost of that shape is no longer hypothetical:

* [rfc-ci-isolation-talos](../rfc/rfc-ci-isolation-talos.md) documents two node-down
  incidents from the same mechanism — KEP-2254 gives privileged pods the **host** cgroup
  namespace by design, so DinD-nested containers land outside `kubepods`, invisible to
  kubelet eviction and the Talos OOMController. Sidero has said outright that privileged
  dind on Talos is unsupported.
* code14's staging cluster (the other estate running ploeg) refused the shape at admission
  from day one (their RFC-0013: `claude-code` harness, `dind: false`, "no privileged
  container, no exception, smaller blast radius").
* The estates were divergent on a security-load-bearing design for no capability reason:
  every webgrip team that *explicitly* declared a harness already ran `dind: false`.

The owner decided (2026-08-28) that both estates adopt one design, choosing "daemonless"
from three candidate paths (see options below).

## Decision Drivers

* One design across webgrip homelab and code14 staging — identical policy floor, identical
  worker pod shape, so a change proves itself in one estate and ports as a diff.
* Remove the incident class, not contain it: no privileged container should exist in the
  agent plane at all.
* Gates must still run in CI's exact images — the property the DinD design existed for —
  just not inside the worker pod.
* Re-enabling a daemon must require a deliberate MR, never a values default nobody wrote
  down (the bronze-builder/silver inheritance is the anti-pattern this retires).

## Considered Options

* **Daemonless** — `dind: false` estate-wide; gates run in CI on the agent's MR; the growth
  path is a gate-as-Job broker (a ploeg-dispatched Job in a restricted namespace running
  "image Y, command C, ref R").
* **Kata-walled DinD** — keep the sidecar, wrap the pod in the already-proven `kata`
  RuntimeClass so privileged is confined to a guest kernel.
* **Rootless dind + user namespaces** (`hostUsers: false`) — the upstream-sanctioned
  endgame; blocked today by moby#52268 (non-root nested netns).

## Decision Outcome

Chosen option: **"Daemonless"**, because it is secure by construction rather than by
containment — there is no privileged surface left to wall off — it needs zero node
prerequisites (so it is the only option that is *identical* on any conformant cluster,
including a future cloud one), and it matches where both estates were already converging.

Implemented in this repo and its siblings, one coherent change:

* `kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml` — executor-level
  `harness: {name: openhands, dind: false}` becomes the estate default, overriding the
  chart's `dind: true`; the dormant `dindImage`/`dindResources` values are deleted.
* `kubernetes/apps/ploeg/namespace.yaml` — PSA `enforce` returns from `privileged` to
  `baseline`; the namespace sits under the same floor as every other app namespace and the
  same floor as code14's ploeg namespace.
* `kubernetes/apps/kyverno/exceptions/app/exception-pod-security-baseline-cel.yaml` — the
  `exception-ploeg-worker-privileged-cel` waiver is deleted. Its match-arm lore (the
  2026-07-30 inspection-based cleanup that broke every DinD dispatch) is honored, not
  repeated: this removal ships *together with* the `dind: false` default that makes the
  waiver match nothing, in one MR.
* `webgrip/infrastructure` `ops/docker/agent-runner` — the docker CLI and the entrypoint's
  daemon-wait are removed from the image; its design header now states the daemonless
  contract.

Gates that need containers run in CI, in CI's pinned images, on the MR the agent opens.
If in-run gate execution is ever needed again, the sanctioned shape is the gate-as-Job
broker (dispatched by ploeg into a restricted namespace) — or, for interactive docker as a
hard requirement, the Kata path via a new ADR; never a bare privileged sidecar. Rootless +
`hostUsers: false` remains the destination; re-evaluation triggers live in
[rfc-ci-isolation-talos](../rfc/rfc-ci-isolation-talos.md).

### Consequences

* Good, because no pod in the agent plane is privileged, on either estate; the KEP-2254
  cgroup-invisibility class that took a node down twice cannot occur here.
* Good, because the two estates now share one worker pod shape, one policy floor, and one
  entrypoint contract — a fix or audit in one is a diff away from the other.
* Good, because re-enabling DinD now requires an MR that must bring back three named things
  (values, waiver, PSA label) — it cannot happen by inheriting a chart default.
* Bad, because bronze-builder and silver lose in-run gate execution: the agent-runner image
  bakes no language toolchains, so gate commands run by the agent in-pod will fail until
  the per-repo delivery contracts (erfbeeld, ploeg — ADR-0050) are updated to "push and let
  CI gate the MR". That follow-up is real work and is tracked on the board.
* Bad, because the deleted waiver also carried `workload-hardening-audit` for the two named
  ScaledJobs; audit-tier findings for the worker pods may reappear in the PolicyReport.
  That is signal, not noise — harden the pods instead of re-waiving.

### Confirmation

* `kubectl get ns ploeg -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}'`
  returns `baseline`.
* `kubectl get policyexceptions -n security | grep ploeg` shows only
  `exception-ploeg-worker-advanced-cel` (capabilities audit) — no privileged waiver.
* During a dispatched run:
  `kubectl get pods -n ploeg -o json | jq '[.items[].spec.containers[]?.securityContext.privileged // false] | any'`
  returns `false`, and worker pods have one container (no dind sidecar).
* `grep -c 'dind: true' kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml` returns 0 while
  the executor-level `dind: false` default is present.

## Pros and Cons of the Options

### Daemonless

* Good, because the capability is removed, not sandboxed — nothing to escape.
* Good, because it is portable to any conformant cluster with zero node prerequisites.
* Neutral, because the gate-as-Job broker (the capability-preserving growth path) is not
  built yet; until then gates run only on the MR pipeline.
* Bad, because agents cannot self-verify with project toolchains mid-run.

### Kata-walled DinD

* Good, because the substrate is already proven here (kata 3.32.0 on all three workers,
  standing smoke Job, real guest kernel verified) and it closes both the escape risk and
  the cgroup hole.
* Bad, because ~160Mi/250m overhead per pod, the warm docker store needs a block volume,
  a (defensible) Kyverno exception must still exist — and code14 staging would first have
  to verify KVM on its workers, so estate-identity is conditional, not guaranteed.

### Rootless dind + user namespaces

* Good, because it deletes the incident class by construction with no VM overhead and no
  exception — the sanctioned upstream endgame.
* Bad, because moby#52268 breaks non-root nested netns today; not adoptable this year.

## More Information

* Technical story: [rfc-ci-isolation-talos](../rfc/rfc-ci-isolation-talos.md) (the incident
  record and options ranking this decision draws on).
* 2026-08-28 — decided by the owner and implemented across
  `homelab-cluster` (namespace, HelmRelease, Kyverno waiver) and
  `webgrip/infrastructure` (agent-runner image); code14 twin recorded as staging-cluster
  ADR-0038.
* Refines [ADR-0048](adr-0048-dark-factory-execution-layer.md): the execution layer stands,
  its privileged-DinD plane aspect is retired.
* Relates to [ADR-0050](adr-0050-per-repo-delivery-contract.md) (delivery contracts must
  move gate execution to CI) and [ADR-0051](adr-0051-harness-plurality-acp.md) (harness
  plurality is unaffected — `dind: false` is harness-neutral).
* 2026-09-28/29 — copper, then bronze, moved to the agent-sandbox executor under the `kata` RuntimeClass, still daemonless (bd6c30ea, b75cab92); the worker pod shape now differs by team
* 2026-10-04 — Ploeg moved to ploeg-hq 0.2.0-rc.2, whose chart has no homelab defaults, so `executor.dindImage` was written back into the HelmRelease (a9683e7c); inert while every team runs `dind: false` (logged in audit 2026-10-04)
