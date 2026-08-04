# RFC: Kyverno audit→enforce hardening

> Status: **Proposed** · Date: 2026-06-21 · Umbrella for [ADR-0032](../adr/adr-0032-kyverno-enforce-promotion-policy.md), [ADR-0033](../adr/adr-0033-approved-registries-stays-audit.md)

> **TL;DR.** 11 Kyverno ClusterPolicies run in `Audit` (observe-only); ~108–114 live FAILs sit
> unenforced. This RFC sequences their promotion to `Enforce` as **gated, one-at-a-time waves**,
> each preceded by the remediation it needs and blocked by a CI test-coverage gate, so we move to
> *enforce-not-observe* without ever blocking a legitimate workload at admission. It also fixes a
> latent hole in the test harness and names the policies that must **stay Audit**.

## Why

The [security-hardening RFC](rfc-security-hardening.md) set the direction: close the loops we
already built. Admission control is half-closed — the policies exist and report, but most don't
block. The newly-repaired SLO alerting now correctly fires `slo-kyverno-fail-total` (114 > 50),
making the backlog visible. The house discipline (from the `kyverno-policy` skill) is unchanged:
**promote one policy at a time, only after a clean PolicyReport, or you block a legitimate
workload at admission.** Two structural facts shape everything:

- **Autogen duality.** Every Pod policy carries `pod-policies.kyverno.io/autogen-controllers`, so a
  violating Deployment produces both a base `<rule>` finding (Pod, background scan) and an
  `autogen-<rule>` finding (controller, admission). Any waiver must cover **both** or admission
  still blocks. This is the single most common way a promotion self-inflicts an outage.
- **Promotion mechanics.** Per-rule action on a `ClusterPolicy` is not supported; the levers are a
  whole-policy `validationFailureAction: Enforce` flip, `validationFailureActionOverrides`
  (per-namespace enforce), or **splitting** a policy (clean rules → a new `-enforce.yaml`, dirty
  rules stay in the `-audit` policy). The repo also uses per-rule `failureAction: Audit` to keep
  individual rules observe-only inside an otherwise-Enforce policy.

## Proposal

### Per-policy blast radius (live FAIL counts, base + autogen)

| Policy | Biggest live FAIL | Verdict |
|--------|-------------------|---------|
| `require-pod-probes` | 6 (not ~18) — `forgejo-dind` + `preview-host` only | DONE — wave 1 enforced after probing both sidecars |
| `image-hygiene` | ~0 (confirmed by template sweep) | DONE — wave 2 enforced |
| `image-supply-chain` | `require-approved-registries` ~103 (intended signal, ADR-0033), `require-image-digest` actual 11 | DONE — waves 4 + 11 enforced; approved-registries **stays Audit** and is all that remains in the audit policy |
| `rbac-least-privilege` | `disallow-wildcards-in-app-roles` ~40 — **this figure was never real**, the rule was denying every Role (glob `*` in `AnyIn`); fixed 2026-08-04, actual count 0 | DONE — waves 3 + 10 both enforced; `-audit` policy retired |
| `workload-hardening` | forgejo 26 | ns-by-ns via overrides; needs resource-limit sweep |
| `workload-advanced-hardening` | SA-token / readonly-rootfs broad | SPLIT — 5 low-risk rules now; invasive rules stay Audit |
| `namespace-tenancy` | netpol/quota/labels | SPLIT — netpol-shape rules now; require-* after roadmap #13 |
| `secrets-observability-ops` | `require-prometheusrule-labels` ~49 (actual: 19 across all three monitor kinds) | DONE — wave 7 enforced after remediating all 19 |
| `image-verify` | unsigned webgrip | SPLIT — kyverno-images rule now; webgrip-images after signing proof |
| `image-verify-harbor` | — | **Stays Audit** (failurePolicy: Fail → Harbor/OpenBao SPOF) |
| `image-attestations` | — | Promote LAST, after image-verify |

### Gated wave sequence

The 14-wave order, gating, and prerequisites live in
[the implementation plan](rfc-kyverno-audit-enforce-hardening.md#waves) and ADR-0032. Each wave:
clean PolicyReport for the promoted rules (base **and** autogen = 0 unwaived) for ≥1 reconcile
cycle → **pod-template sweep (below)** → CLI/chainsaw test added, with a `result: pass` case as
well as a `result: fail` one → `mise exec -- just kyverno-test` + flux-local green → flip → watch
one admission cycle. One wave per commit, spaced apart (the batched-rollout storage-collapse memory).

> **A clean PolicyReport is NOT sufficient to open a wave gate.** Reports only cover resources
> that *exist*. Anything that materialises briefly — CronJob and Job pods above all — contributes
> no findings between runs, so a rule can read 0 FAILs and still deny those pods the moment they
> are created.
>
> This is not hypothetical: it was caught during wave 4 on 2026-08-03. Both CNPG drill CronJobs
> (`cnpg-restore-test`, `cnpg-disaster-recovery-check`) referenced a bare `alpine/k8s:1.36.2@…`,
> which `require-fully-qualified-images` denies. Their pods live for seconds a day, so
> `require-fully-qualified-images` reported **0 live FAILs** and passed the gate as written. Had
> the wave shipped on that basis, it would have silently killed every backup-restore drill and
> disaster-recovery check across eight namespaces at the next schedule tick — failing exactly the
> safety net you would want working when you find out.
>
> So before any flip, sweep pod **templates**, not running pods — every
> Deployment/StatefulSet/DaemonSet/Job/CronJob/Pod in the in-scope namespaces — and evaluate the
> promoted rules against each image or field yourself. Kyverno's `autogen-controllers` annotation
> lists only `DaemonSet,Deployment,StatefulSet`, so CronJob and Job pod templates get **no**
> autogen rule and are invisible at controller admission too; the base rule first bites at pod
> creation, in production, unattended.
>
> Also verify that any PolicyException covering the promoted rules is repointed at the new policy.
> Exceptions are keyed by `policyName`, so a split silently orphans every waiver that still names
> the old policy.

> **Worse: for several kinds there are no PolicyReports at all.** The background scanner only
> reports on some kinds. Verified live on 2026-08-04 — across every PolicyReport in the cluster the
> scoped kinds are Service, ConfigMap, NetworkPolicy, Deployment, Kustomization,
> PersistentVolumeClaim, Pod, HelmRelease, OCIRepository, CronJob, Job, PolicyException,
> HelmRepository, ScheduledBackup, StatefulSet, Certificate, DaemonSet, GitRepository. **Role,
> RoleBinding, ClusterRoleBinding, ServiceMonitor, PodMonitor, PrometheusRule and Namespace appear
> zero times.**
>
> So every rule scoped to those kinds reads "0 FAILs" whether it is clean or catastrophic. This was
> not theoretical either: `disallow-wildcards-in-app-roles` reported 0 and a CLI sweep found **55**
> failing Roles; the monitor-label rules reported 0 and a sweep found **19** failures. Both had been
> recorded as gate-clean on the strength of the report count.
>
> The gate for any wave touching those kinds is a `kyverno apply` sweep over a live dump of the
> matched resources. Note the CLI does **not** resolve `namespaceSelector` from supplied Namespace
> objects, so filter the dump to the policy's own in-scope namespaces first or the sweep will
> over-report against namespaces the policy excludes.
>
> One further limit: `verifyImages` rules (waves 6, 13 and 14) cannot be swept this way at all —
> they need registry access and the CLI evaluates nothing for them offline. Those three need a
> different gate, not a sweep.
>
> Two more traps worth naming, both hit on 2026-08-04:
>
> - **Preserve `ownerReferences` when you synthesise pods for a sweep.** Rules legitimately key on
>   them — `require-pod-probes` skips Job-owned pods, because probes are meaningless on a pod that
>   runs to completion. A corpus built without that field reported 65 probe failures where the real
>   number is 6. Stamp a `kind: Job` ownerReference on pods synthesised from Job/CronJob templates,
>   and a `ReplicaSet` one on those from Deployments.
> - **`operator: AnyIn` with `value: ["*"]` does NOT test for a literal asterisk.** Kyverno's
>   In/AnyIn family treats `*` on the value side as a glob, so it matches everything. That is what
>   made `disallow-wildcards-in-app-roles` fail all 55 Roles. Use
>   `key: "{{ contains(element.verbs || `[]`, '*') }}" / operator: Equals / value: true` instead.
>   Any rule written to catch a literal wildcard is suspect until it has a **passing** test case.

<a name="waves"></a>

| Wave | Policy / rules | Mechanism | Prereq |
|------|----------------|-----------|--------|
| 1 | `require-pod-probes` (whole) | Enforce | **SHIPPED 2026-08-04** — prune + git-sync sidecars given probes (remediated, not waived); 101 pods/templates clean, 58 correctly skipped as Job-owned |
| 2 | `image-hygiene` (whole) | Enforce | **SHIPPED 2026-08-04** — namespaceSelector reconciled; swept 168 pods+templates, 0 fails |
| 3 | `rbac-least-privilege` — 4 clean rules | split→Enforce | **SHIPPED 2026-08-04** — `rbac-least-privilege-enforce`; swept 371 RBAC objects |
| 4 | `image-supply-chain` — latest-tag + fully-qualified | split→Enforce | **SHIPPED 2026-08-03** — `image-supply-chain-enforce`; prereq was NOT "none" (see the gate note above) |
| 5 | `namespace-tenancy` — netpol-shape rules | split→Enforce | **SHIPPED 2026-08-04** — `namespace-tenancy-enforce` |
| 6 | `image-verify` — `verify-kyverno-images-keyless` | split→Enforce | **UNSWEPT** — `verifyImages`; needs registry access, CLI evaluates nothing offline |
| 7 | `secrets-observability-ops` — monitor-label rules | split→Enforce | **SHIPPED 2026-08-04** — all 19 remediated (11 repo manifests + guac via chart values + renovate-operator via postRenderer), then flipped; 85/85 clean |
| 8 | `workload-advanced-hardening` — 5 low-risk rules | split→Enforce | **NOT clean** — 65 fails: non-default-SA 24, SA-token opt-out 17, risky-volumes 7, non-baseline-caps 7, drop-ALL 6, explicit-root 4 |
| 9 | `workload-hardening` (4 rules) | overrides, ns-by-ns | **NOT clean** — 46 fails: run-as-non-root 15, seccomp 15, validate-resources 10, privilege-escalation 6 |
| 10 | `rbac-least-privilege` — wildcards | merge→Enforce | **SHIPPED 2026-08-04** — the "55 failing Roles" were a RULE BUG, not a backlog (see below); fixed, 55/55 pass, `-audit` policy retired |
| 11 | `image-supply-chain` — `require-image-digest` | merge→Enforce | **SHIPPED 2026-08-04** — erfbeeld ×3 + minecraft genuinely pinned; only CNPG operator images waived; audit policy now holds require-approved-registries alone |
| 12 | `namespace-tenancy` — require-{netpol,quota,labels} | merge→Enforce | **1 fail, needs one manual step.** The `drawio` namespace is an EMPTY orphan: Git declares all three labels, but the app is deliberately SUSPENDED so Flux no longer manages it. `kubectl delete namespace drawio` clears the wave (verified empty: 0 workloads, 0 PVCs). Do not un-suspend the app to satisfy a policy |
| 13 | `image-verify` — `verify-webgrip-images` | merge→Enforce | **UNSWEPT** — `verifyImages` rules need registry access; the CLI cannot evaluate them offline |
| 14 | `image-attestations` | Enforce | **UNSWEPT** — same `verifyImages` limitation as wave 13 |
| — | approved-registries, image-verify-harbor, advanced invasive rules, secrets PDB/topology/cm-keys | **stay Audit** | see ADR-0033 |

### Test harness fixes (prerequisite, shipped first)

- **Closed a latent hole:** `scripts/lib/kyverno-tests.sh` hardcoded a policy allowlist that
  silently omitted `workload-hardening`, `workload-advanced-hardening`, `secrets-observability-ops`,
  `image-hygiene`, `image-verify-harbor`, `storage-cnpg` — so those could be flipped to Enforce with
  zero CLI coverage and CI would stay green. Now discovered by kind (every policy + exception loads).
- **Added the gate:** `scripts/check-kyverno-test-coverage.sh` fails CI if an enforcing policy isn't
  exercised by a CLI test with a `fail` case (pass-case advisory; pre-existing untested
  `storage-cnpg-governance` is baselined as debt). Wired into `.forgejo/workflows/e2e.yml` before the test run.

## Decisions

| ADR | Status | Decision |
|-----|--------|----------|
| [ADR-0032](../adr/adr-0032-kyverno-enforce-promotion-policy.md) | Proposed | Gated wave promotion via split + overrides; mandatory test-coverage gate before any Enforce merge. |
| [ADR-0033](../adr/adr-0033-approved-registries-stays-audit.md) | Proposed | `require-approved-registries` stays Audit; enforce only ever via Harbor proxy + admission mutate-rewrite. |

## Out of scope

- The Harbor pull-through proxy + the admission mutate-rewrite that would make
  `require-approved-registries` enforceable — its own future work
  ([RFC: Harbor proxy cache](rfc-harbor-proxy-cache.md)).
- Restricting Helm/OCI source registries (a follow-up noted in the supply-chain policy).

## Deferred items (from retired enforcement roadmap, 2026-07-02)

The earlier standalone enforcement-roadmap RFC was retired (it assumed keyless GHCR + an
enforceable registry allowlist, both since overturned — see
[supply-chain-pipeline](../general/supply-chain-pipeline.md) and ADR-0033). These are the
still-open items it owned that live nowhere else:

**Flux chart-source verification** (Kyverno never sees Flux's chart pulls):

- No `OCIRepository`/`HelmRelease` uses `spec.verify.provider: cosign` today — chart *signature*
  verification is unbuilt (digest pinning is enforced by `flux-governance-enforce`).
- Flux verify is **enforce-only** (failed verify → `Ready=False`, artifact withheld; no audit
  mode). For an audit phase, run a side-channel CronJob that `cosign verify`s charts → alert;
  add `spec.verify` only when ready to enforce.
- Keyed verification needs the `cosign-webgrip` public key mirrored as a Secret in `flux-system`
  (Flux can't read the `security`-ns ConfigMap).
- Harbor-only *chart* sources: mirror upstream OCI charts through Harbor, repoint
  `OCIRepository.spec.url`, and guard with a `flux-governance-enforce` rule pinning chart hosts —
  sequence after image mirroring is stable (a broken chart source fails reconciliation hard).

**Harbor-side hardening** (project settings, not yet captured as IaC):

- Tag immutability on `webgrip/**` release tags — the keyed path has no Rekor; immutability +
  sign-by-digest close the tag-mutation gap.
- Robot least privilege: CI push robot and Kyverno pull-only robot (`harbor-pull`) stay separate;
  neither gets project admin. Project storage quota + retention/GC that never prunes a digest a
  running pod or signature still references.
- CVE-severity pull-gating last, observe-mode first (a fresh CVE can otherwise block the cluster
  pulling its own runner images).
- Capture all of the above as IaC (Harbor API/Terraform) instead of clicked-in settings.

**Runner hardening** (privileged DinD path):

- Gate who can trigger the release path (protected tags / protected branches) — the OpenBao
  claim binding delegates signing authorization to the forge event, so forge-side protection is
  the real boundary.
- Move off privileged DinD (rootless/sysbox or a shared locked-down buildkitd); the LXC/VM
  runner variant is explicitly backbenched as P2 ([ADR-0026](../adr/adr-0026-rootless-ci-image-builds.md) owns the rootless move).
- Scope the runner ServiceAccount + NetworkPolicy to Harbor/OpenBao/Dependency-Track only.
- Pin Forgejo action installers (`cosign-installer`, `sbom-action`) by digest/SHA.
- Forgejo-native SLSA provenance for the Harbor path (no `attest-build-provenance` analog) —
  research item; Harbor images carry signature + CycloneDX SBOM but no build provenance.
