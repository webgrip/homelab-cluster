# RFC: Backstage TechDocs as the in-cluster docs surface

> Status: **Proposed** · Date: 2026-06-18 · Owner: Ryan Grippeling (`ryan@webgrip.nl`)
> · Decision: [ADR-0023 (Backstage TechDocs)](../adr/adr-0023-backstage-techdocs.md)
> · Plan: [Backstage TechDocs plan](plan-backstage-techdocs.md)
> · Supersedes (as primary): [ADR-0022 (Codeberg Pages, interim)](../adr/adr-0022-codeberg-pages-techdocs.md)

## 1. Why

The interim host ([ADR-0022](../adr/adr-0022-codeberg-pages-techdocs.md)) gets the docs *served* and gives
us off-site DR, but it is a bare static site: public-only, no search, no link from the service
catalog. Our docs are authored as **Backstage TechDocs**, and **Backstage already runs in-cluster**
— so the integrated experience is config away, not a new platform. This RFC designs that step and
the migration from Codeberg-primary to Backstage-primary.

## 2. Architecture

```
build (CI, Forgejo)                Garage S3 (in-cluster)           Backstage (in-cluster)
  techdocs-cli generate  ──┐        bucket: techdocs                 TechDocs plugin
                           ├─ techdocs-cli publish ──► s3://techdocs/<ns>/<kind>/<name>/...
  artifact techdocs-site ──┘        (awsS3 publisher)                builder: external
                                                                     publisher: awsS3 ──► reads bucket
                           └─ (DR) push to Codeberg pages branch     serves /docs/<ns>/<kind>/<name>
                                                                     behind Authentik SSO + search
```

Key choices:

- **`builder: external`** — Backstage **never builds docs on read**; it only serves what CI
  published. This keeps the Backstage pods light and avoids giving the frontend a toolchain.
- **`publisher.type: awsS3`** against **Garage** — Garage is S3-compatible and already our blob
  store ([ADR-0002](../adr/adr-0002-registry-blob-storage-garage-s3.md)). A dedicated `techdocs` bucket,
  path-style addressing, plain-HTTP in-cluster endpoint, creds from OpenBao.
- **Entity-keyed layout** — `techdocs-cli publish --entity <ns>/<kind>/<name>` writes under a path
  Backstage resolves from each entity's `backstage.io/techdocs-ref` annotation.
- **SSO** — Backstage already authenticates via Authentik; docs inherit it, enabling **private**
  docs (impossible on Codeberg Pages).

## 3. Catalog requirements

Each docs set needs a catalog entity. For this repo:

```yaml
# catalog-info.yaml (in the repo root)
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: homelab-cluster
  annotations:
    backstage.io/techdocs-ref: dir:docs/techdocs   # where the mkdocs site lives
spec:
  type: documentation
  lifecycle: production
  owner: platform
```

The entity is registered in the Backstage catalog (static `app-config` location or a discovery
rule). `techdocs-cli publish --entity default/component/homelab-cluster` then targets it.

## 4. CI changes

`on_docs_change.yml` keeps its `generate` job (unchanged) and gains a **primary** publish job:

- `deploy-backstage` — `runs-on: docker`, container `webgrip/techdocs-runner`; downloads the
  `techdocs-site` artifact and runs
  `techdocs-cli publish --publisher-type awsS3 --storage-name techdocs --entity <…>` with the Garage
  S3 endpoint + creds (org Actions secrets from OpenBao).
- `deploy-codeberg` — unchanged from [ADR-0022](../adr/adr-0022-codeberg-pages-techdocs.md); stays as the
  off-site DR copy.

Both consume the same artifact, so there is **no second build**.

## 5. Cluster changes

- **Garage**: a `techdocs` bucket + an access key scoped to it; key material in OpenBao
  (`garage/techdocs`), surfaced to CI as org Actions secrets and to Backstage as an ExternalSecret.
- **Backstage `app-config`**: the `techdocs` block (`builder: external`, `publisher.type: awsS3`,
  endpoint/region/forcePathStyle, bucketName) + the S3 creds env from the ExternalSecret.
- **No new workload** — Backstage and Garage already exist; this is configuration + a bucket + keys.

## 6. Migration from Codeberg-primary

1. Land the Garage bucket + Backstage config (docs not yet published → 404 in Backstage, harmless).
2. Add the `deploy-backstage` job; trigger a docs change; confirm the entity's docs render in
   Backstage.
3. Flip the canonical `docs.webgrip.dev` expectation: announce Backstage as the primary URL;
   **keep Codeberg** for off-site/public access.
4. No teardown — Codeberg stays as DR.

See the [plan](plan-backstage-techdocs.md) for the step-by-step.

## 7. Risks

- **Catalog drift** — if the entity/annotation is wrong, docs 404 in Backstage. Mitigated by a
  catalog-info smoke check in CI.
- **Garage endpoint/creds in CI** — scoped key, OpenBao-sourced, masked. Read-write for publish;
  Backstage gets read-only.
- **Backstage availability** — an outage hides the primary docs; Codeberg DR covers it. This is the
  whole reason Codeberg is retained.
- **`external` builder gotcha** — if Backstage is left on the default (`local`) builder it would try
  to build on read (needs a toolchain); the config must pin `external`.
