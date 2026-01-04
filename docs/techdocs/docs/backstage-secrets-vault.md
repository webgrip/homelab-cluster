# Backstage + Vault + External Secrets (ESO)

This cluster runs Backstage with secrets sourced from Vault via External Secrets Operator (ESO), and CloudNativePG (CNPG) database credentials generated in-cluster and pushed into Vault.

This page documents the **current desired state in Git** for Backstage and how it interacts with Vault/ESO.

## Components and manifests

- Backstage app kustomization (includes the ExternalSecret):
  - [kubernetes/apps/backstage/backstage/app/kustomization.yaml](../../kubernetes/apps/backstage/backstage/app/kustomization.yaml)
- Backstage application secrets from Vault (creates `Secret/backstage-secrets`):
  - [kubernetes/apps/backstage/backstage/app/secret-externalsecret.yaml](../../kubernetes/apps/backstage/backstage/app/secret-externalsecret.yaml)
- Backstage CNPG DB bootstrap secret generated in-cluster (creates `Secret/backstage-db-secret`):
  - [kubernetes/apps/backstage/backstage/app/base/backstage-db-externalsecret.yaml](../../kubernetes/apps/backstage/backstage/app/base/backstage-db-externalsecret.yaml)
- Backstage DB credentials pushed into Vault:
  - [kubernetes/apps/backstage/backstage/app/base/pushsecret-vault.yaml](../../kubernetes/apps/backstage/backstage/app/base/pushsecret-vault.yaml)
- Flux dependency ordering for Backstage:
  - [kubernetes/apps/backstage/backstage/ks.yaml](../../kubernetes/apps/backstage/backstage/ks.yaml)

## High-level architecture

```mermaid
flowchart LR
  subgraph Vault[Vault KV v2]
    V1[kv/webgrip/prod/clusters/soyo/apps/backstage/app]
    V2[kv/webgrip/prod/clusters/soyo/apps/backstage/db]
  end

  subgraph ESO[External Secrets Operator]
    ES1[ExternalSecret backstage-secrets]
    GEN1[Password generator backstage-db-password]
    ES2[ExternalSecret backstage-db-secret]
    PS1[PushSecret backstage-db-credentials-to-vault]
  end

  subgraph K8s[Kubernetes]
    S1[Secret backstage-secrets]
    S2[Secret backstage-db-secret]
    CNPG[CNPG Cluster backstage-db]
    BS[Backstage Deployment]
  end

  V1 --> ES1 --> S1 --> BS

  GEN1 --> ES2 --> S2
  S2 --> CNPG
  S2 --> PS1 --> V2
```

## Vault paths used

### Backstage application secret bundle

Backstage’s application secret bundle is stored in Vault at:

- `kv/webgrip/prod/clusters/soyo/apps/backstage/app`

ESO reads this Vault secret using `dataFrom.extract` in [kubernetes/apps/backstage/backstage/app/secret-externalsecret.yaml](../../kubernetes/apps/backstage/backstage/app/secret-externalsecret.yaml) and creates/updates:

- `Secret/backstage-secrets` (namespace `backstage`)

Backstage consumes it via `envFrom.secretRef` in the Backstage deployment.

Expected keys in Vault (non-exhaustive; match what the manifest templates reference):

- `GITHUB_TOKEN`
- `AUTH_GITHUB_CLIENT_ID`
- `AUTH_GITHUB_CLIENT_SECRET`
- `GA_MEASUREMENT_ID`
- `OPENAPI_AI_KEY`
- `GITHUB_APP_ID`
- `GITHUB_APP_CLIENT_ID`
- `GITHUB_APP_CLIENT_SECRET`
- `GITHUB_APP_WEBHOOK_SECRET`
- `GITHUB_APP_PRIVATE_KEY` (multi-line)
- `BACKEND_SECRET`

Optional keys (if absent, ESO templates default them to empty):

- `SENTRY_TOKEN`
- `NEW_RELIC_REST_API_KEY`
- `NEW_RELIC_USER_KEY`
- `K8S_SERVICE_ACCOUNT_TOKEN_BACKSTAGE`
- `K8S_CONFIG_CA_DATA`

### Backstage DB credentials pushed into Vault

Backstage’s CNPG bootstrap Secret is generated in-cluster as:

- `Secret/backstage-db-secret` (namespace `backstage`)

A `PushSecret` then pushes that secret into Vault at:

- `kv/webgrip/prod/clusters/soyo/apps/backstage/db`

as properties:

- `username`
- `password`

This makes Vault a convenient lookup location for the DB credentials while keeping the CNPG bootstrap path fully GitOps-managed and secret-free.

## Reconciliation and ordering

Flux applies Backstage with explicit dependencies in [kubernetes/apps/backstage/backstage/ks.yaml](../../kubernetes/apps/backstage/backstage/ks.yaml):

- `cloudnative-pg` (CNPG operator) in namespace `cnpg-system`
- `external-secrets` and `external-secrets-stores` in namespace `external-secrets`

```mermaid
flowchart TB
  F[Flux] --> ES[external-secrets]
  ES --> STORES[external-secrets-stores]
  F --> CNPG[cloudnative-pg]
  STORES --> BS[backstage]
  CNPG --> BS
```

## End-to-end sequence

```mermaid
sequenceDiagram
  autonumber
  participant Vault
  participant ESO
  participant K8s as Kubernetes API
  participant CNPG
  participant Backstage

  rect rgb(240, 248, 255)
    Note over Vault: Operator writes app secrets to kv/webgrip/prod/clusters/soyo/apps/backstage/app
  end

  ESO->>Vault: Authenticate (Kubernetes auth)
  ESO->>Vault: Read kv/webgrip/prod/clusters/soyo/apps/backstage/app
  ESO->>K8s: Create/Update Secret/backstage-secrets

  ESO->>K8s: Generate password (Password generator)
  ESO->>K8s: Create/Update Secret/backstage-db-secret
  CNPG->>K8s: Read Secret/backstage-db-secret for initdb
  CNPG-->>K8s: Initialize Cluster (once)

  ESO->>Vault: Write kv/webgrip/prod/clusters/soyo/apps/backstage/db (PushSecret)

  Backstage->>K8s: Read envFrom Secret/backstage-secrets
  Backstage->>K8s: Read DB creds Secret/backstage-db-secret
```

## Vault policy requirements

For ESO to read `kv/webgrip/prod/clusters/soyo/apps/backstage/app`, the Vault policy bound to the ESO role must allow KV v2 reads:

- `read` on `kv/data/external-secrets/*`
- `read`/`list` on `kv/metadata/external-secrets/*`

For `PushSecret` to write `kv/webgrip/prod/clusters/soyo/apps/backstage/db`, the same policy must also allow:

- `create` and `update` on `kv/data/external-secrets/*`

(Exact policy lives in Vault; see [docs/techdocs/docs/external-secrets-vault.md](external-secrets-vault.md) for the one-time setup flow.)

## Notes and caveats

- Backstage environment variables are loaded at container start; after secrets change, Backstage Pods need a restart to pick them up.
- CNPG `initdb` runs once per cluster initialization; changing `backstage-db-secret` later does not retroactively change the database user password unless you run an explicit rotation procedure.
