---
description: Audit every Kyverno policy against live state — enforcement inventory, real violations (sweep, not PolicyReports), orphaned waivers, test coverage, wave readiness.
allowed-tools: Bash(mise exec -- kubectl get*), Bash(mise exec -- kubectl describe*), Bash(mise exec -- yq*), Bash(mise exec -- jq*), Bash(docker run*), Bash(./scripts/check-kyverno-test-coverage.sh*), Bash(mise exec -- just kyverno-test*), Bash(grep*), Bash(ls*)
---

Read-only audit of the Kyverno estate. **Mutate nothing.**

## Why this is not just `kubectl get polr`

PolicyReports are the obvious source and they are **not trustworthy on their own**. Two
holes, both found the hard way on 2026-08-03/04 (see the gate note in
`docs/techdocs/docs/rfc/rfc-kyverno-audit-enforce-hardening.md`):

1. **Reports only cover resources that EXIST.** CronJob/Job pods live for seconds, so a
   rule can read 0 FAILs and still deny every one of them at the next schedule tick. This
   nearly killed the CNPG backup drills in eight namespaces.
2. **Several kinds are never scanned at all.** Verified live: Role, RoleBinding,
   ClusterRoleBinding, ServiceMonitor, PodMonitor, PrometheusRule and Namespace appear
   **zero** times across every PolicyReport. Rules scoped to them read "0 fails" whether
   clean or catastrophic — `disallow-wildcards-in-app-roles` reported 0 while failing
   **all 55** Roles in the cluster.

So the authority here is a `kyverno apply` sweep over live state, not a report count.

## Steps

### 1. Enforcement inventory

**Two dialects now.** The estate is migrating off legacy `kyverno.io/v1` ClusterPolicy to the
`policies.kyverno.io` CEL family before v1.20 removes it (rfc-kyverno-cel-migration.md), so an
inventory that only lists `clusterpolicy` silently omits every migrated policy. **Readiness lives
in a different field too**: legacy uses `status.conditions[type=Ready].status == "True"`, CEL uses
`status.conditionStatus.ready == true`. Query both or a migrated policy reads as not-Ready.

```
mise exec -- kubectl get clusterpolicy,validatingpolicy,mutatingpolicy,generatingpolicy,imagevalidatingpolicy,deletingpolicy -o json | mise exec -- jq -r '.items[] | "\(.kind)\t\(.metadata.name)\tready=\(.status.conditionStatus.ready // ([.status.conditions[]?|select(.type=="Ready")|.status=="True"]|first) // "?")"' | sort
```

**Then resolve the EFFECTIVE action per rule — the policy-level field is not the answer.**
Kyverno takes the rule-level `validate.failureAction` over `spec.validationFailureAction`, and this
estate uses that deliberately: nine rules sit at `Audit` inside `Enforce` policies, under an
`audit-*` naming convention where the prefix matches the effective action. Reading only the
policy-level field over-reports blocking rules — on 2026-08-04 it produced a false "the CNPG DR
component will be denied at CREATE" finding against rules that only audit.

```
mise exec -- kubectl get clusterpolicy -o json | mise exec -- jq -r '.items[] | .metadata.name as $p | (.spec.validationFailureAction // "-") as $pa | .spec.rules[] | select(.validate) | "\(.validate.failureAction // $pa)\t\($p)/\(.name)"' | sort
mise exec -- kubectl get validatingpolicy,imagevalidatingpolicy -o json | mise exec -- jq -r '.items[] | "\(if ([.spec.validationActions[]?] | index("Deny")) then "Enforce" else "Audit" end)\t\(.metadata.name)\t(CEL, no named rules)"' | sort
```

**CEL policies have no named rules.** Their PolicyReport results carry `policy` and
`source: KyvernoValidatingPolicy` but NO `rule` field, and CLI Test `results[]` entries must omit
`rule:` — asserting a rule name against a CEL policy scores as `Pass / Excluded`, green while
proving nothing. Their enforce signal is `validationActions: [Deny]`; `Audit`/`Warn` do not block.
Flag any policy not Ready. Cross-check against the repo: a policy file present in
`kubernetes/apps/kyverno/policies/app/` but absent in-cluster means the Kustomization is
failing.

### 2. Build the sweep corpus — **preserve `ownerReferences`**
Synthesize a Pod from every controller pod-template plus every live Pod. Stamp a `Job`
ownerReference on pods derived from Job/CronJob templates and a `ReplicaSet` one on those
from Deployments/StatefulSets/DaemonSets.

This is not optional. `require-pod-probes` deliberately skips Job-owned pods (probes are
meaningless on a pod that runs to completion). A corpus without that field reported **65**
probe failures against a real **6** — the sweep itself became the false positive.

### 3. Sweep each policy, scoped to its own namespaces
The kyverno CLI does **not** resolve `namespaceSelector` from supplied Namespace objects,
so filter the corpus to each policy's own exclusion list first, or every excluded namespace
shows up as a violation.

Read each rule's scope individually — it is **not** always `namespaceSelector`. Namespace-
scoped rules typically use `exclude.any[].resources.names[]` instead, and a script that only
looks for `namespaceSelector` gets an empty exclusion list and reports every platform
namespace as failing.

Run `kyverno apply <policy> --resource <scoped corpus> --exception <all exceptions>` via
the pinned CLI image (see `scripts/lib/kyverno-tests.sh` for `KYVERNO_CLI_IMAGE`).
Concatenate the exception files but **skip `kustomization.yaml`**, and do not leave a
leading `---` (an empty first document errors with "GVK cannot be empty").

For non-Pod policies sweep the matched kinds directly (Roles, Namespaces, NetworkPolicies,
ServiceMonitors/PodMonitors/PrometheusRules, ConfigMaps, HTTPRoutes).

Two rule shapes **cannot be swept offline**. Report them UNSWEPT, never clean:

- `verifyImages` rules (`image-verify-harbor-audit`, `image-cve-budget-audit`) need registry access; the
  CLI evaluates nothing for them.
- Rules with an `apiCall` **context** (e.g. `require-resourcequota`, `require-networkpolicy`,
  which query for existing objects in the namespace) cannot resolve the call offline. They
  surface as `error`, NOT `fail` — so a sweep reporting "0 fail" while showing errors is
  telling you nothing about those rules. Check them with a direct `kubectl` query instead.
  This exact trap hid 5 real wave-12 failures behind a clean-looking "1 fail" on 2026-08-04.

**Never read `fail: 0` without also reading the `error:` count.**

### 4. Waiver integrity
A PolicyException is keyed by `policyName`. Splitting or renaming a policy silently
orphans every waiver still naming the old one — this has bitten three times (waves 4, 10,
11). Check every exception's `policyName` resolves to a policy that exists, and every
`ruleNames` entry to a rule that policy actually has:
```
mise exec -- kubectl get policyexception -A -o json | mise exec -- jq -r '.items[] | .metadata.name as $n | .spec.exceptions[] | "\($n)\t\(.policyName)\t\(.ruleNames|join(","))"'
```
Also confirm each waiver covers **both** the base rule and its `autogen-` variant where the
policy has `pod-policies.kyverno.io/autogen-controllers` — covering only one still blocks.

### 5. Test coverage
```
./scripts/check-kyverno-test-coverage.sh
mise exec -- just kyverno-test
```
Every enforcing policy needs a fail case AND a pass case. A failure-only suite cannot tell
a working policy from one that rejects everything — exactly how the wildcard-Role bug
survived (`operator: AnyIn` with `value: ["*"]` globs and matches every string; use
`contains(element.verbs || \`[]\`, '*')` instead).

### 6. Downstream references
Grep dashboards and rules for policy names that no longer exist — renaming
`rbac-least-privilege-audit` would have blanked nine panels:
```
grep -rn "policy=\\\\\"" kubernetes/apps/observability/grafana/app/dashboards/ | grep -oE 'policy=\\"[a-z0-9-]+' | sort -u
```

## Output

A verdict — 🟢 / 🟡 / 🔴 — then:

- **Enforcing vs Audit** table, and which rules are deliberately permanent-Audit
  (`require-approved-registries` per ADR-0033 — its FAILs are the intended
  registry-sovereignty drift signal and must NOT be "fixed"; `image-verify-harbor`).
- **Real violations per rule** from the sweep, with the resource names, separating
  genuinely-failing from waived.
- **Orphaned waivers / dangling references**, if any — these are silent breakage.
- **Wave readiness**: which remaining waves in the RFC are gate-clean by sweep, with
  counts. Do not report a wave clean on a PolicyReport count alone.
- Anything UNSWEPT and why.

Keep it short. Cite resource names, not adjectives.
