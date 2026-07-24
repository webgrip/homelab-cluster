---
title: "A dark factory on a homelab cluster: Kanban tickets in, reviewed PRs out"
published: false
description: "Autonomous coding agents on self-hosted Kubernetes: KEDA-scaled runner pool, per-run budget-capped LLM keys, and a reviewer bot that can't push. Real numbers: $0.046 per PR."
tags: kubernetes, selfhosted, ai, gitops
canonical_url: "TODO-substack-url-after-publish"
---

*This is the condensed architecture cut of a longer write-up ([canonical on Substack — set
canonical_url above before publishing]). dev.to gets the infrastructure skeleton; the full
post has the war stories.*

This morning my Kubernetes cluster scheduled an AI agent the same way it schedules a CI job:
KEDA saw a queued task and scaled a pod from zero. The agent worked a Kanban ticket, opened a
PR (205 lines of unit tests), and a different bot rejected it for skipping the TypeScript
gate. No human in the loop until the merge button. Total inference cost: **$0.046**, every
cent of it queryable in a ledger.

The claim worth your scroll: **scheduling agents is a solved problem** (a stock autoscaler
does it); the real problems are spend, identity, and trust. Here's the architecture that
handles those three on a 5-node homelab cluster, every component open source and self-hosted.

## The pipeline

Vikunja ticket labeled `team/bronze` → workflow dispatch → KEDA scales a runner pod from
zero → OpenHands (headless) works the ticket → PR opened by `agent-builder` → review lane
runs as `agent-reviewer` → human merges.

## The five load-bearing decisions

**1. builder ≠ judge, enforced by the forge.** Builder and reviewer are separate bot
accounts. The reviewer has `read:repository` + `write:issue` only: it cannot push, merge, or
rewrite what it judges. A forge won't let an account approve its own PR, so the safety
property is structural, not behavioral.

**2. Per-run budget-capped LLM keys.** Every run mints its own LiteLLM virtual key: model
allow-list, `max_budget` ($2 for the cheap tier), tagged with a trace id, revoked on exit.
A run that fails before minting spends exactly $0.00 — three of my five pilot runs failed,
and their combined cost was nothing. Provider-level day-caps sit above that.

**3. One correlation id everywhere.** `agent-vik454-run32` appears in the ticket comments,
the commit trailers, and the spend ledger. Keys get revoked, but the ledger is immutable, so
a SQL exporter into VictoriaMetrics reconstructs any run's history after the key is gone.

**4. The agent gets a shell, not a cluster.** The runner pod runs a privileged
Docker-in-Docker sidecar (language gates run in the exact images CI uses), but sets
`automountServiceAccountToken: false`, binds a no-authority ServiceAccount, and network
policy denies API-server egress. The Kyverno exception for the DinD sidecar is
label-matched and documents all of this in its own description.

**5. Agent tooling is baked; language toolchains are not.** Baking the Rust toolchain made
the image 2.1 GB. Letting gates run in CI's own images via DinD dropped it to 1.12 GB, and
the gates now match CI exactly instead of approximating it.

## Numbers from the pilot

| Run | What | Result | Cost |
| --- | --- | --- | --- |
| 31 | build | failed at key mint (16 s) | $0.00 |
| 32 | build | PR opened: 16 specs, 83/83 green | $0.046 (103 requests, 4.6M tokens) |
| 33–34 | revision | failed pre-key, triage comments | $0.00 |
| 35 | revision | revision pushed to the PR | $0.018 |

The reviewer rejected PR #1 on day one: three TypeScript strict-mode errors the builder
skipped. That rejection is the system working.

## Stack

Talos Kubernetes · FluxCD · Forgejo + Forgejo Actions · KEDA · Harbor · Vikunja · LiteLLM ·
OpenHands · ESO + OpenBao · Kyverno · Cilium · VictoriaMetrics/Logs/Traces.

Full write-up (the failure museum: the Cilium identity traps, the placement mistake an ADR
now records, the silent-success provisioner bug) at the canonical link above.
