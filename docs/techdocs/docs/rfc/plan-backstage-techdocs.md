# Plan: Backstage TechDocs (Option 2) — implementation checklist

> Status: **Executing** (build-out started 2026-08-09, after
> [rfc-docs-platform-2026](rfc-docs-platform-2026.md) reaffirmed the bet) · Date: 2026-06-18 ·
> For [ADR-0039](../adr/adr-0039-backstage-techdocs.md) /
> [RFC: Backstage TechDocs](rfc-backstage-techdocs.md). Sequenced **after** the Codeberg interim
> ([ADR-0038](../adr/adr-0038-codeberg-pages-techdocs.md)) is live.
>
> 2026-08-09 corrections discovered during build-out: the catalog entity is
> **`homelab/component/homelab-cluster`** (namespace `homelab`, not the `default` assumed below),
> and the Backstage app-config lands as an opt-in **`app-config.k8s.yaml` overlay** in
> `webgrip/backstage-application` (the image loads only `app-config.yaml` by default; the
> Deployment opts in via container args) rather than an edit to the baked-in config.

This is the concrete, ordered work to make Backstage the primary TechDocs surface while keeping
Codeberg as the off-site DR mirror. Each phase is independently revertable.

## Phase 0 — Prerequisites
- [x] Confirm Backstage is healthy and SSO (Authentik) login works. *(2026-08-09: pod 1/1, 6d uptime)*
- [x] Confirm Garage is reachable in-cluster (S3 endpoint
      `http://garage-s3.garage.svc.cluster.local:3900`, path-style) — same store as
      [ADR-0018](../adr/adr-0018-registry-blob-storage-garage-s3.md).
- [x] Decide the bucket name (`techdocs`) and the canonical entity ref
      (**`homelab/component/homelab-cluster`** — see header note).

## Phase 1 — Storage (Garage) — *landed 2026-08-09, commit c0eb1ba7; verified live*
- [x] Create a Garage bucket `techdocs` (`garage-techdocs-bootstrap` Job,
      `kubernetes/apps/garage/garage/bootstrap/techdocs.job.yaml`).
- [x] Create access keys scoped to `techdocs`: **read-write** `techdocs-publish` for CI and
      **read-only** `techdocs-read` for Backstage (two keys, least-privilege).
- [x] Store key material in OpenBao at `garage/techdocs` (PushSecret
      `techdocs.pushsecret.yaml`; properties `publish_*`/`read_*`).
- [x] ExternalSecret → `backstage` namespace: surfaces the **read** key
      (`backstage/backstage/app/techdocs-s3.externalsecret.yaml`; Deployment consumes via
      envFrom, `optional: true`).
- [x] ExternalSecret + `forgejo-actions-secrets` CronJob: publish the **publish** key to the
      `webgrip` org as Actions secrets (mirror the `HARBOR_ROBOT_*` pattern):
      `TECHDOCS_S3_ACCESS_KEY_ID`, `TECHDOCS_S3_SECRET_ACCESS_KEY`, and vars
      `TECHDOCS_S3_ENDPOINT`, `TECHDOCS_S3_BUCKET`, `TECHDOCS_S3_REGION`.
- [x] *(added)* NetworkPolicies: backstage→garage:3900, CI-runner→garage:3900
      (`forgejo-runner-allow-garage`; agent-runner excluded per ADR-0048), garage ingress from both.

## Phase 2 — Backstage config
- [ ] In Backstage `app-config` add the TechDocs block:
  ```yaml
  techdocs:
    builder: 'external'          # serve prebuilt docs; never build on read
    publisher:
      type: 'awsS3'
      awsS3:
        bucketName: 'techdocs'
        endpoint: 'http://garage.<ns>.svc.cluster.local:3900'  # Garage S3
        region: 'garage'
        s3ForcePathStyle: true
        credentials:
          accessKeyId:    ${TECHDOCS_S3_ACCESS_KEY_ID}
          secretAccessKey: ${TECHDOCS_S3_SECRET_ACCESS_KEY}
  ```
- [x] Wire the S3 creds env into the Backstage Deployment from the ExternalSecret
      *(2026-08-09: envFrom `backstage-techdocs-s3`, `optional: true`; non-secret
      `TECHDOCS_*` env in `configmap.yaml`; the techdocs block itself lives in
      `app-config.k8s.yaml` in webgrip/backstage-application — see header note)*.
- [ ] Roll Backstage; confirm it starts and the TechDocs plugin loads (docs will 404 until
      published — expected). *(Blocked on the backstage-application release ≥1.1.0 carrying
      app-config.k8s.yaml; then bump the image digest AND add the container args
      `["packages/backend", "--config", "app-config.yaml", "--config", "app-config.k8s.yaml"]`
      in the same commit.)*

## Phase 3 — Catalog entity
- [x] Catalog entity with `backstage.io/techdocs-ref` exists —
      `catalog/components/homelab-cluster.yaml`, entity ref
      **`homelab/component/homelab-cluster`** (predates this plan's `default/` assumption).
- [x] Registered via the root `catalog-info.yaml` Location + GitHub discovery.
- [ ] Confirm the entity shows in the catalog with a (empty) **Docs** tab.

## Phase 4 — CI publish job — *landed 2026-08-09*
- [x] Reusable `webgrip/workflows/.forgejo/workflows/techdocs-deploy-backstage-s3.yml`
      (workflows@7495a4f): downloads the `techdocs-site` artifact and runs
      `techdocs-cli publish --publisher-type awsS3 --awsEndpoint … --awsS3ForcePathStyle
      --entity homelab/component/homelab-cluster` with creds/vars from the org secrets.
- [x] `.forgejo/workflows/on_docs_change.yml` in THIS repo calls generate →
      `deploy-backstage` (primary) + `deploy-codeberg` (DR) — both consume the same artifact.
      **Codeberg leg blocked**: the non-mirror Codeberg repo was never created (the ADR-0038
      §Ops handoff; `webgrip/homelab-cluster-techdocs` 404s, as does infrastructure's).
- [x] Jobs run `runs-on: docker`, `container: harbor.webgrip.dev/ghcr/webgrip/techdocs-builder`
      (the runner image is redundant for CI — see techdocs-generate.yml's rationale).

## Phase 5 — Cutover + verify
- [ ] Trigger a docs change (push under `docs/techdocs/**`).
- [ ] Verify the object layout in the `techdocs` bucket (`<ns>/<kind>/<name>/index.html`).
- [ ] Verify docs render at `backstage.webgrip.dev/docs/default/component/homelab-cluster`, search
      works, and SSO gates access.
- [ ] Verify the Codeberg DR copy still publishes (off-site mirror intact).
- [ ] Announce Backstage as the primary docs URL; keep `docs.webgrip.dev` (Codeberg) as public/DR.

## Rollback
- Remove/disable the `deploy-backstage` job → Codeberg remains the live host (no data loss; the
  Garage bucket can be emptied later). Backstage config revert is a single `app-config` change.

## Out of scope (follow-ups)
- Multi-entity docs (per-service catalog entities) once more repos publish TechDocs.
- TechDocs search backend tuning (Lunr vs a search engine) if the doc set grows large.
- Signing the published docs objects (tie-in to the supply-chain story) — only if we later want
  docs provenance.
