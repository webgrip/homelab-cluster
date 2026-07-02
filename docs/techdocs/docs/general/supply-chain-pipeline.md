# Supply Chain Intelligence Pipeline

> Status: living · Companion to [Container Supply Chain — Architecture Overview](./supply-chain-overview.md),
> the [Transit key-rotation runbook](../runbooks/cosign-transit-key-rotation.md), the
> [Harbor runbook](../runbooks/harbor.md), and the Kyverno image-verify policies under
> `kubernetes/apps/kyverno/policies/app/`.

This document explains the end-to-end software supply chain in this cluster: how first-party
images are built, signed and published; how they are verified at admission; where SBOMs come
from and how they flow into Dependency-Track and GUAC; and what questions you can actually
answer as a result.

---

## Release once, publish many

The single most important thing to understand: **Forgejo is the sole release authority.**

- **Forgejo (in-cluster, LAN)** owns the release. A change under `ops/docker/**` in a
  `webgrip/*` repo triggers `semantic-release`, which decides the version, **cuts the release
  tag**, and **commits the bumped `package.json` back with `[skip ci]`**. Forgejo's in-cluster
  KEDA/DinD runner then **builds** the image and **dual-publishes** it to two registries:
  **Harbor** (`harbor.${SECRET_DOMAIN}/webgrip/*`, private/LAN, the primary) **and**
  **GHCR** (`ghcr.io/webgrip/*`).
- **GitHub is a pure mirror.** The repo is push-mirrored to GitHub for off-site DR, but the
  GitHub side **runs zero Actions** for the release — it does not tag, does not version, does
  not decide anything. Anything the `.github/` mirror still does at push time is build-side
  only and is **not what the cluster trusts** (see "What the cluster trusts" below).

So: one release is cut once (on Forgejo), and the resulting image is published to many places
(Harbor + GHCR). The trust anchor is the same in both: **one signing key**.

---

## Signing — key-based, both registries, same key

Both registries are signed the **same way**: key-based by digest, not keyless.

- **`cosign sign` / `cosign attest` by digest**, using the OpenBao **Transit** key
  `cosign-webgrip` (`ecdsa-p256`). The private key **never leaves OpenBao** — cosign calls
  `transit/sign` over `--key hashivault://cosign-webgrip`.
- **`--tlog-upload=false`.** Signatures are **not** uploaded to a public Rekor transparency
  log. This avoids leaking digests/timestamps to the public internet and removes an internet
  dependency from the signing path. (This is the fact that drives the Kyverno `rekor.ignoreTlog`
  requirement below — read that section.)
- **Authorized per-job via Forgejo Actions OIDC → OpenBao.** Each release job mints a
  *per-job* OIDC token from Forgejo (issuer `https://forgejo.${SECRET_DOMAIN}/api/actions`,
  audience `openbao-cosign`) and presents it to OpenBao at `/v1/auth/forgejo/login`. OpenBao's
  JWT auth (mount `auth/forgejo`, role **`cosign-signer`**) independently verifies the token
  against Forgejo's JWKS and its **bound claims** before issuing a short-lived, sign-only
  Transit token. A fork PR gets no token and therefore cannot sign.

> **The bound-claims shape is Forgejo-specific, not GitHub.** The release fires via
> `workflow_dispatch` on a branch (semantic-release publishes on `main`/`release/*`), so the
> role binds `{"repository": "webgrip/infrastructure", "event_name": "workflow_dispatch",
> "ref": "refs/heads/*"}`.
> The earlier GitHub-shaped binding (`event_name=release`, `ref=refs/tags/*`) made OpenBao
> 400 the login. Source: `kubernetes/apps/security/openbao/bootstrap/config.sh`.

**As of commit `fc5fdf1` (2026-06-26), webgrip GHCR is signed with the SAME Transit key as
Harbor.** GHCR is no longer keyless / Fulcio / Rekor. The keyless+Rekor language survives in
exactly one place: **third-party `ghcr.io/kyverno/*` images**, which still verify via GitHub
Actions OIDC against the public Rekor (`rekor.url: https://rekor.sigstore.dev`). Do not use
"keyless" to describe any `webgrip/*` image.

### One key signs both registries

The `.forgejo` sign-attest action signs **by digest**
(`docker buildx imagetools inspect … --format '{{.Manifest.Digest}}'`) and was generalized to
`REGISTRY_USERNAME` / `REGISTRY_TOKEN` so the single `cosign-webgrip` key signs Harbor and
GHCR identically. The public half is published to the **`cosign-webgrip-pub`** ConfigMap
(`security` ns) by the `cosign-pubkey` CronJob (every 30 min, every still-trusted key version,
newest first) — no human ever pastes a PEM. See the
[Transit key-rotation runbook](../runbooks/cosign-transit-key-rotation.md).

---

## What the cluster trusts — Kyverno is the single admission gate

Kyverno `verifyImages` is the **one** admission gate. Three **Audit** ClusterPolicies cover
first-party images, all **key-based** against the `cosign-webgrip-pub` ConfigMap:

| Policy file | Rule | Verifies |
|---|---|---|
| `image-verify-audit.yaml` | `verify-webgrip-images` | `ghcr.io/webgrip/*` **signature** (key-based) |
| `image-attestations-audit.yaml` | `verify-webgrip-ghcr-images` | `ghcr.io/webgrip/*` **CycloneDX SBOM attestation** (key-based) |
| `image-verify-harbor-audit.yaml` | `verify-webgrip-harbor-images` | `harbor.${SECRET_DOMAIN}/webgrip/*` **signature + CycloneDX SBOM** (key-based) |

All three read the public key from the `cosign-webgrip-pub` ConfigMap in `security`. The Harbor
policy additionally supplies the `harbor-pull` robot credential (Harbor is private + LAN-only,
so Kyverno needs it to fetch the manifest/signature/attestation). `image-verify-audit` also
carries the separate `verify-kyverno-images-keyless` rule for `ghcr.io/kyverno/*` — that is
the **only** keyless rule, and it is the only place `rekor.url` legitimately appears.

### The Rekor gate — `rekor.ignoreTlog: true` (CRITICAL)

Because cosign signs with **`--tlog-upload=false`**, there is **no Rekor transparency-log
entry** for any webgrip image. But Kyverno (1.18.x, cosign 2.x) **verifies the Rekor tlog by
default**. A key-based attestor against a `--tlog-upload=false` signature therefore needs an
explicit `rekor.ignoreTlog: true` on **every** verify entry, or verification fails for a
correctly-signed image:

```yaml
attestors:
  - count: 1
    entries:
      - keys:
          publicKeys: '{{ cosignpub.data."cosign.pub" }}'
          rekor:
            ignoreTlog: true   # no tlog exists (--tlog-upload=false) → must skip the lookup
```

This was a latent bug masked by Audit mode (Audit only surfaces PolicyReports; it does not
block). It was added to all key-based attestors in **commit `f26106d`**. Without it, flipping
to Enforce would reject **every** (correctly) signed image cluster-wide.

### Promotion gate — do NOT flip Audit → Enforce until both are true

1. **The policies carry `rekor.ignoreTlog: true`** on every key-based attestor. ✅ *Done
   (`f26106d`).*
2. **A real signed release verifies green with zero false positives** — confirm via Policy
   Reports / the Kyverno dashboards that an actual signed Harbor+GHCR image admits cleanly
   before promoting. *Not yet exercised end-to-end.*

When you do promote the Harbor rule, also flip its `failurePolicy: Ignore` → `Fail` (it is
`Ignore` today so an unpublished ConfigMap / OpenBao blip / unreachable Harbor cannot block
unrelated pod admissions during Audit).

> **Correcting the stale OIDC contract.** Older docs described the trust as a GitHub keyless
> subject `https://github.com/webgrip/infrastructure/.github/workflows/...@refs/tags/*` issued
> by `https://token.actions.githubusercontent.com`. **That is no longer what the cluster
> trusts.** The cluster trusts the **`cosign-webgrip` Transit public key**. The GitHub-OIDC
> subject pattern applies to nothing in scope; the only keyless trust is the
> `kyverno/kyverno` subject in `verify-kyverno-images-keyless`.
>
> **Stale CLI-test rule names.** The CLI test
> `kubernetes/apps/kyverno/tests/cli/image-verification/kyverno-test.yaml` still references
> rule names `verify-github-slsa-provenance` and `verify-cyclonedx-sbom`, which **no longer
> match** any rule. The live rules are `verify-webgrip-images` (signature) in
> `image-verify-audit` and `verify-webgrip-ghcr-images` (SBOM attestation) in
> `image-attestations-audit`. The test needs updating to the current rule names.

---

## SBOMs — two origins

There are two fundamentally different moments at which an SBOM is produced. Both matter.

### Origin 1 — Build-time (CI, by digest)

During the release job, the `.forgejo` sign-attest action runs **Syft** to produce a
**CycloneDX** (and SPDX) SBOM, then **`cosign attest --type cyclonedx`** by digest (same
Transit key, same `--tlog-upload=false`). This attestation is what Kyverno's SBOM policies
verify, and what GUAC's OCI collector ingests.

The action also **uploads the CycloneDX SBOM to in-cluster Dependency-Track**
(`POST http://dependency-track-api-server.security.svc.cluster.local:8080/api/v1/bom`,
`autoCreate`). **This upload is fail-soft**: on a non-2xx it logs a `::warning::` and the job
continues — the cosign attestation already proves provenance and Trivy Operator covers
continuous analysis, so a DT hiccup must not fail a release.

> **Harbor's native SBOM column is separate** and is **not** fed by the pushed cosign
> attestation. The "SBOM" column in Harbor's UI is populated **exclusively** by Harbor's own
> Trivy-backed `.sbom` accessory, triggered server-side and authorized by RBAC resource
> **`sbom` + action `create`** (NOT `scan:create`). The CI robot lacked that grant and the
> step 403'd until **commit `9938e09`** added it. A `cosign attest --type cyclonedx` shows up
> under "Signed" as a `.att` accessory — never in the SBOM column. See the
> [Harbor runbook](../runbooks/harbor.md) for the least-privilege robot grant.
>
> **The Harbor SBOM step is asymmetric on purpose.** It is gated
> `if: contains(inputs.registry, 'harbor')` — GHCR has no server-side SBOM API, so the step is
> meaningless there. Evaluate signing/SBOM changes per-target, never blindly mirror them.

### Origin 2 — Runtime scanning (whole-fleet)

The `dependency-track/sbom-uploader` CronJob runs **Sundays at 02:10 UTC** (`10 2 * * 0`). It:

1. Lists every running container image across all namespaces.
2. Runs `trivy image --format cyclonedx` on each (scans actual layers).
3. Uploads each CycloneDX SBOM to Dependency-Track (`POST /api/v1/bom`).
4. Writes the SBOM to the GUAC Garage S3 bucket (`s3://guac/sboms/`) for GUAC ingestion.

This auto-populates **~160 DT projects (and growing)** — overwhelmingly **third-party / system
/ operator images**, not just webgrip images. Keep that in mind when reading DT/SLO numbers:
they are whole-fleet posture, not a verdict on your own images.

### Why both

| Concern | Build-time (attestation) | Runtime (Trivy scan) |
|---|---|---|
| Covers third-party / system images | No | **Yes** |
| Cryptographically tied to the release | **Yes** (cosign by digest) | No |
| Detects post-build tampering | **Yes** (signature mismatch) | No |
| Reflects what is actually running now | No | **Yes** |
| Basis for Kyverno SBOM admission | **Yes** | No |

---

## Data flow

```mermaid
flowchart TD
    subgraph Forge ["Forgejo — sole release authority (in-cluster, LAN)"]
        SR[semantic-release\ntag + commit package.json [skip ci]] --> B[Runner builds ops/docker/*]
        B --> H[push harbor.${SECRET_DOMAIN}/webgrip/*]
        B --> G[push ghcr.io/webgrip/*]
        B --> SY[Syft → CycloneDX + SPDX]
    end

    subgraph Sign ["Sign by digest — OpenBao Transit (cosign-webgrip, ECDSA-P256)"]
        OIDC[Forgejo OIDC per-job token\naud=openbao-cosign] --> BAO[auth/forgejo/login\nrole cosign-signer]
        BAO --> TR[transit/sign\n--tlog-upload=false]
        SY --> TR
        TR --> SH[cosign sig + CycloneDX attest\non BOTH registries]
    end

    subgraph DT ["Dependency-Track (security ns)"]
        SY -.->|fail-soft POST /api/v1/bom| DTU[CI upload]
        TRIVY[sbom-uploader CronJob\nSun 02:10 UTC, ~160 imgs] --> DTU
        TRIVY --> S3[Garage S3 s3://guac/sboms/]
    end

    subgraph GUAC ["GUAC (security ns)"]
        SH --> OCI[oci-collector polls registries]
        S3 --> S3C[s3-collector CronJob]
        OCI --> GR[GUAC graph]
        S3C --> GR
    end

    subgraph Admit ["Kyverno verifyImages — single admission gate (Audit)"]
        PUB[cosign-webgrip-pub ConfigMap] --> KV[3 key-based policies\nrekor.ignoreTlog:true]
        SH --> KV
    end

    subgraph Mirror ["GitHub — pure mirror (zero Actions)"]
        GHM[push-mirror DR only]
    end

    Forge -.->|push-mirror| GHM
```

---

## Dependency-Track in depth

Dependency-Track is the **continuous component-analysis** platform. For every uploaded SBOM it
parses components (name + version + PURL), matches them against OSV / NVD / GitHub Advisory,
evaluates the bootstrapped policies, and aggregates portfolio metrics.

The DT metrics exporter polls `GET /api/v1/metrics/portfolio/current` every 5 minutes and
exposes `dt_portfolio_*` metrics (vulnerabilities by severity, policy violations by state,
projects, components, risk score, last-scrape timestamp) to VictoriaMetrics.

- Public URL: `https://dependency-track.${SECRET_DOMAIN}`
- The portfolio dashboard aggregates from `PROJECTMETRICS` on an hourly cycle — fresh uploads
  may take up to an hour to appear (or `POST /api/v1/metrics/portfolio/refresh`).

> **Read DT numbers as whole-fleet hygiene.** ~160 projects are mostly third-party/system
> images. A "critical CVE" in DT is usually an upstream-image finding, not a defect in a
> webgrip image — triage accordingly before paging on it.

---

## GUAC in depth

GUAC (Graph for Understanding Artifact Composition) is the **supply-chain metadata graph** —
it answers relationship questions ("which running images depend on log4j?", "what is the
provenance of image Z?", "which images share this vulnerable component?"). It ingests SBOMs +
attestations and stores them as a graph in CloudNativePG PostgreSQL, queried via GraphQL
(`https://guac.${SECRET_DOMAIN}`).

Two ingest paths:

- **OCI attestations (build-time):** `oci-collector` polls the registries for cosign-attached
  CycloneDX attestations on `webgrip/*` images — the cryptographically-anchored graph.
- **S3 cluster SBOMs (runtime):** the `guac-s3-collector` CronJob ingests every CycloneDX SBOM
  the Trivy uploader wrote to `s3://guac/sboms/` — visibility into every running image,
  including third-party/operator images with no attestation.

---

## How Kyverno, Trivy, DT, and GUAC relate

They are layered, not redundant:

| Tool | Job | Data source | When |
|---|---|---|---|
| **Kyverno** | Admission gate — only signed first-party images run | cosign sig + SBOM attestation (key-based) | Every pod admission |
| **Trivy Operator** | Continuous in-cluster CVE/config/RBAC posture | Running images | Scheduled / on change |
| **Dependency-Track** | Portfolio SBOM risk + policy + license | CycloneDX SBOMs (CI upload + weekly Trivy) | On upload + hourly aggregation |
| **GUAC** | Supply-chain graph / relationship queries | SBOMs + attestations + OSV | Continuous (OCI) + S3 ingest |

A finding may surface in more than one — that is intentional: DT says *what component is
vulnerable*, GUAC says *which images share it*, Kyverno says *this image isn't signed*, Trivy
Operator says *this running pod has the CVE*.

---

## Operational schedule

| When (UTC) | Job | What it does |
|---|---|---|
| On `ops/docker/**` change | Forgejo `semantic-release` + runner | Tag, build, dual-publish, sign + attest by digest |
| Per release | DT upload (CI) | `POST /api/v1/bom` — **fail-soft** |
| Sun 02:10 | `dependency-track/sbom-uploader` | Scans ~160 running images → DT + Garage S3 |
| ~hourly | DT `PROJECTMETRICS` aggregation | Portfolio metric rollup |
| every 30 min | `cosign-pubkey` CronJob | Publishes Transit public key(s) → `cosign-webgrip-pub` |
| every 5 min | DT metrics exporter | Exposes `dt_portfolio_*` to VictoriaMetrics |
| continuous | GUAC `oci-collector` | Polls registries for attestations |
| weekly (Sun 05:20) | GUAC `s3-collector` | Ingests S3 SBOMs into the graph |

---

## Gaps and what's next

- **Promote Kyverno Audit → Enforce.** Gated on a real signed release verifying green with
  zero false positives (the `rekor.ignoreTlog` half is done). See the promotion gate above.
- **Fix the CLI test rule names.** `tests/cli/image-verification/kyverno-test.yaml` still
  names `verify-github-slsa-provenance` / `verify-cyclonedx-sbom`; update to
  `verify-webgrip-images` / `verify-webgrip-ghcr-images`.
- **First real Harbor SBOM column populate.** `sbom:create` is granted (`9938e09`); the next
  release should turn the `::warning:: HTTP 403` into a populated SBOM column — confirm live.
- **GHCR package visibility.** If `ghcr.io/webgrip/*` packages are private, add a `ghcr-pull`
  read-scoped credential to the GHCR policies so Kyverno can fetch manifests/attestations.
- **Leave Harbor's own Deployment-security / cosign gate OFF.** Harbor's signature check only
  verifies *a* signature exists (not against your key) and would block pulls of unsigned
  artifacts including the buildx `:cache` tag. Enforce only at Kyverno admission.

---

## Quick reference

| Service | In-cluster URL | External URL |
|---|---|---|
| Dependency-Track API | `http://dependency-track-api-server.security.svc.cluster.local:8080` | `https://dependency-track.${SECRET_DOMAIN}` |
| GUAC GraphQL | `http://graphql-server.security.svc.cluster.local:8080/query` | `https://guac.${SECRET_DOMAIN}` |
| Harbor (registry) | `harbor.${SECRET_DOMAIN}` (LAN-only) | — |
| OpenBao (Transit + auth/forgejo) | `http://openbao.security.svc.cluster.local:8200` | — |

| Resource | Namespace | Purpose |
|---|---|---|
| Transit key `cosign-webgrip` | OpenBao | ECDSA-P256 signing key; private half never leaves OpenBao |
| `cosign-webgrip-pub` ConfigMap | `security` | Public key(s) Kyverno verifies against; published by CronJob |
| `harbor-pull` secret | `security` | Robot pull cred Kyverno uses to fetch private Harbor manifests |
| `auth/forgejo` role `cosign-signer` | OpenBao | JWT role binding `repository`/`event_name=workflow_dispatch`/`ref=refs/heads/*` |
