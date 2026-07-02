# Container Supply Chain — Architecture Overview

> Status: living · Companion to the [Supply Chain Intelligence Pipeline](supply-chain-pipeline.md),
> [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md),
> the [Transit key-rotation runbook](../runbooks/cosign-transit-key-rotation.md), and
> [ADR-0020 (Codeberg mirror)](../adr/adr-0020-codeberg-offsite-push-mirror.md).

How webgrip images get built, signed, published, verified, and analysed — and where identity and
secrets come from. **Solid arrows = built/active flow; dotted = trust / verify / planned.**
Colours group by domain (see the system map).

## 1. System map

```mermaid
%%{init: {'theme':'base','fontFamily':'Inter, Segoe UI, system-ui, sans-serif','themeVariables':{'fontSize':'13px','lineColor':'#78909c','primaryTextColor':'#102027'},'flowchart':{'curve':'basis','padding':14,'nodeSpacing':45,'rankSpacing':55}}}%%
flowchart TB
  dev(["👤 Developer / Renovate"])

  subgraph FORGE["🪵 FORGE — Forgejo v15+ (in-cluster, LAN)"]
    repo["webgrip/* repos<br/><i>builds 10 images</i>"]
    fjoidc["OIDC issuer · /api/actions<br/><i>per-job token: repo, event, ref</i>"]
  end

  subgraph CI["⚙️ CI — in-cluster Runner (KEDA · DinD · runs-on docker)"]
    srel["semantic-release<br/><i>cut release tag per image</i>"]
    build["build + push<br/><i>publish image</i>"]
    syft["Syft → CycloneDX/SPDX SBOM"]
    sign["cosign sign + attest by digest"]
  end

  subgraph IDS["🔐 IDENTITY & SECRETS"]
    authentik["Authentik — <b>humans</b><br/><i>SSO</i>"]
    subgraph OB["OpenBao — <b>machines</b>"]
      jwtauth["JWT auth · auth/forgejo<br/><i>role claim-bound: workflow_dispatch@branch signs</i>"]
      transit["Transit key · cosign-webgrip<br/><i>private key never leaves</i>"]
      kv["KV: Harbor robot, DT key<br/><i>+ dynamic PKI/SSH/cloud later</i>"]
      oidcp["OIDC provider · identity/oidc<br/><i>mint tokens for cloud (future)</i>"]
    end
  end

  subgraph REG["📦 REGISTRY"]
    harbor["Harbor · private/LAN<br/>harbor.${SECRET_DOMAIN}/webgrip/*"]
    ghcr["ghcr.io/webgrip/*<br/><i>dual-published by Forgejo CI, same key</i>"]
    dhproxy["Docker Hub pull-through cache"]
  end

  subgraph GITOPS["🔄 GITOPS — Flux"]
    flux["source · kustomize · helm"]
    fluxverify["spec.verify cosign on OCI charts<br/><i>future</i>"]
  end

  subgraph ADM["🛡️ ADMISSION — Kyverno (Audit→Enforce)"]
    kverify["verify image sig + require SBOM<br/><i>only signed first-party images run</i>"]
  end

  subgraph SCA["🔎 SUPPLY-CHAIN ANALYSIS"]
    trivyop["Trivy Operator"]
    dt["Dependency-Track"]
    guac["GUAC graph"]
  end

  subgraph APPS["🚀 PERIPHERAL APPS"]
    apps["Grafana · SearxNG · Backstage · n8n · …"]
  end

  subgraph MIRR["🌐 OFF-SITE MIRRORS & DOCS"]
    gh["GitHub<br/><i>push-mirror = break-glass source</i>"]
    codeberg["Codeberg<br/><i>2nd off-site mirror · ADR-0020</i>"]
    docs["TechDocs → pages"]
  end

  dev -->|push / PR| repo
  repo -->|ops/docker/** changed| srel
  srel -->|release published| build
  build -->|push image| harbor
  build -->|push image| ghcr
  build --> syft --> sign
  sign -->|attach sig + SBOM| harbor
  sign -->|attach sig + SBOM| ghcr

  sign ==>|"1 · per-job OIDC token"| fjoidc
  fjoidc ==>|"2 · present JWT"| jwtauth
  jwtauth ==>|"3a · scoped token"| transit
  jwtauth -.->|"3b · target: fetch CI creds"| kv
  sign ==>|cosign --key hashivault| transit

  flux -->|reconcile · in-cluster URL| repo
  flux -->|deploy| apps
  apps -->|pull| harbor
  flux --> fluxverify
  fluxverify -.->|verify chart sig| harbor

  transit -.->|public key → ConfigMap| kverify
  kverify -.->|verify sig + SBOM at admission| harbor

  trivyop --> dt
  trivyop --> guac
  harbor -.->|attestations · planned| guac
  dt <--> guac
  dhproxy --> harbor

  authentik -->|SSO| apps
  authentik -->|SSO| harbor
  authentik -->|SSO| repo
  oidcp -.->|machine OIDC → cloud · future| ghcr

  repo -->|push-mirror · zero release Actions| gh
  repo -->|push-mirror| codeberg
  docs --> codeberg

  classDef forge fill:#e8eaf6,stroke:#3949ab,color:#102027;
  classDef ci fill:#e3f2fd,stroke:#1565c0,color:#102027;
  classDef sec fill:#fff8e1,stroke:#f57f17,color:#102027;
  classDef reg fill:#e8f5e9,stroke:#2e7d32,color:#102027;
  classDef gitops fill:#e0f7fa,stroke:#00838f,color:#102027;
  classDef adm fill:#f3e5f5,stroke:#7b1fa2,color:#102027;
  classDef sca fill:#e0f2f1,stroke:#00897b,color:#102027;
  classDef apps fill:#eceff1,stroke:#546e7a,color:#102027;
  classDef mirr fill:#efebe9,stroke:#6d4c41,color:#102027;
  classDef person fill:#ffffff,stroke:#37474f,color:#102027;
  class dev person;
  class repo,fjoidc forge;
  class srel,build,syft,sign ci;
  class authentik,jwtauth,transit,kv,oidcp sec;
  class harbor,ghcr,dhproxy reg;
  class flux,fluxverify gitops;
  class kverify adm;
  class trivyop,dt,guac sca;
  class apps apps;
  class gh,codeberg,docs mirr;
  style OB fill:#fffdf5,stroke:#f9a825,stroke-dasharray:4 3;
```

### How to read it
- **Thick arrows (1→2→3) are the signing spine.** A Forgejo job proves identity with a *per-job*
  OIDC token whose claims (`event_name=workflow_dispatch`, `ref=refs/heads/*`) are the authorization → OpenBao checks the
  claims → returns a *scoped, short-lived* token → cosign signs via Transit (key never leaves OpenBao).
  (The build/sign job is reached via `workflow_dispatch` on a branch, **not** a tag-`release` event —
  binding the OpenBao role to `event_name=release` + `refs/tags/*` 400s the login.)
- **`3b` (dotted) is the unification target.** Harbor/DT creds reach CI as Forgejo org secrets today
  (a CronJob); the goal is to fetch them over the same spine so there are **zero** standing Forgejo secrets.
- **Two dotted "verify" arrows are the gates.** Flux verifies *charts* before deploy; Kyverno verifies
  *images* (signature + SBOM) at admission using the Transit **public** key.
- **Dual-publish** (`.github`→ghcr, `.forgejo`→Harbor) is the migration safety net; **mirrors**
  (GitHub/Codeberg) are DR for the Git source. **Gold = identity/secrets; humans via Authentik, machines via OpenBao.**

## 2. The release job (sequence)

Build and sign run as *separate* ephemeral runner pods; shown as one "Runner" lane for readability.

```mermaid
%%{init: {'theme':'base','fontFamily':'Inter, Segoe UI, system-ui, sans-serif','themeVariables':{'fontSize':'13px','actorBkg':'#e8eaf6','actorBorder':'#3949ab','actorTextColor':'#102027','actorLineColor':'#90a4ae','signalColor':'#455a64','signalTextColor':'#102027','labelBoxBkgColor':'#eceff1','labelTextColor':'#102027','noteBkgColor':'#fff8e1','noteBorderColor':'#f9a825','noteTextColor':'#5d4037','activationBkgColor':'#cfd8dc','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    autonumber
    box rgb(232,234,246) People & Forge
      actor dev as Dev / semantic-release
      participant fj as Forgejo · OIDC issuer
    end
    box rgb(227,242,253) CI
      participant run as Runner · DinD
    end
    box rgb(255,248,225) Identity & Secrets
      participant bao as OpenBao · auth/forgejo + Transit
    end
    box rgb(232,245,233) Registry & analysis
      participant harbor as Harbor
      participant dt as Dependency-Track / GUAC
    end
    box rgb(224,247,250) Cluster · deploy
      participant flux as Flux
      participant kyv as Kyverno
    end

    Note over dev,fj: Source change → release
    dev->>fj: push to ops/docker/** (on_source_change)
    fj->>run: schedule semantic-release job
    run->>fj: create release tag IMG-vVER
    run->>fj: POST workflow_dispatch (per image, tag input)
    fj-->>run: dispatch on_release_published (event_name=workflow_dispatch, branch ref)

    rect rgb(237,243,251)
    Note over run,harbor: Job 1 — build + push (release-distribute-harbor)
    run->>run: parse tag → IMG, VER
    run->>harbor: docker login (HARBOR_ROBOT, target via OpenBao)
    run->>harbor: buildx build + push harbor.webgrip.dev/webgrip/IMG:VER
    harbor-->>run: pushed (digest sha256 …)
    end

    rect rgb(237,247,239)
    Note over run,bao: Job 2 — sign + attest (enable-openid-connect)
    run->>fj: GET ACTIONS_ID_TOKEN_REQUEST_URL + audience=openbao-cosign (? vs & per existing query)
    fj-->>run: per-job OIDC JWT (claims repository, event_name=workflow_dispatch, ref=refs/heads/*)
    run->>bao: POST auth/forgejo/login {role cosign-signer, jwt}
    bao->>fj: fetch OIDC discovery + JWKS
    fj-->>bao: JWKS
    bao->>bao: verify iss + bound_claims (repo / event_name=workflow_dispatch / refs/heads/*)
    bao-->>run: scoped token (TTL 10m, Transit sign-only)
    run->>harbor: docker login + resolve digest (imagetools inspect)
    run->>run: syft → CycloneDX + SPDX SBOM
    run->>bao: cosign sign --key hashivault (transit/sign)
    bao-->>run: signature (private key never leaves OpenBao)
    run->>harbor: push cosign signature (by digest)
    run->>bao: cosign attest CycloneDX (transit/sign)
    bao-->>run: signed attestation
    run->>harbor: push SBOM attestation
    run->>dt: POST /api/v1/bom (CycloneDX, autoCreate) — fail-soft
    dt-->>run: 200
    end

    rect rgb(252,247,237)
    Note over flux,kyv: Later — deploy / admission
    flux->>harbor: pull image (GitOps deploy)
    kyv->>harbor: fetch image + signature + SBOM attestation
    kyv->>kyv: verify sig vs Transit pubkey (ConfigMap) + require CycloneDX SBOM
    kyv-->>flux: admit (Audit now → Enforce later)
    end
```

### Security-critical moments
- **10–11:** the runner proves identity with a *per-job* OIDC token; a fork PR gets no token.
  Append `audience=openbao-cosign` to `ACTIONS_ID_TOKEN_REQUEST_URL` with the right separator
  (`?` if the URL has no query string, else `&`) — a malformed URL silently mints the *default*
  audience and OpenBao 400s the login.
- **12–16:** OpenBao independently verifies that token against Forgejo's JWKS + the bound claims
  (`event_name=workflow_dispatch`, `ref=refs/heads/*`) before issuing a 10-minute, sign-only token.
- **19–22:** signing/attesting call `transit/sign` — the key material never reaches the runner.
- **29:** Kyverno re-checks signature + SBOM at admission against the **public** (Transit) key.

## 3. Prerequisites to go live

See the [Kyverno audit→enforce RFC](../rfc/rfc-kyverno-audit-enforce-hardening.md) for the full gate list (the standalone enforcement roadmap was retired into it, 2026-07-02).
In short: Forgejo server ≥ v15 (for `enable-openid-connect`); a one-time OpenBao break-glass on the
*existing* cluster to enable Transit + the `forgejo` jwt auth and create the key (a fresh rebuild does
this automatically via init.sh); the `cosign-pubkey` CronJob then publishes the public key to the
`cosign-webgrip-pub` ConfigMap — no manual paste; runner→OpenBao/Harbor/Dependency-Track and OpenBao→Forgejo
network reachability.
