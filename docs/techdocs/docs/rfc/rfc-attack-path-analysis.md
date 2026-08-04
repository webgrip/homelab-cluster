# RFC: Attack-path analysis — validate the policy estate as a graph, not a list

> Status: **Proposed** · Date: 2026-08-04 · Spawned by the [Kyverno estate audit](rfc-kyverno-audit-enforce-hardening.md#audit-2026-08-04)

> **TL;DR.** Every security control in this cluster answers a **list** question: which pods lack
> probes, which Roles hold wildcards, which images are unsigned. The 2026-08-04 audit produced
> exactly that — accurate, complete, and structurally unable to answer the question that actually
> matters: *does a path exist from something an attacker can reach to something they want?* Our
> 17 PolicyExceptions are each individually justified, and several of them stack privileged +
> hostPath + a mounted ServiceAccount token onto the same CI workloads. Whether those compose into
> a route to cluster-admin is not a question any policy engine can answer, because admission
> control evaluates one object at a time. [KubeHound](https://github.com/DataDog/KubeHound)
> (Datadog, Apache-2.0) answers it by building a BloodHound-style attack graph of the live cluster.
> It runs read-only from a laptop, deploys nothing, and would be the first control here that
> reasons about **composition**.

## Why

The audit's own findings are the argument. Verified state, 2026-08-04:

- **17 PolicyExceptions**, concentrated on the CI path — `forgejo-dind`, `forgejo-buildkitd`,
  `forgejo-runner`, `forgejo-agent-runner`, `ploeg-worker`. Between them these waive
  `privileged-containers`, `host-path`, `host-ports-none`, `host-namespaces`,
  `require-drop-all-capabilities`, `run-as-non-root`, `privilege-escalation` and
  `check-seccomp-strict`.
- **22 pods on the default ServiceAccount** and **17 without a ServiceAccount-token opt-out**
  (the wave-8 backlog).
- **338 RBAC objects** — 109 Roles, 111 RoleBindings, 118 ClusterRoleBindings.
- **No runtime detection.** Falco and Tetragon have been uninstalled since 2026-06-19
  ([runtime RFC](rfc-runtime-detection-response.md)), so nothing observes what a compromised
  workload does after admission.

Each waiver is defensible on its own — a Docker-in-Docker build genuinely needs privileges. But
"privileged pod" + "hostPath mount" + "mounted SA token" + "a RoleBinding somewhere in 338 objects"
is a *chain*, and we have never evaluated the chains. The gap is categorical, not a matter of
being more thorough with the existing tools:

1. **Admission control is single-object by construction.** Kyverno evaluates the resource in front
   of it. It cannot express "this is fine unless that other thing also exists", which is exactly
   the shape of privilege escalation.
2. **Waivers are where composition hides.** The exception list is the deliberate, reviewed set of
   places where the guardrails are off. That is precisely the input an attack-path tool should be
   pointed at, and precisely what a per-rule FAIL count cannot evaluate.
3. **We have no compensating runtime control right now.** With no detector installed, a chain that
   exists is a chain that executes unobserved. That raises the value of finding chains
   *statically* until the runtime RFC lands.

## Proposal

Deliberately small. This is an **audit exercise**, not a platform component.

1. **Run KubeHound locally against the cluster, read-only, as a one-off.** It collects via the
   Kubernetes API using an existing read-only context and stores the graph in a local JanusGraph
   container — nothing is deployed to the cluster, nothing is mutated, and the whole thing is
   `docker compose down` away from gone. This costs an afternoon and is the cheapest way to find
   out whether the idea earns anything here.
2. **Treat the first run as calibration, not a verdict.** KubeHound models 25+ attack primitives
   (`POD_EXEC`, `CONTAINER_ATTACH`, `TOKEN_STEAL`, `EXPLOIT_HOST_WRITE`, …). On a cluster that
   deliberately runs privileged CI workloads, it will report paths that are *known and accepted*.
   The output to care about is the path we did **not** already know about — particularly anything
   originating at an externally-attached HTTPRoute.
3. **Convert real findings into the existing machinery, not a new one.** A confirmed path becomes
   either a Kyverno rule (if it is expressible as a per-object invariant), a narrowed
   PolicyException (if the waiver was broader than the workload needed), or an accepted risk with
   a recorded reason. The point of the exercise is to feed the controls we already have.
4. **Decide cadence only after the first run.** If it finds nothing new, the honest answer is
   "run it again after significant RBAC or waiver changes" and no automation. If it finds real
   paths, a periodic run — plausibly in the same slot as the other weekly supply-chain jobs —
   becomes justified. Do not build a pipeline for a tool that has not yet earned one.

## Risks

- **Findings need triage judgement.** Graph tools are generous with theoretical paths. Without
  someone reading them against intent, the output becomes a noise source that discredits itself —
  the same failure mode as an alerting plane that delivers nowhere.
- **The graph is a point-in-time snapshot** of a cluster that changes under Flux. A path found on
  Monday may be gone on Tuesday, and vice versa. This argues for treating it as a periodic audit
  rather than a control.
- **JanusGraph is heavy**, which is exactly why this runs on a laptop and not on the cluster. If
  someone later proposes hosting it in-cluster, that is a different RFC with a real footprint
  argument to make against a single worker node.
- **It may find nothing.** That is a legitimate and useful outcome, and it should be recorded as
  such rather than quietly dropped — a negative result on a deliberately-waivered CI path is
  genuine evidence about this cluster's posture.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Adopt attack-path analysis as a periodic audit (or record that it earned nothing) (new) |
| candidate | — | Disposition of any confirmed path: policy rule, narrowed waiver, or accepted risk (new) |

## Out of scope

- Runtime detection and response — [own RFC](rfc-runtime-detection-response.md); complementary,
  and currently unexecuted.
- Admission policy authoring — [audit→enforce RFC](rfc-kyverno-audit-enforce-hardening.md).
- Network-layer reachability — [ADR-0006](../adr/adr-0006-default-deny-network-policies.md);
  KubeHound reasons about identity and privilege, not about whether a NetworkPolicy permits a
  packet.
- Penetration testing of applications. This is infrastructure-graph analysis only.

## References

- [DataDog/KubeHound](https://github.com/DataDog/KubeHound) ·
  [Identifying attack paths in Kubernetes clusters](https://securitylabs.datadoghq.com/articles/kubehound-identify-kubernetes-attack-paths/)
  — the attack-primitive model and the list→graph framing
- [RFC: Kyverno audit→enforce hardening](rfc-kyverno-audit-enforce-hardening.md#audit-2026-08-04)
  — the waiver inventory this would be pointed at
- [RFC: Runtime detection & response](rfc-runtime-detection-response.md) — the missing
  compensating control that raises this RFC's value
