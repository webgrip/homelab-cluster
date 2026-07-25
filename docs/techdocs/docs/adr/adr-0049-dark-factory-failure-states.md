# ADR-0049: Dark-factory failure-state management under permanent scarcity

- **Status:** accepted
- **Date:** 2026-07-25
- **Deciders:** Ryan Grippeling
- **Related:** ADR-0047 (agent runtime), ADR-0048 (execution layer), Vikunja VIK-585/588/589/590/594/595/596–599

## Glossary (read this first)

| Term | Meaning |
|---|---|
| **Run** | One worker Job executing one ticket end to end (clone → agent → PR → outcome). |
| **Lease** | The dispatch plane's crash-safe claim on a work item; renewed by the running worker, expires mechanically if the worker dies. |
| **Sweeper** | The ploegd loop that expires dead leases and re-queues or stales the item. |
| **Burstable cgroup** | Where Kubernetes puts pods whose resource `requests < limits`. Talos's OOM controller kills *only* in this tree. |
| **Guaranteed QoS** | `requests == limits` for every container. The pod leaves the burstable tree and cannot be killed by the Talos OOM controller; the scheduler will not place it unless the memory truly exists. |
| **Attempt budget** | `work_items.attempts`, capped at 3; at the cap the item goes `stale` and stops dispatching. |

## Context: what actually happened (2026-07-25)

The cluster ran out of memory headroom. Talos v1.13's userspace **`runtime.OOMController`** responded to PSI pressure by SIGKILLing whole pod cgroups under `/kubepods/burstable/` — invisibly to Kubernetes (exit 137, reason `Error`, **no** `OOMKilled` mark, no eviction event). It killed two factory runs mid-flight (runs 9 and 10 on VIK-585), the log shipper, and cilium — repeatedly. Each killed run leaked its per-run LiteLLM key (traps and defers cannot survive SIGKILL), burned one attempt from the ticket's budget, and one run's Job+pod were garbage-collected by KEDA before forensics could map the cgroup. Separately, the second worker node was CPU-full, so the retry sat Pending. **No component misbehaved — the system as designed simply converts node pressure into lost work, leaked money, and burned tickets.**

Extra RAM is not available. Scarcity is the operating condition, not an incident.

## Decision: five principles, each with a concrete mechanism

### P1 — Never start work you can't finish (admission control)

Factory pods (worker + DinD sidecar) get **Guaranteed QoS** (VIK-595 S1). Under scarcity the scheduler then *queues* runs instead of starting them into a death zone. This is safe **because the worker claims at startup** (ADR-0048): a Pending pod holds no lease, burns no attempt, spends no money. Pending-with-reason is the correct degraded mode. A starvation alert (VIK-598) tells a human when the factory has been queued for too long — the human decides to shed load or wait, but nothing is lost meanwhile.

### P2 — Infrastructure failures never burn the ticket's attempt budget (VIK-596)

Today every death increments `attempts`; three infra kills stale a perfectly good ticket. The sweeper can already distinguish the cases:

| Signal | Classification | Effect |
|---|---|---|
| Worker **reported** an outcome (`failed`/`stuck`) | *Agent* failure | counts an attempt (the ticket or the agent is the problem) |
| Lease expired, **no outcome reported** | *Infra* failure | re-queue **without** attempt increment, with **backoff** (1 m → 5 m → 15 m → 60 m cap) so a sick node isn't hammered every 30 s |

An `infra_failures` counter (with its own generous cap + alert) prevents an infinite loop while keeping the semantics honest: *the ticket didn't fail — the floor collapsed*. Post-VIK-588, even a stale item revives with a fresh budget on human re-assign, so stale is an inconvenience, not a dead end.

### P3 — Money is contained on every path (defense in depth)

1. Worker `defer` revoke (VIK-585) — instant, covers in-process failures.
2. **Sweeper revoke** (VIK-594) — the dispatch plane revokes the key of any run it declares dead; worst-case leak window = one lease TTL (≤ 15 m). Plus a boot-time orphan sweep.
3. Key TTL (4 h) — the final net.
4. Per-run budget, per-provider daily caps, and a daily factory-spend alert (VIK-598).

The `slo-ploeg-run-key-leak` alert stays — demoted from "page a human to clean up" to "the self-heal failed twice; something is genuinely wrong."

### P4 — Evidence must outlive the pod (VIK-597)

KEDA cleanup deleted run 10's Job+pod before the kill could be attributed. Forensics move to places that survive:

- The worker's **first log line and first checkpoint carry node name + pod UID** (logs persist in VictoriaLogs; checkpoints persist in Postgres) — a dead run can always be mapped to a Talos dmesg cgroup line afterwards.
- `failedJobsHistoryLimit` raised so failed Jobs linger for inspection.
- A run's failure gets a **reason taxonomy** (`infra_node` / `infra_llm` / `agent_error` / `budget` / `lease_lost`) recorded by the sweeper/worker — dashboards then show *why* runs die, not just that they died.

### P5 — Detect pressure before the controller kills (VIK-595 S2, VIK-598)

- PSI early-warning alert (`node_pressure_memory_*`) — fires *before* the OOM controller does, because the controller's own trigger is PSI.
- Invisible-kill detector: exit-137-with-reason-Error spikes per node (the OOMController signature Kubernetes won't name).
- Run-health panel on the dark-factory dashboards: kills by reason, attempt burn, Pending age, node PSI.
- A periodic **chaos drill** (VIK-599): a forced-fail ticket walks the whole failure path (kill → sweep → revoke → requeue → alert) and proves the machinery still works — mutation testing for resilience itself.

## What we explicitly do NOT do

- **No priority-class arms race.** `system-node-critical` demonstrably does not stop the Talos OOM controller (alloy was killed *with* it). QoS class is the shield; priority only orders kubelet eviction.
- **No auto-shedding of other workloads.** Preemption/eviction of neighbors to feed the factory is a human decision (owner-only), never automated.
- **No retry-forever.** Backoff + capped infra counter + starvation alert; a human always ends up in the loop when the cluster is genuinely too small.

## Symptom → cause quick table (for 3 a.m.)

| Symptom | Likely cause | First check |
|---|---|---|
| Run died, exit 137, no `OOMKilled` | Talos OOMController (PSI) | `talosctl -n <node-ip> dmesg \| grep "OOM controller"` |
| Worker pod Pending > 15 m | No node fits Guaranteed request | starvation alert; `kubectl describe pod` scheduling message |
| Ticket went `stale` | 3 *agent* failures (post-VIK-596: infra kills don't count) | run reasons in the Run Explorer dashboard; re-assign revives with fresh budget |
| Leak alert firing > 30 m | Sweeper revoke failing too | ploegd logs `revoke` lines; LiteLLM admin reachable? |
| Same line ×N in log panels | Log-shipper restarts (often OOMController kills) | see ADR notes in alloy memory / VIK-595 S3 |

## Consequences

Runs queue honestly instead of half-dying; tickets survive infrastructure weather; every euro a run can spend is bounded by three independent layers; and when the factory is starved, exactly one signal says so and a human makes the only decision automation must not make. The trade-off is throughput under pressure — accepted, because a homelab's scarcity is structural and correctness beats speed here.
