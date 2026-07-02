# RFC: Kyverno audit→enforce hardening

> Status: **Proposed** · Date: 2026-06-21 · Umbrella for [ADR-0033](../adr/adr-0033-kyverno-enforce-promotion-policy.md), [ADR-0034](../adr/adr-0034-approved-registries-stays-audit.md)

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
| `require-pod-probes` | ~18 | Safe after a first-party probe sweep; heavily waived already |
| `image-hygiene` | ~0 | Safe; reconcile its narrow namespaceSelector first |
| `image-supply-chain` | `require-approved-registries` ~103, `require-image-digest` ~25 | SPLIT — 2 clean rules now; digest later; approved-registries **stays Audit** |
| `rbac-least-privilege` | `disallow-wildcards-in-app-roles` ~40 | SPLIT — 4 clean RBAC rules now; wildcards after remediation |
| `workload-hardening` | forgejo 26 | ns-by-ns via overrides; needs resource-limit sweep |
| `workload-advanced-hardening` | SA-token / readonly-rootfs broad | SPLIT — 5 low-risk rules now; invasive rules stay Audit |
| `namespace-tenancy` | netpol/quota/labels | SPLIT — netpol-shape rules now; require-* after roadmap #13 |
| `secrets-observability-ops` | `require-prometheusrule-labels` ~49 | SPLIT — monitor-label rules after a label sweep |
| `image-verify` | unsigned webgrip | SPLIT — kyverno-images rule now; webgrip-images after signing proof |
| `image-verify-harbor` | — | **Stays Audit** (failurePolicy: Fail → Harbor/OpenBao SPOF) |
| `image-attestations` | — | Promote LAST, after image-verify |

### Gated wave sequence

The 14-wave order, gating, and prerequisites live in
[the implementation plan](rfc-kyverno-audit-enforce-hardening.md#waves) and ADR-0033. Each wave:
clean PolicyReport for the promoted rules (base **and** autogen = 0 unwaived) for ≥1 reconcile
cycle → CLI/chainsaw test added → `mise exec -- just kyverno-test` + flux-local green → flip → watch
one admission cycle. One wave per commit, spaced apart (the batched-rollout storage-collapse memory).

<a name="waves"></a>

| Wave | Policy / rules | Mechanism | Prereq |
|------|----------------|-----------|--------|
| 1 | `require-pod-probes` (whole) | Enforce | probe sweep on first-party apps |
| 2 | `image-hygiene` (whole) | Enforce | reconcile namespaceSelector to canonical set |
| 3 | `rbac-least-privilege` — 4 clean rules | split→Enforce | none |
| 4 | `image-supply-chain` — latest-tag + fully-qualified | split→Enforce | none |
| 5 | `namespace-tenancy` — netpol-shape rules | split→Enforce | none |
| 6 | `image-verify` — `verify-kyverno-images-keyless` | split→Enforce | none |
| 7 | `secrets-observability-ops` — monitor-label rules | split→Enforce | label sweep (49 PrometheusRules) |
| 8 | `workload-advanced-hardening` — 5 low-risk rules | split→Enforce | none |
| 9 | `workload-hardening` (4 rules) | overrides, ns-by-ns | resource-limit sweep; extend waivers (forgejo) |
| 10 | `rbac-least-privilege` — wildcards | merge→Enforce | narrow ~40 Roles / per-Role exceptions |
| 11 | `image-supply-chain` — `require-image-digest` | merge→Enforce | digest-pin first-party/platform images |
| 12 | `namespace-tenancy` — require-{netpol,quota,labels} | merge→Enforce | roadmap #13 |
| 13 | `image-verify` — `verify-webgrip-images` | merge→Enforce | confirm CI signing + digest pins |
| 14 | `image-attestations` | Enforce | SLSA+CycloneDX publishing confirmed |
| — | approved-registries, image-verify-harbor, advanced invasive rules, secrets PDB/topology/cm-keys | **stay Audit** | see ADR-0034 |

### Test harness fixes (prerequisite, shipped first)

- **Closed a latent hole:** `scripts/lib/kyverno-tests.sh` hardcoded a policy allowlist that
  silently omitted `workload-hardening`, `workload-advanced-hardening`, `secrets-observability-ops`,
  `image-hygiene`, `image-verify-harbor`, `storage-cnpg` — so those could be flipped to Enforce with
  zero CLI coverage and CI would stay green. Now discovered by kind (every policy + exception loads).
- **Added the gate:** `scripts/check-kyverno-test-coverage.sh` fails CI if an enforcing policy isn't
  exercised by a CLI test with a `fail` case (pass-case advisory; pre-existing untested
  `storage-cnpg-governance` is baselined as debt). Wired into `e2e.yaml` before the test run.

## Decisions

| ADR | Status | Decision |
|-----|--------|----------|
| [ADR-0033](../adr/adr-0033-kyverno-enforce-promotion-policy.md) | Proposed | Gated wave promotion via split + overrides; mandatory test-coverage gate before any Enforce merge. |
| [ADR-0034](../adr/adr-0034-approved-registries-stays-audit.md) | Proposed | `require-approved-registries` stays Audit; enforce only ever via Harbor proxy + admission mutate-rewrite. |

## Out of scope

- The Harbor pull-through proxy + the admission mutate-rewrite that would make
  `require-approved-registries` enforceable — its own future work
  ([RFC: Harbor proxy cache](rfc-harbor-proxy-cache.md)).
- Restricting Helm/OCI source registries (a follow-up noted in the supply-chain policy).

## Deferred items (from retired enforcement roadmap, 2026-07-02)

The earlier standalone enforcement-roadmap RFC was retired (it assumed keyless GHCR + an
enforceable registry allowlist, both since overturned — see
[supply-chain-pipeline](../general/supply-chain-pipeline.md) and ADR-0034). These are the
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
  runner variant is explicitly backbenched as P2 ([ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md) owns the rootless move).
- Scope the runner ServiceAccount + NetworkPolicy to Harbor/OpenBao/Dependency-Track only.
- Pin Forgejo action installers (`cosign-installer`, `sbom-action`) by digest/SHA.
- Forgejo-native SLSA provenance for the Harbor path (no `attest-build-provenance` analog) —
  research item; Harbor images carry signature + CycloneDX SBOM but no build provenance.
