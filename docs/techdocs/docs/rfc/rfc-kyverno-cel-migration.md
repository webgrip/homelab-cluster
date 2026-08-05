# RFC: Kyverno CEL policy migration — the API we run on is removed in October 2026

> Status: **Proposed** · Date: 2026-08-04 · Spawned by the [Kyverno estate audit](rfc-kyverno-audit-enforce-hardening.md#audit-2026-08-04)

> **TL;DR.** All **25** ClusterPolicies in this cluster are the legacy `kyverno.io/v1`
> (JMESPath) API. Kyverno 1.17 marked that API **Deprecated** and targets **removal in v1.20,
> October 2026**; we run **1.18.1**, which upstream already classes as critical-fixes-only for it.
> The replacement CRDs are *already installed here* — `validatingpolicies`, `mutatingpolicies`,
> `generatingpolicies`, `imagevalidatingpolicies`, `deletingpolicies` under
> `policies.kyverno.io` — and sitting unused. This is not a cosmetic rename: `ValidatingPolicy`
> is a **superset of upstream `ValidatingAdmissionPolicy`**, the namespaced variants delete the
> hand-maintained `NotIn` namespace lists that have twice made our own audit sweeps lie, and CEL
> removes the entire class of bug that shipped a rule which silently denied all 55 Roles in the
> cluster. The deadline is real and a Renovate chart bump can arrive before we're ready.

## Why

Verified state, 2026-08-04:

| Fact | Value |
| --- | --- |
| Running version | `reg.kyverno.io/kyverno/kyverno:v1.18.1` (chart `3.8.1`) |
| Policies on legacy API | 25 / 25 (`kyverno.io/v1`) |
| Exceptions on legacy API | 17 / 17 (`kyverno.io/v2`) |
| CEL CRDs installed | yes — 10 (`{,namespaced}{validating,mutating,generating,imagevalidating,deleting}policies.policies.kyverno.io`) |
| CEL policies authored | 0 |

Upstream's published sunset ([1.17 release announcement](https://kyverno.io/blog/2026/02/02/announcing-kyverno-release-1.17/)):

| Kyverno | Timeline | Legacy `ClusterPolicy` status |
| --- | --- | --- |
| 1.17 | Feb 2026 | Deprecated |
| **1.18** | Apr 2026 | **critical fixes only — where we are** |
| 1.19 | Jul 2026 | critical fixes only |
| 1.20 | **Oct 2026** | **planned removal** |

Four reasons this is worth doing on purpose rather than under duress:

1. **A Renovate bump is an unguarded trapdoor.** The chart is pinned by tag (`3.8.1`) and
   `.renovaterc.json5` excludes only `kyverno/policies/**` and `kyverno/tests/**` — the *chart*
   is in scope. Nothing in the repo prevents a routine minor-chart PR from landing 1.20 and
   removing the CRD that carries our entire admission posture. The failure mode is not a broken
   pod; it is **25 policies silently ceasing to exist** while Flux reports Ready.
2. **CEL kills a bug class we have already shipped.** `disallow-wildcards-in-app-roles` used
   `operator: AnyIn` with `value: ["*"]`, which Kyverno treats as a **glob**, not a literal
   asterisk — so the rule matched every string and failed all 55 Roles in the cluster while its
   PolicyReport read 0. In CEL the same check is an ordinary expression
   (`rule.verbs.exists(v, v == '*')`) with no operator-semantics trap. Our current mitigation is
   a hand-rolled `contains(...)` JMESPath idiom whose correctness depends on remembering that
   In/AnyIn globs and `contains` does not.
3. **Namespaced policies delete the `NotIn` lists.** Eight policies each carry a hand-maintained
   16–17 entry `kubernetes.io/metadata.name NotIn [...]` selector. These lists drift, and the
   Kyverno CLI does **not** resolve `namespaceSelector` from supplied Namespace objects — which
   is exactly why the 2026-08-04 audit sweep reported two phantom Role failures in `flux-system`
   and `longhorn-system` before rescoping. `NamespacedValidatingPolicy` expresses the same intent
   without a list to maintain or a sweep to mis-scope.
4. **`DeletingPolicy` covers the one policy we cannot test.** `stateful-delete-protection-enforce`
   swept 0/0 in the audit — its rules fire on DELETE, so a static corpus evaluates nothing and the
   CLI has no way to exercise it. It is the sole enforcing policy with genuinely zero offline
   coverage. The CEL family models deletion as a first-class policy type.

Secondary but real: CEL evaluates materially faster than JMESPath, and `ValidatingPolicy`
compiles down to upstream `ValidatingAdmissionPolicy` where the rule allows it — moving those
evaluations **into the API server**, off the webhook path. On a single-worker homelab where the
Kyverno admission controller is a cluster-wide availability dependency, shortening that path is a
resilience win, not just a performance one.

## Findings from execution (2026-08-05)

Two things learned by migrating, both of which change the plan below. Neither was visible
from reading the docs.

### 1. Waiver granularity forces splits — but far fewer than one-per-rule

The CEL `PolicyException` has `policyRefs: [{kind, name}]` and **no `ruleNames`**: waivers
are whole-policy. Naively that means one ValidatingPolicy per rule, to keep a whole-policy
waiver equal to the old per-rule one. Measured against the live estate, the real requirement
is much smaller — rules whose waiver-sets are **identical** can share a policy:

| | |
| --- | --- |
| validate rules today | 78 |
| ValidatingPolicies actually needed | **35** |
| policies needing no split at all | **9** |

The 9 that migrate 1:1 (name preserved, so no dashboard breakage): `exception-governance`,
`image-hygiene-audit`, `namespace-tenancy-audit`, `namespace-tenancy-enforce`,
`rbac-least-privilege-enforce`, `require-pod-probes-audit`, `secrets-observability-ops-enforce`,
`stateful-delete-protection-enforce`, and the already-migrated `image-supply-chain-audit`.
Notably `rbac-least-privilege-enforce` (5 rules, one waiver-set) is among them, which
removes the concern about renaming a policy that nine Grafana panels select on.

The worst case is `workload-advanced-hardening-audit`: 11 rules across 6 distinct
waiver-sets. `pod-security-baseline-enforce` needs 4 from 4 rules — every rule has a
different waiver-set.

Regenerate the grouping before each wave; it changes whenever an exception is added.

### 2. **BLOCKER: CEL autogen does not work — Pod policies cannot migrate**

Legacy Pod policies rely on autogen to evaluate *controllers* at admission. Verified on
2026-08-05 that the CEL equivalent produces nothing. A Deployment and a CronJob both
carrying a tagless `image: nginx`, swept with `image-hygiene-audit` in both dialects:

| dialect | result |
| --- | --- |
| legacy ClusterPolicy | **fail: 2** — `autogen-require-image-tag` and `autogen-cronjob-require-image-tag` both fire |
| CEL ValidatingPolicy | **pass: 0, fail: 0** — neither resource is evaluated at all |

Not a config error: identical with an explicit `spec.autogen.podControllers.controllers`
list, with a single-controller list, and with the block omitted entirely. The same policy
correctly fails a bare **Pod** (`fail: 1`), so only the autogen path is dead. Corroborated
in-cluster — the migrated pilot reports `status.autogen: {}` despite declaring three
controllers.

**Consequence.** Migrating an enforcing Pod policy silently moves the deny from controller
admission to pod creation. For a Deployment that is a worse error message; for a **CronJob
it means the failure lands at the next schedule tick, in production, unattended** — exactly
the trap the audit→enforce RFC's gate note exists to prevent. `image-hygiene-audit` was
written, differentially tested, and **reverted unmigrated** for this reason.

The already-migrated `image-supply-chain-audit` stays: it is Audit-only, so nothing is
un-enforced, and every controller's pods are still evaluated by the base rule, so the drift
signal survives. It loses only the duplicate controller-level report row.

**Until autogen is understood, only non-Pod policies may migrate.** Next step is a spike:
determine whether CEL autogen requires a newer Kyverno, a feature gate, or a different
spec shape — and whether the CLI and the controller disagree.

## Proposal

Kyverno runs both APIs side by side through 1.19, so this is a staged migration with a hard
backstop, not a flag day.

1. **Guard the trapdoor first** (do this before any migration work). Add a Renovate constraint
   holding the Kyverno chart below the version that ships 1.20, with a comment naming this RFC,
   so the bump becomes a deliberate decision instead of an automerge. Cheap, reversible, and it
   buys the whole schedule.
2. **Teach the harness both dialects** (prerequisite). `scripts/lib/kyverno-tests.sh` discovers
   policies by kind; it must recognise the `policies.kyverno.io` kinds too, and
   `scripts/check-kyverno-test-coverage.sh` must count a CEL policy's tests as coverage. Until
   this lands, migrating a policy would silently drop it out of CI — the same latent hole the
   audit RFC already closed once for the hardcoded allowlist.
3. **Migrate in waves, ordered by blast radius ascending**, reusing the ADR-0032 gate machinery
   verbatim (sweep → fail case *and* pass case → `just kyverno-test` → flux-local → flip → watch
   one admission cycle). Suggested order:
   - **Wave A — Audit-only, non-Pod kinds** (`longhorn-*`, `namespace-defaults-generate` →
     `GeneratingPolicy`). Nothing can be blocked by getting these wrong.
   - **Wave B — Enforcing, narrow kinds** (`exception-governance`, `cert-manager-governance`,
     `flux-governance-enforce`, `network-exposure-enforce`, `storage-cnpg-governance`).
   - **Wave C — the eight `namespaceSelector` Pod policies**, converting each `NotIn` list into
     namespaced policies as part of the move. This is where the win is, and where the risk is:
     a mis-scoped conversion changes *which workloads are governed*, silently.
   - **Wave D — `verifyImages` → `ImageValidatingPolicy`** (the three image-verify policies plus
     `image-cve-budget-audit`). Sequence **after** [verify-policy gating](rfc-verify-policy-gating.md)
     lands, so these convert once against a working gate rather than twice.
   - **Wave E — `stateful-delete-protection-enforce` → `DeletingPolicy`**, last, because it is the
     one with no prior test coverage to regress against.
4. **Migrate exceptions with their policies, not separately.** A `PolicyException` is keyed by
   `policyName`; renaming a policy orphans every waiver naming the old one. That has already
   bitten this repo three times (waves 4, 10, 11). Each wave's commit must move the policy **and**
   repoint its exceptions, and the post-flip check is the audit's waiver-integrity query, not a
   glance at the PolicyReport.
5. **Keep a converted-policy equivalence check in the loop.** For each migrated policy, run the
   audit sweep against both the old and new form over the same corpus and require identical
   pass/fail sets before deleting the legacy file. A migration that changes behaviour should have
   to say so out loud.

## Risks

- **Behavioural drift on conversion is invisible by default.** JMESPath and CEL disagree on
  null-handling and type coercion at the edges. Mitigation is step 5 — differential sweeps, not
  code review.
- **`PolicyException` has two CRDs installed** (`kyverno.io` and `policies.kyverno.io`). Mixing a
  CEL policy with a legacy-API exception is a plausible silent no-op. The wave commits must keep
  each policy and its waivers on the same dialect.
- **Reports and dashboards key on policy names.** Three Grafana dashboards filter on
  `policy="..."` (`image-attestations-audit`, `image-verify-audit`,
  `rbac-least-privilege-enforce`). Renaming during migration blanks panels; keep names stable or
  update the dashboards in the same commit.
- **We may not finish before 1.20.** That is survivable — 1.19 is supported and there is no
  obligation to take 1.20 in October. The unsurvivable version is taking 1.20 *by accident*,
  which step 1 prevents.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Adopt the CEL policy family as the target API; legacy `kyverno.io/v1` is frozen (new) |
| candidate | — | Pin the Kyverno chart below 1.20 until migration completes (new) |
| candidate | — | Replace `namespaceSelector` NotIn lists with namespaced policies during Wave C (new) |

## Out of scope

- Promoting any policy Audit→Enforce — that is the [audit→enforce RFC](rfc-kyverno-audit-enforce-hardening.md)
  and [ADR-0032](../adr/adr-0032-kyverno-enforce-promotion-policy.md). **Migration and promotion
  must not share a wave**; a policy changes dialect or changes mode, never both at once.
- The registry-sovereignty posture — [ADR-0033](../adr/adr-0033-approved-registries-stays-audit.md),
  unaffected.
- Kyverno-as-authorization-server for L7 request policy — separate concern, separate deployment,
  [own RFC](rfc-request-authorization-envoy.md).

## References

- [Kyverno 1.17 release announcement](https://kyverno.io/blog/2026/02/02/announcing-kyverno-release-1.17/)
  — GA promotion and the deprecation table
- [ValidatingPolicy](https://kyverno.io/docs/policy-types/validating-policy/) ·
  [MutatingPolicy](https://kyverno.io/docs/policy-types/mutating-policy/) ·
  [GeneratingPolicy](https://kyverno.io/docs/policy-types/generating-policy/)
- [CNCF: how Kyverno complements Kubernetes' native policy types](https://www.cncf.io/blog/2025/10/16/kyverno-vs-kubernetes-policies-how-kyverno-complements-and-completes-kubernetes-policy-types/)
  — the `ValidatingAdmissionPolicy` superset relationship
- [RFC: Kyverno audit→enforce hardening](rfc-kyverno-audit-enforce-hardening.md) — the gate
  machinery this reuses, and the audit that found the wildcard-glob bug
