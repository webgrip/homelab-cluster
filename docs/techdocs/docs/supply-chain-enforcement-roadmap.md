# Container Supply Chain: Future Enforcement Roadmap

> **Status:** Draft / Proposed — Audit-only today, no Enforce yet
> **Owner:** Ryan Grippeling (platform engineering, `ryan@webgrip.nl`)
> **Last reviewed:** 2026-06-17
> **Type:** Internal ADR/RFC. This is the authoritative plan for moving WebGrip's container
> supply-chain controls from `validationFailureAction: Audit` to `Enforce`, plus the
> registry-side, GitOps-side, and runner-side hardening that has to land alongside it.
> **Companion docs:** [Supply Chain Intelligence Pipeline](./supply-chain-pipeline.md) ·
> [Security Platform](./security-platform.md)

This document is deliberately specific to the architecture that exists in
`webgrip/infrastructure` (the two-tree CI) and `webgrip/homelab-cluster` (Kyverno + the
security platform) as of the review date. Where a capability is **not yet built or not yet
verified**, it is called out explicitly rather than assumed. Treat any "TODO / unverified"
marker as a real gap, not boilerplate.

---

## 1. Executive summary and trust model

### 1.1 The shape of the problem

WebGrip builds first-party container images in **one** source tree (`webgrip/infrastructure`,
`ops/docker/<image>/Dockerfile`) but publishes them through **two independent CI trees** to
**two registries** with **two different signing trust models**:

| Path | CI tree | Registry | Runner | Signing | Provenance |
|---|---|---|---|---|---|
| Public | `.github/workflows/*` | `ghcr.io/webgrip/*` | GitHub-hosted `ubuntu-latest` | cosign **keyless** (Fulcio + Rekor) via GitHub OIDC | SLSA build provenance (`actions/attest-build-provenance`) + Trivy SARIF → GitHub Security |
| In-cluster | `.forgejo/workflows/*` | `harbor.webgrip.dev/webgrip/*` (LAN-only) | in-cluster `forgejo-runner` (`runs-on: docker`, privileged DinD) | cosign **keyed** via OpenBao **Transit** (`cosign-webgrip`, ECDSA-P256) | **none yet** (no SLSA on the Forgejo path); CycloneDX SBOM attestation only |

This is a **dual-publish migration**: GHCR keeps running untouched while Harbor comes online.
Both paths build from the same Dockerfiles and are triggered by the same release-tag format
`<image>-v<version>` (e.g. `helm-deploy-v1.2.3`).

> **Ground-truth correction:** the brief references "11 images." The repo currently contains
> **10** image directories under `ops/docker/`: `act-runner`, `github-runner`, `helm-deploy`,
> `mkdocs-runner`, `php-ci-runner`, `playwright-runner`, `rust-ci-runner`, `rust-releaser`,
> `techdocs-builder`, `techdocs-runner`. The enforcement scope below is "all 10" — re-confirm
> the count before flipping any glob to Enforce, because a single un-re-released image becomes
> a cluster-wide admission failure.

### 1.2 The two trust models, precisely

The whole point of the enforcement work is that the cluster trusts an **identity that produced
the artifact**, not a tag or a digest in isolation. The two paths anchor that identity
differently:

**GHCR — keyless / transparency-log-anchored.** The trust root is the *Sigstore Fulcio CA + the
GitHub OIDC issuer*. There is no long-lived private key anywhere. At sign time the GitHub
workflow exchanges its OIDC token for a short-lived Fulcio cert whose SAN encodes the exact
workflow path. Kyverno (`image-verify-audit`) trusts:

- **Issuer:** `https://token.actions.githubusercontent.com`
- **Subject (regex):** `^https://github\.com/webgrip/infrastructure/\.github/workflows/on_release_published\.yml@refs/tags/.+$`
- **Transparency log:** `rekor.sigstore.dev` (public, append-only — gives independent,
  third-party proof the signature existed at a point in time)

So "trusted" means: *this digest was signed by the `on_release_published.yml` workflow of
`webgrip/infrastructure`, running on a release tag, and that event is logged in Rekor.* Nothing
else under `ghcr.io/webgrip/*` is trusted — not a manual `cosign sign`, not a different
workflow, not a branch build.

**Harbor — keyed via OpenBao Transit.** The trust root is a *single asymmetric key whose private
half lives in OpenBao and never leaves it*. cosign calls `transit/sign` over the OpenBao API
(`hashivault://cosign-webgrip`); the runner only ever holds a short-lived OpenBao token, never
the key. Kyverno (`image-verify-harbor-audit`) trusts the **public half**, read from the
committed `cosign-webgrip-pub` ConfigMap (`security` namespace, `cosign.pub` PEM).

The keyed path has no Fulcio and **no Rekor / transparency log** — there is no independent
record that a signature happened. The "who is allowed to sign" guarantee is therefore *not* in
the signature material; it is enforced **at sign time** by the OpenBao JWT auth method.

### 1.3 Why per-workflow OIDC claims are load-bearing

On the Forgejo/Harbor path the authorization to use the Transit key is gated by OpenBao's JWT
auth method (`auth/forgejo`), role `cosign-signer`, with `bound_claims`:

```
{ repository: webgrip/infrastructure, event_name: release, ref: refs/tags/* }
```

This is the keyed-path equivalent of the GHCR subject regex. Because Forgejo mints a **per-job**
OIDC token (the job sets `enable-openid-connect: true`) whose claims include `repository`,
`event_name`, and `ref`, only a job that is *actually* a release on a tag in
`webgrip/infrastructure` can exchange its token for an OpenBao token scoped to
`transit/sign` on `cosign-webgrip`. A push build, a PR build, a different repo, or a branch ref
all fail the claim binding and cannot sign — even though they run on the same runner.

> **Critical corollary:** Forgejo Actions OIDC is **disabled for fork PRs**. A fork PR therefore
> cannot mint a signer token at all. This is the primary defense for the privileged DinD runner
> (see §7) — the runner's blast radius does *not* include the signing key, because the key is in
> OpenBao and only a tag-event token unlocks it.

### 1.4 One-time break-glass prerequisites (blocks the entire Harbor path)

OpenBao runs with **no live root token** (`generate-root` is a break-glass ceremony). The
`config-admin` identity used by day-to-day automation **cannot mount secret engines or auth
methods**. Therefore the following are one-time, break-glass `generate-root` operations and are
hard prerequisites for *any* Harbor-side enforcement:

1. Enable the **Transit** secrets engine and create key `cosign-webgrip` (ECDSA-P256).
2. Enable the **JWT** auth method at `auth/forgejo`, pointed at Forgejo's OIDC discovery, and
   create role `cosign-signer` with the bound claims above and a policy granting
   `transit/sign` (sign-only) on the key.
3. (Automatic — no manual paste) the `cosign-pubkey` CronJob reads the Transit public key and
   publishes it to the `cosign-webgrip-pub` ConfigMap. On a fresh rebuild this is fully hands-off
   (init.sh creates the key, the CronJob publishes it); on the existing cluster it publishes once
   the break-glass (steps 1-2) has created the key.

Until all three are done, the Harbor signing path produces nothing verifiable and
`image-verify-harbor-audit` will (correctly) report failures in Audit mode.

---

## 2. Current posture — every Kyverno supply-chain policy

All policies below live in
`homelab-cluster/kubernetes/apps/kyverno/policies/app/` and are wired into the
`kustomization.yaml` in that directory. Kyverno is **v3.8.1** running in the `security`
namespace. **Every supply-chain policy is `validationFailureAction: Audit` today** — nothing in
this table blocks admission yet. (The `flux-governance-enforce` and
`pod-security-baseline-enforce` policies *are* Enforce, but they govern Flux sources / PSS, not
image trust, and are out of scope here except where noted.)

| Policy (file) | Scope (image glob / target) | What it verifies | Trust anchor | Mode |
|---|---|---|---|---|
| `image-verify-audit` — rule `verify-webgrip-images` | `ghcr.io/webgrip/*` | cosign signature present; `verifyDigest: true`; `mutateDigest: false` | keyless: issuer `token.actions.githubusercontent.com`, subject regex `…/on_release_published.yml@refs/tags/.+`, Rekor `rekor.sigstore.dev` | **Audit** |
| `image-verify-audit` — rule `verify-kyverno-images-keyless` | `ghcr.io/kyverno/*` (only in `security` ns) | cosign keyless signature on upstream Kyverno images | keyless: `kyverno/kyverno` GH workflows | **Audit** |
| `image-verify-harbor-audit` — rule `verify-webgrip-harbor-images` | `harbor.webgrip.dev/webgrip/*` | cosign signature **and** CycloneDX attestation, both verified against the Transit public key; SBOM must have `components > 0` | keyed: `cosign-webgrip-pub` ConfigMap PEM; needs `harbor-pull` dockerconfigjson to fetch from private LAN registry | **Audit** |
| `image-attestations-audit` — rule `verify-github-slsa-provenance` | `ghcr.io/webgrip/*` | SLSA provenance attestation (`https://slsa.dev/provenance/v1`); requires `buildDefinition.buildType == https://actions.github.io/buildtypes/workflow/v1` | keyless (same subject regex as above) | **Audit** |
| `image-attestations-audit` — rule `verify-cyclonedx-sbom` | `ghcr.io/webgrip/*` | CycloneDX SBOM attestation (`https://cyclonedx.org/bom`); requires `Data.bomFormat == CycloneDX` | keyless (same subject regex) | **Audit** |
| `image-supply-chain-audit` — `require-image-digest` | application namespaces (NotIn system list) | every container/init/ephemeral image pinned `*@sha256:*` | n/a (hygiene) | **Audit** |
| `image-supply-chain-audit` — `disallow-latest-tag-even-with-digest` | application namespaces | reject `*:latest@*` even when digest-pinned | n/a | **Audit** |
| `image-supply-chain-audit` — `require-approved-registries` | application namespaces | image must match an allowlisted registry (ghcr.io, docker.io, quay.io, registry.k8s.io, mirror.gcr.io, gcr.io, public.ecr.aws, mcr.microsoft.com) | n/a (allowlist) | **Audit** |
| `image-supply-chain-audit` — `require-fully-qualified-images` | application namespaces | reject bare/short image names with no registry host | n/a | **Audit** |
| `image-hygiene-audit` — `require-image-tag` | application namespaces | every image carries a tag | n/a | **Audit** |
| `image-hygiene-audit` — `validate-image-tag` | application namespaces | reject mutable `:latest` | n/a | **Audit** |

> **Note on `require-approved-registries`:** the allowlist **does not yet include
> `harbor.webgrip.dev`.** As soon as a real workload pulls from Harbor in an application
> namespace, this rule will report an audit failure. Adding Harbor to the allowlist is a
> prerequisite for the Harbor registry-allowlist phase (§3, Phase E) — see the checklist.

Supporting objects (not policies, but required for the Harbor policy to function):

- `cosign-webgrip-pub.configmap.yaml` — public key (currently a **placeholder**).
- `harbor-pull.externalsecret.yaml` — `ExternalSecret` rendering a `kubernetes.io/dockerconfigjson`
  Secret `harbor-pull` in `security` from OpenBao `harbor/robot-webgrip` (so Kyverno can pull
  manifests + signatures from the private registry).

---

## 3. Phased Audit → Enforce migration

The migration is **per-control**, not per-policy-file, because a single file
(`image-attestations-audit`) contains two independently-promotable rules, and the two registries
mature on different timelines. Phases are ordered by confidence and blast radius: signatures
first (highest confidence, broadest existing coverage), registry allowlist last (touches every
third-party workload).

**Global readiness gate for every phase** — applies before any flip:

- Audit findings for the rule are **zero** for in-scope images for a sustained window (≥ 7 days,
  ideally one full Renovate cycle), confirmed from PolicyReports (§3.7).
- A documented **rollback** is one revert commit away and Flux can reconcile it in minutes.
- `failurePolicy: Fail` + `webhookTimeoutSeconds: 30` are already set on the verify policies — be
  aware that under Enforce a Kyverno outage or a slow registry now blocks admission (see §3.8).

### Phase A — Signature required (GHCR)

**Promote:** `image-verify-audit` rule `verify-webgrip-images` → Enforce.

**Gates / prerequisites:**

- [ ] All **10** `ghcr.io/webgrip/*` images currently *running* in the cluster have been
      re-released through `on_release_published.yml` on a tag, so each carries a keyless
      signature with the expected subject. (Older images built before signing existed will be
      *rejected* — re-release or scope them out with a time-boxed exception.)
- [ ] Spot-verify from a workstation:
      `cosign verify --certificate-identity-regexp '…on_release_published.yml@refs/tags/.+' --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/webgrip/<img>@sha256:<digest>`
- [ ] Cluster egress to `rekor.sigstore.dev` and the Fulcio root works from the Kyverno pods
      (keyless verification fetches/validates the transparency-log entry). **Verify this** — a
      LAN-only / egress-filtered cluster can silently fail keyless verification.
- [ ] All `ghcr.io/webgrip/*` deployments are **digest-pinned** (Phase D need not be enforced
      yet, but in practice signature verification by tag is fragile; pin first).

**Decide `mutateDigest`:** currently `false` (see §4.3). Keep `false` for Phase A — we want to
verify exactly what was deployed, and digests should already be pinned.

### Phase B — SBOM attestation required

**Promote (two registries, independently):**

- GHCR: `image-attestations-audit` rule `verify-cyclonedx-sbom` → Enforce.
- Harbor: `image-verify-harbor-audit` (its attestation block is part of the same rule as the
  signature, so promoting the Harbor policy enforces signature *and* CycloneDX together).

**Gates — GHCR side:**

- [ ] Every in-scope image's release produced a `cosign attest --type cyclonedx` record (it does
      today via `.github/actions/cosign-sign-attest`, but re-released images only — older ones lack it).
- [ ] `cosign verify-attestation --type cyclonedx …` succeeds for each.

**Gates — Harbor side (all of these block):**

- [ ] **Break-glass complete** (§1.4): Transit engine + key + `auth/forgejo` JWT role exist.
- [ ] `cosign-webgrip-pub` ConfigMap **populated** with the real PEM (placeholder removed).
- [ ] `harbor-pull` ExternalSecret successfully rendering — Kyverno can authenticate to
      `harbor.webgrip.dev` (LAN-only) and pull manifests/signatures. Confirm the
      `harbor/robot-webgrip` creds in OpenBao and the ESO sync status.
- [ ] **Kyverno can reach Harbor** on the LAN (NetworkPolicy / routing) and **reach OpenBao**
      only indirectly — note Kyverno verifies against the *static public key*, so it does **not**
      need OpenBao at admission time; OpenBao reachability is a *runner-side* requirement (the
      runner needs OpenBao OIDC discovery + sign at *build* time, not Kyverno at admission).
- [ ] Every Harbor image in scope has been signed+attested by a release job (i.e. released after
      break-glass). Pre-break-glass Harbor images are unsigned and will be rejected.

> Phase B for Harbor is effectively "signature + SBOM in one flip" because the policy couples
> them. There is no signature-only intermediate for Harbor — accept that or split the policy
> into two rules first.

### Phase C — SLSA provenance required (GHCR only)

**Promote:** `image-attestations-audit` rule `verify-github-slsa-provenance` → Enforce.

**Gates:**

- [ ] Every in-scope GHCR image carries a SLSA v1 provenance attestation with
      `buildType == https://actions.github.io/buildtypes/workflow/v1` (produced by
      `actions/attest-build-provenance@v2`, `push-to-registry: true`). Re-released images only.
- [ ] `cosign verify-attestation --type slsaprovenance …` or
      `gh attestation verify oci://… --owner webgrip` succeeds.

**Explicitly out of scope for this phase:** Harbor. **The Forgejo path does not generate SLSA
provenance at all** — `actions/attest-build-provenance` has no Forgejo analog and the
`.forgejo/actions/cosign-sign-attest` action intentionally omits it. There is therefore **no
Harbor SLSA rule to promote** and one must not be authored that would match
`harbor.webgrip.dev/webgrip/*`, or it would fail every Harbor image. Closing this gap is a
roadmap item (§8), not an enforcement flip.

### Phase D — Digest pinning enforced

**Promote:** `image-supply-chain-audit` rule `require-image-digest` (and pair it with
`disallow-latest-tag-even-with-digest`) → Enforce, for application namespaces.

**Gates:**

- [ ] PolicyReports show zero `require-image-digest` audit failures across all *non-excepted*
      application namespaces.
- [ ] Renovate is configured to pin digests (or HelmRelease/kustomize image overrides are pinned
      manually) so newly-rendered manifests stay compliant — otherwise the next chart bump
      reintroduces a tag-only reference and blocks the deploy.
- [ ] The `exception-third-party-image-supply-chain` PolicyException (§4.1) already covers the
      known offenders (backstage, drawio, excalidraw, freshrss, invoiceninja, minecraft, n8n,
      sparkyfitness). Re-confirm the list is current and each has a migration note + review date.

This phase is **independent of signing** and can be promoted early — it is pure hygiene and the
exception inventory already exists. Good candidate to enforce *before* Phase A if you want a
low-risk first win.

### Phase E — Registry allowlist enforced

**Promote:** `image-supply-chain-audit` rules `require-approved-registries`,
`require-fully-qualified-images` → Enforce; and `image-hygiene-audit` rules → Enforce.

**Gates:**

- [ ] **Add `harbor.webgrip.dev` to the `require-approved-registries` anyPattern list** —
      currently absent. Without this, the first real Harbor workload in an app namespace is
      rejected under Enforce.
- [ ] Inventory every registry in use cluster-wide (Trivy Operator's running-image list or the
      `trivy-sbom-uploader` output is the source of truth) and confirm each is either on the
      allowlist or covered by an exception.
- [ ] Exceptions for third-party charts that hardcode Docker Hub are in place and reviewed.

This is **last** because it has the widest blast radius — it touches every workload's image
reference, including operator/system images, and the allowlist is easy to get subtly wrong.

### 3.6 Recommended ordering (TL;DR)

```
Phase D (digest pinning) ─► Phase A (GHCR signature) ─► Phase C (GHCR SLSA)
                                    │                          │
                                    └► Phase B (GHCR SBOM) ─────┘
Harbor break-glass ─► Phase B-Harbor (signature + SBOM, coupled)
Phase E (registry allowlist) ── last, after Harbor is on the allowlist
```

### 3.7 Detecting readiness from PolicyReports

Audit-mode failures land in `PolicyReport` (namespaced) and `ClusterPolicyReport` (cluster-scoped)
objects, summarized by Policy Reporter and the Kyverno Grafana dashboards ("Kyverno / Policy
Violations", "Kyverno / Policy Insights").

```bash
# All failing results for a given policy, cluster-wide:
kubectl get clusterpolicyreport,policyreport -A -o json \
  | jq -r '.items[].results[]
      | select(.policy=="image-verify-audit" and .result=="fail")
      | "\(.resources[0].namespace)/\(.resources[0].name)  \(.rule)  \(.message)"'

# Quick pass/fail tally per policy:
kubectl get clusterpolicyreport,policyreport -A -o json \
  | jq -r '.items[].results[] | "\(.policy)\t\(.result)"' | sort | uniq -c
```

Readiness signal: the count of `fail` for the rule you intend to promote is **0** and stays 0
across a full reconcile + Renovate cycle. The existing PrometheusRule (`prometheusrule.yaml`) and
the SLO "Kyverno high/critical violations > 0" alert (see security-platform doc) give you the
same signal in Grafana/Alertmanager. **Do not flip on a momentary zero** — a not-yet-deployed
image won't show a violation until it's admitted.

> **`background: false` caveat:** the three `verifyImages` policies run `background: false`
> (image verification needs admission context). They therefore evaluate **only at admission**,
> not on a background scan of already-running pods. A pod admitted *before* the policy existed
> won't appear in PolicyReports until it is re-admitted (restart/reschedule). To force a true
> readiness picture, roll the relevant Deployments (or wait for natural churn) before trusting a
> zero count.

### 3.8 Rollback

Every flip is one field (`validationFailureAction: Audit` ↔ `Enforce`) in one file, reconciled by
Flux. Rollback = revert the commit; Flux restores Audit within its reconcile interval.

- For an **emergency** (admission is blocking a needed deploy and you can't wait for Flux): patch
  the live policy `kubectl patch clusterpolicy <name> --type merge -p '{"spec":{"validationFailureAction":"Audit"}}'`
  then immediately revert in Git so Flux doesn't fight you / re-enforce.
- Because `failurePolicy: Fail`, if the Kyverno webhook itself is unhealthy under Enforce,
  **all** matching admissions fail closed. Keep a documented break-glass to scale Kyverno's
  admission webhook out of the path (delete/ignore the `ValidatingWebhookConfiguration`) as a
  last resort. Prefer this over leaving Enforce on a flaky webhook.

---

## 4. Migration-tail handling: exceptions, selectors, mutateDigest

### 4.1 PolicyExceptions (the governed escape hatch)

The repo already uses `kyverno.io/v2` `PolicyException` objects, all living in the `security`
namespace, all carrying `labels.owner` and a `policies.kyverno.io/description` migration note
(e.g. `exception-third-party-image-supply-chain` excepts 8 named third-party Deployments from the
four `image-supply-chain-audit` rules, "reviewed quarterly"). This is the right pattern; extend
it, don't invent a new one.

Guidance for the enforcement tail:

- **Scope exceptions to the narrowest unit** — `kind` + `namespace` + `name`, as the existing
  ones do, never a bare namespace wildcard. Note the existing exceptions target `Deployment`
  with `autogen-*` rule names (because the `pod-policies.kyverno.io/autogen-controllers`
  annotation generates per-controller rules); match that naming or the exception silently won't
  apply.
- **Every exception gets:** `owner`, a description with the **migration path**, and a **review
  date / expiry intent**. An exception without an expiry is permanent policy drift.
- **For signature/attestation enforcement**, prefer excepting a *namespace of legacy workloads*
  over excepting individual unsigned `webgrip` images — an unsigned first-party image should be
  re-released, not permanently excepted.

### 4.2 namespaceSelectors

The hygiene/supply-chain policies already use a shared `&applicationNamespaces` anchor — a
`NotIn` list of system namespaces (`kube-system`, `flux-system`, `cnpg-system`, `security`, etc.).
Keep that contract:

- System/operator namespaces are **out of scope** for digest/registry hygiene by design.
- The `verifyImages` policies (`image-verify-audit`, `image-verify-harbor-audit`) match on the
  **image glob**, not a namespace selector — so they apply in *every* namespace where a
  `webgrip` image runs, including `security`. The Kyverno upstream-image rule
  (`verify-kyverno-images-keyless`) is the one that's namespace-scoped (`security` only).
- When you add Harbor workloads, decide deliberately whether they belong in the
  `&applicationNamespaces` scope and whether Harbor needs to be added to the registry allowlist
  (§3 Phase E) before those namespaces go to Enforce.

### 4.3 mutateDigest considerations

All three `verifyImages` policies set `mutateDigest: false` and `verifyDigest: true`. Implications:

- `verifyDigest: true` + `mutateDigest: false` means **the manifest must already reference a
  digest** (or a tag that Kyverno resolves) and Kyverno verifies the signature against it —
  Kyverno will **not** rewrite a tag into a digest for you.
- Setting `mutateDigest: true` would have Kyverno resolve a tag to a digest and pin it into the
  Pod spec at admission. That is convenient but: (a) it mutates workloads (surprising in GitOps —
  the running spec diverges from Git), and (b) it resolves the digest *at admission time*, which
  can pin a different image than CI signed if the tag moved. **Recommendation: keep
  `mutateDigest: false`** and enforce digest pinning at the source (Phase D + Renovate), so Git
  remains the single source of truth and there's no admission-time tag resolution.

---

## 5. OCI Helm chart verification via Flux cosign

Kyverno's image policies only ever see **Pod container images**. They do **not** see the Helm
charts Flux pulls, nor the `OCIRepository` artifacts Flux reconciles. A malicious or swapped
chart could therefore render perfectly-signed images while the chart logic itself is untrusted.
That gap is closed (only) by **Flux's own signature verification** via `spec.verify`.

**Current state (verified):** No `OCIRepository` or `HelmRelease` in the repo uses
`spec.verify.provider: cosign` today. The `flux-governance-enforce` policy *does* already enforce
`OCIRepository` digest pinning (`spec.ref.digest: sha256:*`, Enforce) and steers HelmReleases
toward `OCIRepository` chartRefs — so the pinning foundation exists, but chart *signature*
verification does not. This section is therefore **forward-looking**.

**For first-party OCI charts** (if/when WebGrip publishes Helm charts to GHCR or Harbor):

1. Sign the chart artifact in CI the same way images are signed:
   - GHCR keyless: `cosign sign ghcr.io/webgrip/charts/<chart>@sha256:<digest>` (same OIDC
     identity as images → reuse the GHCR trust anchor).
   - Harbor keyed: `cosign sign --key hashivault://cosign-webgrip harbor.webgrip.dev/webgrip/charts/<chart>@<digest>`.
2. Distribute the public key to Flux as a Secret (Flux verifies against a `.pub` key for keyed,
   or against keyless identities for cosign keyless):

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: example-chart
  namespace: flux-system
spec:
  interval: 1h
  url: oci://harbor.webgrip.dev/webgrip/charts/example
  ref:
    digest: sha256:...            # already required by flux-governance-enforce
  verify:
    provider: cosign
    secretRef:
      name: cosign-webgrip-pub-flux   # holds cosign.pub; mirror the security-ns ConfigMap
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: example
spec:
  chartRef:
    kind: OCIRepository
    name: example-chart
```

3. Flux refuses to reconcile a chart whose signature does not verify — failing **before** any
   Pod reaches Kyverno. This is the chart-layer complement to Kyverno's image layer.

**Notes / pitfalls:**

- The keyless variant uses `spec.verify.matchOIDCIdentity` (issuer + subject regex) — reuse the
  exact GHCR contract from §1.2.
- The public key for keyed verification is the **same** `cosign-webgrip` public half already in
  `cosign-webgrip-pub`; create a Secret in `flux-system` (Flux can't read a ConfigMap in
  `security`). Keep them in sync, or template both from OpenBao.
- This is a §8/roadmap item, not part of the Audit→Enforce flips — there are no charts to sign
  yet.

---

## 6. Harbor-side controls to layer in

Harbor is more than a registry; it has policy primitives the GHCR path doesn't. Configure these
on the `webgrip` Harbor project to make the in-cluster path defense-in-depth rather than "a place
images land." None of these are configured-as-code in the repo today — they are Harbor project
settings (TODO: capture as Terraform/Harbor API automation so they're reproducible).

| Control | What to set | Why it matters here |
|---|---|---|
| **CVE-severity gating on pull** | Project → "Prevent vulnerable images from running", threshold e.g. `High`. Harbor's Trivy scanner gates `docker pull`. | Stops a known-Critical image being pulled even if Kyverno would admit it. Complements (does not replace) Kyverno + Trivy Operator. Watch for "unscanned image" edge cases — decide whether unscanned = blocked. |
| **Tag immutability** | Immutability rule on `webgrip/**` (at least on release tags `*-v*` and `latest`). | The keyed signing path has **no Rekor**; tag immutability is a key part of preventing the tag-mutation attack that Rekor would otherwise help detect. Sign-by-digest (already done in the action) + immutable tags together close it. |
| **Project quota** | Storage quota on the `webgrip` project. | Prevents a runaway/poisoned build loop from filling LAN storage; bounds blast radius of a compromised runner pushing junk. |
| **Robot-account least privilege** | The CI robot (`robot$webgrip+ci`) should have **push** on `webgrip/**` only; the Kyverno pull robot (`harbor/robot-webgrip` → `harbor-pull`) should be **pull-only**. Separate robots, separate scopes, short-lived tokens where possible. | The pull credential lives in-cluster (`harbor-pull` Secret in `security`); if it leaks it must not grant push. The push robot lives in Forgejo secrets; it must not grant project admin. |
| **Retention / GC** | Retention policy (keep last N tags + all signed release tags) + scheduled garbage collection. | Keeps signed release artifacts while pruning prerelease/`latest` churn. Ensure retention never deletes a digest that a running Pod (or a signature/attestation) still references. |
| **Scanner cadence** | Auto-scan on push + periodic re-scan. | New CVEs land after build; periodic re-scan keeps the pull-gate decision current. |

> **Sequencing:** turn on **CVE pull-gating last** and in warn/observe mode first — it can block
> legitimate pulls (including the cluster pulling its own runner images) the moment a new CVE is
> published. Tag immutability and robot least-privilege are safe to enable immediately.

---

## 7. Runner threat model and hardening

### 7.1 The risk

The Harbor path runs on the **in-cluster `forgejo-runner` with `runs-on: docker` and privileged
DinD**. Privileged DinD means the build job has a Docker daemon with effectively host-level
capability inside the cluster. A compromised build (malicious dependency, poisoned base image,
PR that runs arbitrary code) on a privileged runner is a serious escalation primitive: container
escape → node → cluster.

### 7.2 What already constrains it (do not lose these)

- **The signing key is not on the runner.** It's in OpenBao Transit; the runner only ever holds a
  short-lived OpenBao token obtained via OIDC. Even full runner compromise does **not** yield the
  `cosign-webgrip` private key.
- **Only tag-event release jobs can sign.** The `auth/forgejo` role binds
  `event_name: release` + `ref: refs/tags/*` + `repository: webgrip/infrastructure`. A push/PR
  build on the same runner cannot mint a signer token.
- **Forgejo OIDC is disabled for fork PRs** → a fork PR literally cannot obtain a signer token
  and cannot sign. This is the single most important property: untrusted code (fork PRs) is
  structurally barred from the signing path.

### 7.3 Hardening to add

1. **Protected tags / gated release trigger.** The signature gate is "is this a tag event," so
   *who can create release tags* is the real authorization boundary. Configure Forgejo
   **protected tags** on `*-v*` so only trusted maintainers can push/create release tags. Without
   this, anyone who can push a tag can trigger a signed release.
2. **No fork-PR signing — confirm, don't assume.** Verify that the release workflow only triggers
   on `release: published` (it does) and that `enable-openid-connect` jobs never run on
   `pull_request` from forks. Add a guard if any future workflow adds a fork-triggered path.
3. **Move off privileged DinD where possible.** Options, in rough order of effort:
   - **Rootless DinD / sysbox** runner — removes `--privileged`, big blast-radius reduction, some
     compatibility cost for buildx multi-arch.
   - **Buildkit-as-a-service** (a shared, locked-down buildkitd) so build jobs don't each get a
     privileged daemon.
   - **LXC / dedicated-VM runner** off the cluster entirely for the privileged build, so a
     container escape lands in a throwaway VM, not a cluster node. **[DEFERRED — backbenched]**:
     explicitly not pursued now; revisit as a P2 hardening item once Harbor enforcement is live.
     The `lxc://` runner backend gives VM-like per-job isolation but needs LXC on the host and
     elevated privileges, so it's a node-prep project rather than a config change.
4. **Scope the runner's ServiceAccount and NetworkPolicy.** The runner needs to reach Harbor +
   OpenBao + Dependency-Track and nothing else. A NetworkPolicy that denies lateral movement
   limits a compromised runner. Confirm the runner SA has no cluster RBAC beyond what the runner
   controller needs.
5. **Pin actions by SHA.** The GHCR action already pins `actions/checkout` and
   `actions/upload-artifact` by commit SHA; the Forgejo action pins cosign/syft by version but
   uses floating tags for some installers (`sigstore/cosign-installer@v3`,
   `anchore/sbom-action/download-syft@v0`). Pin these by digest/SHA to remove a supply-chain
   vector into the runner itself.

---

## 8. Residual risks and explicit non-coverage

These are known, accepted-for-now gaps. Listing them is the point — none should be a surprise
later.

1. **No transparency log for Harbor keyed signing.** GHCR signatures are in Rekor (independent,
   third-party, append-only proof). Harbor keyed signatures are **not** — there is no external
   record that a signature occurred. Mitigations are *tag immutability* + *sign-by-digest*
   (both in place / planned), but the property "I can prove after the fact that this signature
   existed at time T without trusting our own infra" does **not** hold for Harbor. Accept, or
   stand up a private Rekor instance (large effort; out of scope).
2. **Transit key rotation has no documented story.** `cosign-webgrip` is a single ECDSA-P256 key
   created by break-glass. There is no rotation runbook, and `cosign-webgrip-pub` is a single-key
   ConfigMap. On rotation: OpenBao Transit supports key versions, but Kyverno verifies against a
   *static* public key — rotating requires (a) bumping the Transit key version, (b) updating the
   ConfigMap PEM (and any Flux mirror), (c) deciding whether old signatures (old key version)
   should still verify. **TODO: write the rotation runbook before enforcing**, otherwise a future
   rotation is a cluster-wide admission outage.
3. **No SLSA provenance on the Forgejo/Harbor path.** Documented in §3 Phase C — Harbor images
   have signature + CycloneDX SBOM but **no build provenance**. There is no "who/where/which-commit
   built this" attestation for Harbor artifacts. Closing it needs a Forgejo-native provenance
   generator (no `actions/attest-build-provenance` analog exists) — research item.
4. **Kyverno keyless verification depends on public Sigstore reachability.** Phase A/B/C (GHCR)
   require Kyverno egress to Fulcio root + Rekor. If that egress is ever filtered, keyless
   verification under Enforce fails closed. **Verify and document this dependency.**
5. **`cosign-webgrip-pub` is reconciled, not pasted.** The `cosign-pubkey` CronJob publishes it
   from OpenBao Transit; until the Transit key exists (break-glass on the live cluster, automatic on
   a fresh rebuild) the ConfigMap is absent and the Harbor verify policy reports errors (Audit-only,
   non-blocking).
6. **Dependency-Track upload is fail-soft.** The Forgejo action uploads SBOMs to DT
   "fail-soft" (never fails the build). So a green release does **not** guarantee DT has the
   SBOM — don't treat DT presence as an enforcement signal; it's posture, not a gate.
7. **Background scans don't cover verifyImages.** Already-running pods admitted before a policy
   existed are invisible to PolicyReports until re-admission (§3.7). A "clean" report can hide
   legacy workloads.
8. **Helm charts are unverified by anything today** (§5). Kyverno can't see them and Flux
   `spec.verify` isn't configured. A swapped chart is currently only mitigated by `OCIRepository`
   digest pinning, not signature verification.
9. **Not covered at all:** image base-layer provenance beyond what Syft records; runtime
   attestation (the SBOM describes build time, not what's loaded at runtime — Trivy Operator
   covers running-state separately); VEX/exploitability gating (DT has VEX but it's not wired into
   admission).

---

## 9. Prioritized checklist (P0 / P1 / P2)

Effort: **S** ≈ < ½ day, **M** ≈ ½–2 days, **L** ≈ multi-day / cross-system.

### P0 — unblockers and zero-risk wins (do first)

| # | Measure | Effort | File(s) / system |
|---|---|---|---|
| 1 | **Break-glass**: enable OpenBao Transit engine, create `cosign-webgrip` key, enable `auth/forgejo` JWT method + `cosign-signer` role with bound claims. | M | OpenBao (one-time `generate-root` ceremony) |
| 2 | Populate `cosign-webgrip-pub` with the real Transit public PEM (remove placeholder). | S | `kyverno/policies/app/cosign-webgrip-pub.configmap.yaml` |
| 3 | Confirm `harbor-pull` ExternalSecret renders and Kyverno can pull from Harbor on the LAN. | S | `kyverno/policies/app/harbor-pull.externalsecret.yaml` (verify) |
| 4 | Configure **Forgejo protected tags** on `*-v*`; confirm fork-PR OIDC is disabled. | S | Forgejo project settings |
| 5 | Harbor project: **tag immutability** + **robot least-privilege** (split push vs pull robots) + **storage quota**. | M | Harbor project settings (capture as IaC, TODO) |
| 6 | Verify Kyverno egress to Rekor/Fulcio (needed for any GHCR keyless Enforce). | S | cluster NetworkPolicy / egress (verify + document) |

### P1 — first enforcement flips (after P0, gated on clean PolicyReports)

| # | Measure | Effort | File(s) |
|---|---|---|---|
| 7 | Re-release all 10 `ghcr.io/webgrip/*` running images so each is signed/attested. | M | `webgrip/infrastructure` releases |
| 8 | **Phase D**: enforce `require-image-digest` + `disallow-latest-tag-even-with-digest` (app namespaces; lowest risk, can go first). | S | `kyverno/policies/app/image-supply-chain-audit.yaml` |
| 9 | **Phase A**: enforce `image-verify-audit/verify-webgrip-images` (GHCR signature). | S | `kyverno/policies/app/image-verify-audit.yaml` |
| 10 | **Phase B-GHCR**: enforce `verify-cyclonedx-sbom`. | S | `kyverno/policies/app/image-attestations-audit.yaml` |
| 11 | **Phase B-Harbor**: enforce `image-verify-harbor-audit` (signature + CycloneDX, coupled) — only after P0 #1–3 + Harbor re-releases. | S | `kyverno/policies/app/image-verify-harbor-audit.yaml` |
| 12 | **Add `harbor.webgrip.dev` to `require-approved-registries`** (prereq for Phase E and for any Harbor app workload). | S | `kyverno/policies/app/image-supply-chain-audit.yaml` |
| 13 | Re-confirm / re-date the `exception-third-party-image-supply-chain` inventory before Phase D/E. | S | `kyverno/policies/app/exception-third-party-images.yaml` |

### P2 — deeper hardening and gap-closing

| # | Measure | Effort | File(s) / system |
|---|---|---|---|
| 14 | **Phase C**: enforce `verify-github-slsa-provenance` (GHCR). | S | `kyverno/policies/app/image-attestations-audit.yaml` |
| 15 | **Phase E**: enforce registry allowlist + fully-qualified + image-hygiene rules (last; widest blast radius). | M | `image-supply-chain-audit.yaml`, `image-hygiene-audit.yaml` |
| 16 | Harbor **CVE-severity pull-gating** (start in observe/warn). | M | Harbor project settings |
| 17 | **Transit key rotation runbook** — ✅ DONE: zero-downtime dual-key overlap, emergency path, rollback. | — | [`runbooks/cosign-transit-key-rotation.md`](runbooks/cosign-transit-key-rotation.md) |
| 18 | Move runner **off privileged DinD** (rootless/sysbox/buildkitd or LXC/VM). | L | `forgejo-runner` config + `ops/docker/*-runner` |
| 19 | Pin Forgejo action installers (`cosign-installer`, `sbom-action`) by digest/SHA. | S | `.forgejo/actions/cosign-sign-attest/action.yml` |
| 20 | **Forgejo-native SLSA provenance** for the Harbor path (research → implement). | L | `.forgejo/actions/cosign-sign-attest` + a new attestation step |
| 21 | **Flux `spec.verify` cosign** on first-party OCI Helm charts — Kyverno can't gate charts (they're not Pod images). ⚠️ Flux verify is **enforce-only**: a failed verify sets `Ready=False` + alerts + withholds the artifact; there is **no audit mode**. So for an *audit* phase, run a **side-channel CronJob** that `cosign verify`s the charts → Alertmanager, and add `spec.verify` to the source only when ready to enforce. | M | side-channel CronJob + PrometheusRule (audit); `OCIRepository`/`HelmRelease` `spec.verify` + `flux-system` pubkey Secret (enforce) |
| 22 | Capture Harbor project config (immutability, retention, robots, quotas, CVE gate) as IaC. | M | new Harbor Terraform/automation |

---

### Appendix — quick verification one-liners

```bash
# GHCR keyless signature (Phase A readiness)
cosign verify \
  --certificate-identity-regexp '^https://github\.com/webgrip/infrastructure/\.github/workflows/on_release_published\.yml@refs/tags/.+$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/webgrip/<image>@sha256:<digest>

# GHCR CycloneDX SBOM attestation (Phase B-GHCR)
cosign verify-attestation --type cyclonedx \
  --certificate-identity-regexp '…on_release_published\.yml@refs/tags/.+$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/webgrip/<image>@sha256:<digest>

# GHCR SLSA provenance (Phase C)
gh attestation verify oci://ghcr.io/webgrip/<image>@sha256:<digest> --owner webgrip

# Harbor keyed signature + SBOM (Phase B-Harbor) — needs the public PEM and pull creds
cosign verify --key cosign.pub harbor.webgrip.dev/webgrip/<image>@sha256:<digest>
cosign verify-attestation --key cosign.pub --type cyclonedx harbor.webgrip.dev/webgrip/<image>@sha256:<digest>

# Read the live Transit public key (post break-glass)
bao read -format=json transit/keys/cosign-webgrip | jq -r '.data.keys["1"].public_key'
```
