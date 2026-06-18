# Building a Practical Cloud-Native Security Platform in a Homelab Cluster

Most Kubernetes security writeups fall into one of two traps: they are either architecture-diagram fantasy with no operational details, or they are so vendor-specific that they stop being useful the moment you leave a managed enterprise platform. This cluster takes a more useful path. The goal is not to cosplay a SOC; it is to build a security platform that is GitOps-native, evidence-driven, and realistic enough that the same patterns could scale from a homelab to a serious production environment.

The result is a layered security stack that now combines **Kyverno**, **Trivy Operator**, **Cosign with GitHub OIDC**, **CycloneDX SBOM attestations**, **GUAC**, **Dependency-Track**, **trust-manager**, **Falco**, **Tetragon**, **Policy Reporter**, **Prometheus alerts**, **Grafana dashboards**, **Renovate**, **cert-manager**, **Flux**, **SOPS**, and the cluster’s existing **Cilium** and **Talos** foundations. That sounds like a lot, but it maps cleanly to the way security teams actually think: software supply chain, admission control, runtime detection, identity and least privilege, observability, and operational governance.

This page explains what is actually implemented in the repo today, why each layer exists, where the overlap is, where the gaps still are, and how the controls map to frameworks security professionals already use such as **NIST SSDF**, **SLSA**, **NIST SP 800-190**, **CIS Kubernetes Benchmark**, **NSA/CISA Kubernetes hardening guidance**, and **MITRE ATT&CK for Containers**.

## What is actually running in this cluster now

The current cluster posture is no longer just “Kubernetes with a few good intentions.” It has a defined security control plane.

### 1. GitOps and secret hygiene as the base layer

Security starts before admission control. This repo already used Flux, Kustomize, HelmRelease, and SOPS, which means configuration is versioned, drift is visible, and secrets are not committed as plaintext. That matters more than people often admit. A cluster with mediocre runtime tooling but strong GitOps discipline will usually outperform a cluster with flashy scanners and weak change control.

In practice, that means:

- **Flux** is the authoritative deployment engine.
- **SOPS + Age** protect secret material in Git.
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
- **Keyless image verification for `ghcr.io/webgrip/*`**
- **Attestation audit rules for provenance and SBOM evidence**
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

### 4. Cosign, GitHub OIDC, and attestations as the supply-chain trust layer

The cluster side of keyless signing is now in place. Kyverno verifies internal `ghcr.io/webgrip/*` images using **GitHub OIDC-issued identities** rather than a manually managed public key. It also audits for two important attestations:

- **SLSA provenance**
- **CycloneDX SBOM**

That means the cluster can distinguish between “an image exists” and “an image was built by the expected CI identity, with traceable provenance and evidence.”

What is not yet done is just as important: the **application CI pipelines still need to publish those signatures and attestations**. The cluster is ready to consume them, but CI must produce them.

#### Exact GitHub OIDC contract the cluster currently expects

The current Kyverno policies trust **GitHub Actions keyless identities** for images under `ghcr.io/webgrip/*` with the following shape:

- issuer: `https://token.actions.githubusercontent.com`
- subject pattern: `https://github.com/webgrip/infrastructure/.github/workflows/on_release_published.yml@refs/tags/<tag>`

That means:

- the infrastructure release workflow must run from a **release tag**
- the image must be published to **GHCR**
- the deployment manifest must use a **digest-pinned** image reference
- the attestation must be pushed where **Kyverno/GUAC can read it**, not only retained in the GitHub UI

The attestation types currently audited are:

- **SLSA provenance**: `https://slsa.dev/provenance/v1`
- **CycloneDX SBOM**: `https://cyclonedx.org/bom`

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

- **Daily SBOM upload** (`trivy-sbom-uploader`, 02:00 UTC): scans all running images, pushes CycloneDX SBOMs to both DT and the GUAC S3 bucket.
- **DT policy engine**: 10 IaC-managed policies evaluate every SBOM upload. Currently showing ~3,900 violations (FAIL/WARN/INFO) across the portfolio.
- **DT metrics exporter**: Python Deployment in `security` namespace polls DT REST API every 5m, exposes `dt_portfolio_*` Prometheus metrics.
- **GUAC S3 collector** (`guac-s3-collector`, 05:00 UTC CronJob): ingests runtime SBOMs into the GUAC graph after DT uploads complete.
- **GUAC OCI collector**: continuously polls GHCR for Cosign attestations (build-time SBOMs, SLSA provenance) on `ghcr.io/webgrip/*` images.

### 5. Falco and Tetragon as the runtime layer

This cluster now runs both **Falco** and **Tetragon** in the `security` namespace, and they are intentionally complementary rather than redundant.

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
- **Falco / 10 Runtime Detections**
- **Tetragon / 10 Runtime Telemetry**
- **cert-manager / Certificates**
- **Renovate** operator visibility

**Alerting**: Three `GrafanaAlertRuleGroup` CRDs provide 16 SLO rules across security, platform, and observability concerns. Rules evaluate against Prometheus and fire into Grafana's alerting system. Discord has been removed — contact points should be configured in Grafana UI (Alerting → Contact Points). See [Supply Chain Intelligence Pipeline](supply-chain-pipeline.md) for the full SLO rule list.

## Complete feature inventory at a glance

If we flatten the stack into a practical inventory, the cluster currently has the following security capabilities:

| Control area | Current implementation | Why it matters |
| --- | --- | --- |
| **Configuration trust** | Flux, HelmRelease, Kustomize, GitOps repo workflows | Gives you versioned intent, drift visibility, and a clean rollback path. |
| **Secret management** | SOPS + Age, encrypted manifests, Flux decryption in cluster | Keeps sensitive values out of Git history while remaining GitOps-native. |
| **Artifact trust** | Cosign keyless verification, GitHub OIDC identity matching | Verifies who built internal images without long-lived signing keys. |
| **Supply-chain evidence** | SLSA provenance and CycloneDX SBOM audit policies | Lets the cluster reason about build lineage and software composition, not just image tags. |
| **Admission governance** | Kyverno enforcement and audit policies | Encodes acceptable state at deployment time. |
| **Metadata graphing** | GUAC | Links provenance, SBOMs, vulnerabilities, and VEX/OpenVEX evidence into a queryable graph. |
| **Continuous SCA/SBOM analysis** | Dependency-Track | Adds portfolio-level component analysis and risk review outside admission-time decisions. |
| **Workload hardening** | Non-root, seccomp, capability drops, read-only filesystem, service account hygiene, volume restrictions | Shrinks the blast radius when an app is compromised. |
| **Identity and privilege** | New RBAC least-privilege audit policies plus Trivy RBAC assessments | Reduces the chance that a workload compromise becomes a cluster compromise. |
| **Image and config scanning** | Trivy Operator vulnerability, config, infra, secret, and RBAC scans | Produces structured evidence about workload and platform risk. |
| **Compliance** | Trivy cluster compliance mapped to CIS, NSA, and PSS specs | Gives a framework-oriented posture view instead of a random list of findings. |
| **Runtime detection** | Falco with metrics, Loki-friendly JSON output, alerting | Surfaces suspicious runtime behavior with a mature rules ecosystem. |
| **Runtime telemetry** | Tetragon process and eBPF telemetry with metadata enrichment | Gives lower-level process visibility and investigation context. |
| **Observability** | Policy Reporter, Prometheus, Grafana dashboards, 16 SLO PrometheusRules via GrafanaAlertRuleGroup | Makes the security controls operational instead of invisible background agents. |
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

- this image came from a specific GitHub workflow and repository,
- this is the SLSA provenance for the build,
- this is the SBOM describing what is inside,
- this is the vulnerability evidence that was uploaded to GitHub Security at build time.

GitHub OIDC removes the operational burden of long-lived signing keys. Instead of managing a secret private key, the workflow obtains a short-lived identity token and Cosign uses that identity for keyless signing. That is a substantial improvement in key management hygiene.

The supply-chain trust story now looks like this:

1. CI builds the image.
2. CI pushes the immutable digest.
3. CI signs the digest keylessly with Cosign.
4. CI publishes provenance, SBOM, and scan attestations.
5. Kyverno verifies the expected GitHub identity and attached evidence.
6. Grafana and Policy Reporter show whether the cluster is seeing compliant artifacts.

This is a pragmatic implementation of **SLSA-style provenance plus Kubernetes admission policy**.

## How to move from audit to enforcement without hurting yourself

One of the easiest ways to make a platform less secure is to enforce the right control at the wrong time. A mature rollout is not “turn everything to deny and hope.” It is staged.

For this cluster, the right progression is:

1. **Audit and measure first.** Use the Kyverno violation dashboards, the new RBAC dashboard, and the Trivy framework dashboard to see where drift actually is.
2. **Fix the recurring classes of violations.** Start with the cheapest, highest-value changes: explicit ServiceAccounts, `automountServiceAccountToken: false`, capability drops, digest-pinned images, and removing wildcard Roles.
3. **Make CI produce evidence consistently.** Until every internal image signs, attests, and deploys by digest, supply-chain enforcement will create operational pain.
4. **Promote the highest-confidence controls first.** Good candidates are image digest requirements, approved registries, and obvious `cluster-admin` misuse. Higher-noise controls should remain audit until the exception process is mature.
5. **Keep exceptions governed.** The repo already has PolicyException governance. That is critical because an exception process without labels, ownership, and expiry becomes permanent policy drift.

This is also where the dashboards matter. Security professionals do not just want to know that a control exists; they want to know whether it is stable enough to enforce. Observability is the difference between a control and a surprise outage.

## Manual secrets you still need to add

This repo’s policy is still the right one: no plaintext secrets in Git. The non-secret wiring for GUAC and Dependency-Track is now in place, but you still need to encrypt and add the bootstrap/application secrets with SOPS.

### GUAC

**Secret name:** `guac-secrets`
**Namespace:** `security`
**Required keys:** `username`, `password`, `values.yaml`

GUAC's S3/blob storage now uses the cluster-wide Garage instance (same as Tempo, Loki, Mimir). S3 credentials are **not** in this secret — they live in the separate `security-s3` SOPS secret (see `kubernetes/components/security-s3/`). Fill in only the database credentials below.

Plaintext template to encrypt:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: guac-secrets
  namespace: security
type: Opaque
stringData:
  username: guac
  password: REPLACE_ME
  values.yaml: |
    guac:
      backend:
        ent:
          db-address: postgres://guac:REPLACE_ME@guac-db-rw.security.svc.cluster.local:5432/guac?sslmode=disable
```

### security-s3 (GUAC Garage S3 credentials)

**Secret name:** `security-s3`
**Namespace:** `security`
**Component:** `kubernetes/components/security-s3/security-s3.sops.yaml`

Create a Garage bucket and key first:

```bash
garage bucket create guac
garage key create security-apps
garage bucket allow --read --write --owner guac --key security-apps
```

Then encrypt:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: security-s3
  namespace: security
type: Opaque
stringData:
  S3_ACCESS_KEY_ID: REPLACE_ME
  S3_SECRET_ACCESS_KEY: REPLACE_ME
  S3_REGION: garage
  S3_ENDPOINT: http://10.0.0.110:3900
  S3_GUAC_BUCKET: guac
```

Encrypt with: `sops --encrypt --in-place kubernetes/components/security-s3/security-s3.sops.yaml`

### Dependency-Track

**Secret name:** `dependency-track-secret`
**Namespace:** `security`
**Required keys:** `username`, `password`, `secret.key`

Plaintext template to encrypt:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: dependency-track-secret
  namespace: security
type: Opaque
stringData:
  username: dependencytrack
  password: REPLACE_ME
  secret.key: REPLACE_WITH_32_RANDOM_BYTES
```

Generate the Dependency-Track secret key with:

```bash
openssl rand 32 > secret.key
```

After encrypting these secrets, add them to the **database** kustomizations so the database bootstrap secret exists before the app HelmReleases reconcile:

- `kubernetes/apps/security/guac/app/database/kustomization.yaml`
- `kubernetes/apps/security/dependency-track/app/database/kustomization.yaml`

## How the current controls map to security frameworks

| Framework | Cluster implementation |
| --- | --- |
| **NIST SSDF** | Signed artifacts, SBOM generation, vulnerability evidence, policy-driven release gates, dependency maintenance via Renovate, change control via GitOps. |
| **SLSA** | Keyless signing, provenance verification, immutable digest pinning, admission-time trust policy for internal images. |
| **NIST SP 800-190** | Image scanning, least privilege, runtime monitoring, secret hygiene, compliance reporting, admission control. |
| **CIS Kubernetes Benchmark** | Trivy compliance specs plus Kyverno hardening policies around privilege escalation, seccomp, capabilities, service accounts, and volume types. |
| **NSA/CISA Kubernetes Hardening** | RuntimeDefault seccomp, non-root execution, read-only filesystems, capability drops, service-account-token minimization, network exposure control. |
| **MITRE ATT&CK for Containers** | Falco and Tetragon detections/telemetry for process execution, suspicious runtime behavior, and post-compromise visibility. |

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

## What still needs to happen outside this repo

The biggest remaining gap is **CI production of signatures and attestations**.

To make the GitHub OIDC and attestation model fully operational, application repositories need workflows that:

1. build and push images by digest,
2. request `id-token: write`,
3. sign the digest with Cosign,
4. publish SLSA provenance,
5. publish a CycloneDX SBOM attestation,
6. upload vulnerability scan results to GitHub Security,
7. deploy only digest-pinned image references.

Until that exists, the cluster-side policy is correct but only partially effective. The cluster can verify supply-chain evidence only if CI emits it.

## Suggested next OSS moves

The stack is already serious, but several open source additions would make it stronger.

### Best next steps

1. **Complete CI attestation publishing** in `webgrip/infrastructure` — Cosign sign + SLSA provenance + CycloneDX attestation per release. The cluster is ready; CI is the gap. See [Supply Chain Intelligence Pipeline](supply-chain-pipeline.md#gaps-and-what-still-needs-to-be-done).
2. **Promote Kyverno image verification to enforce** for `ghcr.io/webgrip/*` once CI attestations are confirmed.
3. **VEX analysis in Dependency-Track** — start reviewing and suppressing known-unexploitable CVEs to reduce portfolio noise.
4. **Falco Talon** if you want response automation (container quarantine, network isolation), not just detection.
5. **OpenVEX / openvex-go** to generate machine-readable exploitability context at build time and feed it to GUAC and DT.
6. **Kubescape** if you want another posture lens to cross-reference against Trivy and Kyverno results.
7. **Grafana contact points** — the 16 SLO alert rules are live but currently route to `null`. Add at least one contact point in the Grafana UI for critical-severity alerts.

### What not to add just for the sake of adding

Do not add a second policy engine just to say you have one. Kyverno already owns admission and governance cleanly here. Likewise, do not bolt on a commercial-style control tower unless it materially improves triage or response. A mature security platform is one operators actually use.

## The practical maturity model for this cluster

If we describe the current state honestly, this cluster is now beyond “basic hardening” and into **evidence-backed platform security**:

- **Foundational controls:** GitOps, SOPS, Talos, cert-manager, Renovate
- **Preventive controls:** Kyverno admission and governance policies
- **Detective controls:** Falco, Tetragon, Trivy posture and findings
- **Assurance controls:** Cosign signatures, GitHub OIDC identities, attestations
- **Operational controls:** Prometheus alerting, Grafana dashboards, Policy Reporter

The next maturity jump is to move from **audit-first** to **selective enforcement** once internal images are consistently signed and attested and once the RBAC and hardening findings are burned down. That is how mature platform teams work: observe first, fix drift, then enforce intentionally.

## Final take

What has been built here is not a random collection of security toys. It is a coherent cloud-native security platform:

- GitOps provides controlled change.
- Kyverno defines acceptable state.
- Trivy provides evidence about risk and compliance.
- Cosign and GitHub OIDC establish artifact identity.
- SBOM and provenance attestations establish software lineage.
- Falco and Tetragon watch what actually happens at runtime.
- Grafana and Prometheus make the whole thing operable.

That is the right shape for an enterprise-parity Kubernetes security stack, even in a homelab. The remaining work is mostly not “more tools.” It is finishing the CI side of the supply-chain story, steadily reducing audit findings, and promoting the highest-value checks from visibility to enforcement.
