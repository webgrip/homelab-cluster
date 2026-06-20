---
name: kyverno-policy
description: Author and operate Kyverno ClusterPolicies — validate (Audit/Enforce), generate, PolicyException waivers — and their CLI + chainsaw tests.
when_to_use: Use when adding/editing a Kyverno policy, promoting one Audit→Enforce, granting a PolicyException, or writing/running kyverno CLI or chainsaw tests.
allowed-tools: Bash(./scripts/run-flux-local-test.sh*), Bash(just kyverno-test*), Bash(just kyverno-chainsaw*)
---

# Kyverno policies

All `kind: ClusterPolicy` in `kubernetes/apps/kyverno/policies/app/`, registered in that dir's
`kustomization.yaml`. Three rule kinds: **validate** (Audit or Enforce), **generate** (e.g. namespace
defaults), and **PolicyException** (waivers).

## Audit vs Enforce
New validate policies land in **`validationFailureAction: Audit`** (reports violations to a PolicyReport,
doesn't block) → promote to **Enforce** (admission-blocks) once the fleet is clean. ~10 policies sit in
Audit; the promotion backlog is tracked in `docs/techdocs/docs/general/roadmap.md`. **Promote one at
a time** and check PolicyReports are clean first, or you'll block a legitimate workload at admission.

## Add a policy
1. `…/policies/app/<name>-<audit|enforce|generate>.yaml`, `kind: ClusterPolicy`. Copy
   `network-exposure-enforce.yaml` (enforce) or any `*-audit.yaml`.
2. Register in `…/policies/app/kustomization.yaml` `resources`.
3. **Write a CLI test** (below) — the suite covers each policy.

## PolicyException (waive a policy for specific resources)
When a workload legitimately must break a policy (e.g. forgejo-runner's privileged DinD), add `kind:
PolicyException` (v2) at `…/policies/app/exception-<name>.yaml`, matching the **exact** resource (labels) +
the `policyName`/rule names. Scope it tight — match the specific workload, never the whole namespace. Model:
`exception-forgejo-runner.yaml`. Note: privileged DinD *also* needs the namespace at
`pod-security.kubernetes.io/enforce: privileged` — Kyverno and PSA are separate gates (`docs/techdocs/docs/runbooks/forgejo-runner.md`).

## Test (required for a policy change)
- **CLI (fast, offline):** `just kyverno-test` → `scripts/run-kyverno-cli-tests.sh`. Per policy:
  `kubernetes/apps/kyverno/tests/cli/<policy>/{kyverno-test.yaml,resources.yaml}` (pass/fail expectations).
- **Chainsaw (live KinD, slower):** `just kyverno-chainsaw` → `scripts/run-kyverno-chainsaw.sh`, fixtures
  `kubernetes/apps/kyverno/tests/chainsaw/<suite>/chainsaw-test.yaml` (suites: generate-defaults, network-guardrails).

## Generate policies
`namespace-defaults-generate.yaml` generates per-namespace `default-deny` + `allow-dns` NetworkPolicies +
ResourceQuota/LimitRange on the opt-in label `kyverno.io/default-network-policies: "true"` — see the
`network-policy` skill.

## Validate
`./scripts/run-flux-local-test.sh` + `just kyverno-test` (+ `just kyverno-chainsaw` for generate/netpol changes).
