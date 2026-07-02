# Building a Practical Cloud-Native Security Platform in a Homelab Cluster

Most Kubernetes security writeups fall into one of two traps: they are either architecture-diagram fantasy with no operational details, or they are so vendor-specific that they stop being useful the moment you leave a managed enterprise platform. This cluster takes a more useful path. The goal is not to cosplay a SOC; it is to build a security platform that is GitOps-native, evidence-driven, and realistic enough that the same patterns could scale from a homelab to a serious production environment.

The result is a layered security stack that combines **Kyverno**, **Trivy Operator**, **Cosign with OpenBao Transit (key-based signing)**, **CycloneDX SBOM attestations**, **GUAC**, **Dependency-Track**, **trust-manager**, **Policy Reporter**, **Prometheus alerts**, **Grafana dashboards**, **Renovate**, **cert-manager**, **Flux**, **ESO + OpenBao**, and the cluster’s existing **Cilium** and **Talos** foundations. (**Falco** and **Tetragon** were part of this stack but are **suspended since 2026-06-19** — see §5.) That sounds like a lot, but it maps cleanly to the way security teams actually think: software supply chain, admission control, runtime detection, identity and least privilege, observability, and operational governance.

This page explains what is actually implemented in the repo today, why each layer exists, where the overlap is, where the gaps still are, and how the controls map to frameworks security professionals already use such as **NIST SSDF**, **SLSA**, **NIST SP 800-190**, **CIS Kubernetes Benchmark**, **NSA/CISA Kubernetes hardening guidance**, and **MITRE ATT&CK for Containers**.

## What is actually running in this cluster now

The current cluster posture is no longer just “Kubernetes with a few good intentions.” It has a defined security control plane.

### 1. GitOps and secret hygiene as the base layer

Security starts before admission control. This repo uses Flux, Kustomize, HelmRelease, and ESO + OpenBao, which means configuration is versioned, drift is visible, and secrets are not committed as plaintext. That matters more than people often admit. A cluster with mediocre runtime tooling but strong GitOps discipline will usually outperform a cluster with flashy scanners and weak change control.

In practice, that means:

- **Flux** is the authoritative deployment engine.
- **External Secrets Operator + OpenBao** own secret material (a minimal SOPS/Age floor remains for bootstrap: age key, `cluster-secrets`, `talsecret`).
- **Talos** reduces node-level configuration drift and narrows the mutable host surface.
- **Cilium** provides an eBPF networking foundation that complements runtime telemetry.
- **Renovate** keeps dependency and chart versions moving, which is a major but often invisible security control.

This is the “platform trust” layer. Without it, the rest of the stack becomes theater.

### 2. Kyverno as the policy and admission layer

Kyverno now runs in the shared `security` namespace with the rest of the security platform. That creates tighter coupling than a dedicated control-plane namespace, so the repo compensates by moving the Flux Kustomizations, PolicyExceptions, alerting, tests, and dashboard namespace references with it as one unit.

The tradeoff is real: Kyverno is still an admission control plane with its own lifecycle and exception model, but it is now colocated intentionally for operational simplicity. The important thing is consistency — once you choose `security` as the home, every namespace-targeted reference around Kyverno needs to move with it.

Kyverno now covers several control families:

- **Pod security baseline enforcement**
- **Workload hardening audit rules**
- **Advanced hardening audit rules**
- **Image hygiene and supply-chain audit rules**
- **Network exposure governance**
- **Namespace defaults generation**
- **Exception governance**
- **Flux governance**
- **cert-manager and storage governance**
- **Key-based image verification for `webgrip/*` images** (keyless only for third-party `ghcr.io/kyverno/*`)
- **Attestation audit rules for SBOM evidence**
- **New RBAC least-privilege audit rules**

The newest addition is an RBAC governance layer that audits three common privilege-escalation patterns:

1. wildcard Roles in application namespaces,
2. RoleBindings or ClusterRoleBindings that grant permissions to the `default` ServiceAccount, and
3. `cluster-admin` grants to application identities.

That closes an important gap. The cluster already had strong pod-level hardening, but pod security without RBAC discipline still leaves a large blast radius if a workload is compromised.

### 3. Trivy Operator as the evidence and posture layer

Trivy Operator is now installed in the dedicated `security` namespace and configured for materially useful output, not a minimal demo deployment.

Enabled capabilities include:

- image vulnerability scanning,
- **CycloneDX SBOM generation**,
- cluster SBOM cache,
- config audit,
- RBAC assessment,
- infrastructure assessment,
- cluster compliance,
- exposed secret scanning,
- built-in Trivy server,
- Prometheus metrics,
- persistent report storage on Longhorn.

That makes Trivy more than “a CVE counter.” It is the cluster’s structured evidence source for software composition, workload findings, configuration issues, RBAC missteps, and compliance posture.

### 4. Cosign with OpenBao Transit as the supply-chain trust layer

First-party image signing is **key-based, not keyless**. Forgejo (the sole release authority)
builds and dual-publishes webgrip images to Harbor + GHCR, and both are signed by digest with the
**OpenBao Transit key `cosign-webgrip`** (ECDSA-P256, private half never leaves OpenBao,
`--tlog-upload=false` so no public Rekor entry). Per-job Forgejo Actions OIDC tokens authorize
the signing call against OpenBao's `auth/forgejo` JWT role — a fork PR gets no token and cannot
sign. Kyverno verifies signatures **and CycloneDX SBOM attestations** against the public key in
the `cosign-webgrip-pub` ConfigMap (published by the `cosign-pubkey` CronJob).

**Keyless verification survives in exactly one place: third-party `ghcr.io/kyverno/*` images**,
which still verify via GitHub Actions OIDC against the public Rekor. Do not describe any
`webgrip/*` image as keyless.

Full contract, the `rekor.ignoreTlog: true` gotcha, and the Audit→Enforce promotion gate:
[Supply Chain Intelligence Pipeline](supply-chain-pipeline.md).

### 4.5. GUAC, Dependency-Track, and trust-manager as the graph + analysis + trust-distribution layer

This rollout adds three more supply-chain building blocks:

- **GUAC** gives the cluster a graph-oriented metadata plane for software supply-chain evidence. It is the place where provenance, SBOMs, vulnerabilities, and VEX/OpenVEX data can be connected instead of living as isolated documents.
- **Dependency-Track** adds a dedicated SBOM analysis platform that is especially useful for continuous component risk review, policy, and software inventory workflows outside admission control.
- **trust-manager** adds a consistent mechanism for distributing trust bundles in-cluster, starting here with a managed public CA bundle in namespaces that opt in to trust distribution.

These are not replacements for Kyverno or Trivy. They fill different jobs:

- GUAC = relationship graph and evidence aggregation
- Dependency-Track = continuous SBOM/component risk analysis
- trust-manager = trust-bundle lifecycle and distribution
- OpenVEX = machine-readable exploitability context

**Both GUAC and DT are now fully wired.** See [Supply Chain Intelligence Pipeline](supply-chain-pipeline.md) for the complete data flow, including how CI attestations and cluster runtime SBOMs converge.

Key operational facts:

- **Weekly SBOM upload** (`sbom-uploader`, Sun 02:10 UTC): scans all running images, pushes CycloneDX SBOMs to both DT and the GUAC S3 bucket.
- **DT policy engine**: 10 IaC-managed policies evaluate every SBOM upload.
- **DT metrics exporter**: Python Deployment in `security` namespace polls DT REST API every 5m, exposes `dt_portfolio_*` Prometheus metrics.
- **GUAC S3 collector** (`guac-s3-collector`, weekly Sun 05:20 UTC CronJob): ingests runtime SBOMs into the GUAC graph after DT uploads complete.
- **GUAC OCI collector**: continuously polls the registries for Cosign attestations (build-time SBOMs) on `webgrip/*` images.

### 5. Falco and Tetragon as the runtime layer — SUSPENDED

> **Suspended 2026-06-19.** Repeated cluster outages were attributed to these runtime-security
> agents; both are commented out of `kubernetes/apps/security/kustomization.yaml`, so Flux
> garbage-collected their DaemonSets and **neither runs in the cluster**. All manifests are
> retained under `./falco` and `./tetragon` — re-add the two `ks.yaml` lines to restore. Until
> then the cluster has **no runtime-detection layer**; their Grafana dashboards show no data.

When enabled, they are intentionally complementary rather than redundant.

Falco is configured with:

- modern eBPF,
- containerd metadata collection,
- Prometheus metrics,
- ServiceMonitor integration,
- JSON stdout suitable for Loki,
- runtime detection alerts.

Tetragon is configured with:

- process and runtime telemetry,
- Kubernetes metadata enrichment,
- CRI and cgroup mapping for containerd,
- redaction filters for common secrets and tokens,
- Prometheus metrics,
- ServiceMonitors,
- stdout export for Loki,
- Talos-friendly tracing mounts.

If Falco is the high-level detection engine, Tetragon is the low-level runtime and process telemetry fabric.

### 6. Grafana and alerting as the operational layer

Dashboards now live in the folders of the specific tools instead of being dumped into a generic pile. That sounds small, but it matters operationally. When a control plane grows, usability becomes a security feature.

Current tool-specific coverage includes:

- **Security / SOC Command Center** (cross-concern overview)
- **Security / Supply Chain (Dependency-Track)** — portfolio CVEs, policy violations, risk score trends
- **Kyverno / 10 Policy Insights**
- **Kyverno / 20 Policy Violations**
- **Kyverno / 30 RBAC and Least Privilege**
- **Cosign / 10 GitHub OIDC Attestations**
- **Trivy / 10 Vulnerabilities, SBOMs and Compliance**
- **Trivy / 20 Compliance Frameworks**
- **Falco / 10 Runtime Detections** *(no data — Falco suspended)*
- **Tetragon / 10 Runtime Telemetry** *(no data — Tetragon suspended)*
- **cert-manager / Certificates**
- **Renovate** operator visibility

**Alerting**: `GrafanaAlertRuleGroup` CRDs provide SLO rules across security, platform, and observability concerns (`grafana/app/alerting/`). Rules evaluate against the metrics backend and fire into Grafana's alerting system. Contact points are configured in the Grafana UI (Alerting → Contact Points). Principles + template: [Alerting principles](alerting-principles.md).

## Complete feature inventory at a glance

If we flatten the stack into a practical inventory, the cluster currently has the following security capabilities:

| Control area | Current implementation | Why it matters |
| --- | --- | --- |
| **Configuration trust** | Flux, HelmRelease, Kustomize, GitOps repo workflows | Gives you versioned intent, drift visibility, and a clean rollback path. |
| **Secret management** | ESO + OpenBao (`ExternalSecret`/`PushSecret`; minimal SOPS bootstrap floor) | Keeps sensitive values out of Git while remaining GitOps-native. |
| **Artifact trust** | Cosign key-based verification against the OpenBao Transit public key | Verifies webgrip images were signed by the release pipeline; the key never leaves OpenBao. |
| **Supply-chain evidence** | CycloneDX SBOM attestation audit policies | Lets the cluster reason about software composition, not just image tags. |
| **Admission governance** | Kyverno enforcement and audit policies | Encodes acceptable state at deployment time. |
| **Metadata graphing** | GUAC | Links provenance, SBOMs, vulnerabilities, and VEX/OpenVEX evidence into a queryable graph. |
| **Continuous SCA/SBOM analysis** | Dependency-Track | Adds portfolio-level component analysis and risk review outside admission-time decisions. |
| **Workload hardening** | Non-root, seccomp, capability drops, read-only filesystem, service account hygiene, volume restrictions | Shrinks the blast radius when an app is compromised. |
| **Identity and privilege** | New RBAC least-privilege audit policies plus Trivy RBAC assessments | Reduces the chance that a workload compromise becomes a cluster compromise. |
| **Image and config scanning** | Trivy Operator vulnerability, config, infra, secret, and RBAC scans | Produces structured evidence about workload and platform risk. |
| **Compliance** | Trivy cluster compliance mapped to CIS, NSA, and PSS specs | Gives a framework-oriented posture view instead of a random list of findings. |
| **Runtime detection** | Falco — **suspended 2026-06-19** (manifests retained) | Was the runtime detection engine; the cluster currently runs without it. |
| **Runtime telemetry** | Tetragon — **suspended 2026-06-19** (manifests retained) | Was the low-level process telemetry fabric; suspended alongside Falco. |
| **Observability** | Policy Reporter, VictoriaMetrics, Grafana dashboards, SLO rules via GrafanaAlertRuleGroup | Makes the security controls operational instead of invisible background agents. |
| **Maintenance** | Renovate | Security posture degrades quickly without dependable update hygiene. |
| **PKI and trust distribution** | cert-manager, trust-manager | Stable certificate automation plus managed trust-bundle distribution is foundational for secure service exposure and identity. |
| **Supply-chain pipeline** | Trivy → DT + GUAC S3, OCI collector → GUAC graph, 10 IaC DT policies, DT metrics exporter | Continuous SBOM-to-graph pipeline: every running image lands in DT (policy/CVE) and GUAC (relationship queries) daily. |

That is already a meaningful “enterprise-parity” footprint because it covers **preventive**, **detective**, **assurance**, and **operational** controls in a single GitOps workflow.

## The most important overlap question: Trivy vs Kyverno

The most useful way to explain the overlap is this:

- **Trivy tells you what is risky or non-compliant.**
- **Kyverno tells the cluster what is acceptable.**

That means they overlap in data domain, but not in job function.

Trivy covers:

- vulnerabilities,
- exposed secrets,
- config audit,
- RBAC assessment,
- infrastructure findings,
- compliance reporting,
- SBOM generation.

Kyverno covers:

- admission decisions,
- policy-based blocking or auditing,
- image signature verification,
- attestation verification,
- workload hardening requirements,
- governance of namespaces, network exposure, and exceptions.

The overlap is productive. Trivy generates evidence; Kyverno turns policy expectations into cluster behavior. Trivy can tell you a thing is bad. Kyverno can decide whether that thing should be allowed to land.

## Why Cosign signatures and attestations are worth the effort

Cosigning answers a narrow but critical question: **who produced this artifact, and can I cryptographically prove it?**

Attestation answers a related but broader question: **what do we know about this artifact and its build process?**

A signature says:

- this image digest was signed by the expected identity.

An attestation says things like:

- this is the SBOM describing what is inside,
- (future) this is the build provenance for the image.

OpenBao Transit removes the operational burden of a private key on the runner: the key never
leaves OpenBao, and the release job authorizes each `transit/sign` call with a short-lived,
per-job Forgejo OIDC token. Key rotation is a runbook, not a re-keying ceremony
([Transit key rotation](../runbooks/cosign-transit-key-rotation.md)).

The supply-chain trust story now looks like this:

1. Forgejo CI builds the image and pushes it by immutable digest (Harbor + GHCR).
2. CI signs the digest with Cosign via OpenBao Transit (`hashivault://cosign-webgrip`).
3. CI attests a CycloneDX SBOM with the same key and uploads it to Dependency-Track.
4. Kyverno verifies signature + SBOM against the Transit public key at admission.
5. Grafana and Policy Reporter show whether the cluster is seeing compliant artifacts.

This is a pragmatic implementation of **signed-supply-chain plus Kubernetes admission policy**.

## How to move from audit to enforcement without hurting yourself

One of the easiest ways to make a platform less secure is to enforce the right control at the wrong time. A mature rollout is not “turn everything to deny and hope.” It is staged.

For this cluster, the right progression is:

1. **Audit and measure first.** Use the Kyverno violation dashboards, the new RBAC dashboard, and the Trivy framework dashboard to see where drift actually is.
2. **Fix the recurring classes of violations.** Start with the cheapest, highest-value changes: explicit ServiceAccounts, `automountServiceAccountToken: false`, capability drops, digest-pinned images, and removing wildcard Roles.
3. **Make CI produce evidence consistently.** Until every internal image signs, attests, and deploys by digest, supply-chain enforcement will create operational pain.
4. **Promote the highest-confidence controls first.** Good candidates are image digest requirements and obvious `cluster-admin` misuse. Higher-noise controls should remain audit until the exception process is mature — and `require-approved-registries` **stays Audit permanently** per [ADR-0034](../adr/adr-0034-approved-registries-stays-audit.md). The gated wave plan is [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md).
5. **Keep exceptions governed.** The repo already has PolicyException governance. That is critical because an exception process without labels, ownership, and expiry becomes permanent policy drift.

This is also where the dashboards matter. Security professionals do not just want to know that a control exists; they want to know whether it is stable enough to enforce. Observability is the difference between a control and a surprise outage.

## Secrets

All security-platform secrets (GUAC, Dependency-Track, `security-s3`, Harbor robots, …) are
**ESO-managed** — `ExternalSecret`s backed by OpenBao KV or in-cluster `password-generator`s.
There are no SOPS templates to fill in. To add or migrate one, use the **`external-secrets`
skill**; operational detail lives in the [External Secrets runbook](../runbooks/external-secrets.md).

## How the current controls map to security frameworks

| Framework | Cluster implementation |
| --- | --- |
| **NIST SSDF** | Signed artifacts, SBOM generation, vulnerability evidence, policy-driven release gates, dependency maintenance via Renovate, change control via GitOps. |
| **SLSA** | Key-based signing via OpenBao Transit, immutable digest pinning, admission-time trust policy for internal images (build provenance on the Forgejo path is a known gap). |
| **NIST SP 800-190** | Image scanning, least privilege, secret hygiene, compliance reporting, admission control (runtime monitoring suspended with Falco/Tetragon). |
| **CIS Kubernetes Benchmark** | Trivy compliance specs plus Kyverno hardening policies around privilege escalation, seccomp, capabilities, service accounts, and volume types. |
| **NSA/CISA Kubernetes Hardening** | RuntimeDefault seccomp, non-root execution, read-only filesystems, capability drops, service-account-token minimization, network exposure control. |
| **MITRE ATT&CK for Containers** | **Currently unmapped at runtime** — Falco/Tetragon detections are suspended; restoring them restores this row. |

That mapping matters because it moves the conversation from “we installed some tools” to “we implemented controls aligned to recognized security objectives.”

## What changed in this expansion pass

This phase did not just document the stack; it extended it.

### New governance policy: RBAC least privilege

The cluster now audits RBAC drift that many teams miss until after an incident:

- wildcard Roles,
- `default` ServiceAccount bindings,
- `cluster-admin` grants to workload identities.

This is a meaningful maturity step because compromised workloads typically pivot through identity and permissions, not just container escapes.

### New dashboard: Kyverno RBAC and Least Privilege

Kyverno now has a dedicated RBAC dashboard that shows:

- wildcard role findings,
- default ServiceAccount binding findings,
- cluster-admin grants,
- namespace concentration of RBAC drift,
- namespaced versus cluster-scoped RBAC violations.

That makes least privilege measurable rather than aspirational.

### New dashboard: Trivy Compliance Frameworks

Trivy now has a framework-oriented dashboard focused on:

- failing and passing compliance controls,
- config, RBAC, and infrastructure drift,
- top namespaces with high-severity posture issues,
- the current coverage of CIS, NSA/CISA, and PSS-oriented checks.

This is the right companion to the original Trivy dashboard, which was more workload and finding oriented.

### Better dashboard ordering

The security dashboards now follow the same numbered naming pattern already used in the Kyverno folder. That keeps tool-specific folders predictable:

- `10` for the primary operational view,
- `20` for deeper framework or posture analysis,
- `30` for specialized governance views where needed.

## What still needs to happen

CI-side signing and SBOM attestation **exist** (Forgejo release pipeline, key-based via OpenBao
Transit — see [Supply Chain Intelligence Pipeline](supply-chain-pipeline.md)). The remaining
gaps:

1. **Prove a signed release verifies green end-to-end** (Policy Reports on a real admission),
   then **promote the Kyverno verify policies Audit → Enforce** per the
   [gated wave plan](../rfc/rfc-kyverno-audit-enforce-hardening.md).
2. **Build provenance on the Forgejo path** — Harbor images carry signature + CycloneDX SBOM but
   no SLSA provenance (no `attest-build-provenance` analog); research item.
3. **Runtime detection** — decide whether/when to restore Falco/Tetragon (or a lighter
   replacement) after their 2026-06-19 stability suspension.

## Suggested next OSS moves

1. **VEX analysis in Dependency-Track** — review and suppress known-unexploitable CVEs to reduce portfolio noise.
2. **OpenVEX / openvex-go** to generate machine-readable exploitability context at build time and feed it to GUAC and DT.
3. **Kubescape** if you want another posture lens to cross-reference against Trivy and Kyverno results.
4. **Grafana contact points** — ensure at least one contact point is wired for critical-severity alerts (Grafana UI, Alerting → Contact Points).

### What not to add just for the sake of adding

Do not add a second policy engine just to say you have one. Kyverno already owns admission and governance cleanly here. Likewise, do not bolt on a commercial-style control tower unless it materially improves triage or response. A mature security platform is one operators actually use.

## The practical maturity model for this cluster

If we describe the current state honestly, this cluster is now beyond “basic hardening” and into **evidence-backed platform security**:

- **Foundational controls:** GitOps, ESO + OpenBao, Talos, cert-manager, Renovate
- **Preventive controls:** Kyverno admission and governance policies
- **Detective controls:** Trivy posture and findings (Falco/Tetragon runtime detection suspended)
- **Assurance controls:** Cosign key-based signatures via OpenBao Transit, SBOM attestations
- **Operational controls:** VictoriaMetrics alerting, Grafana dashboards, Policy Reporter

The next maturity jump is to move from **audit-first** to **selective enforcement** once internal images are consistently signed and attested and once the RBAC and hardening findings are burned down. That is how mature platform teams work: observe first, fix drift, then enforce intentionally.

## Final take

What has been built here is not a random collection of security toys. It is a coherent cloud-native security platform:

- GitOps provides controlled change.
- Kyverno defines acceptable state.
- Trivy provides evidence about risk and compliance.
- Cosign + OpenBao Transit establish artifact identity.
- SBOM attestations establish software lineage.
- (Falco and Tetragon watched runtime behavior; suspended until their stability cost is solved.)
- Grafana and VictoriaMetrics make the whole thing operable.

That is the right shape for an enterprise-parity Kubernetes security stack, even in a homelab. The remaining work is mostly not “more tools.” It is finishing the CI side of the supply-chain story, steadily reducing audit findings, and promoting the highest-value checks from visibility to enforcement.
