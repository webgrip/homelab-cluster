# Plan: Backstage TechDocs (Option 2) — implementation checklist

> Status: **Planned** · Date: 2026-06-18 · For [ADR-0039](../adr/adr-0039-backstage-techdocs.md) /
> [RFC: Backstage TechDocs](rfc-backstage-techdocs.md). Sequenced **after** the Codeberg interim
> ([ADR-0038](../adr/adr-0038-codeberg-pages-techdocs.md)) is live.

This is the concrete, ordered work to make Backstage the primary TechDocs surface while keeping
Codeberg as the off-site DR mirror. Each phase is independently revertable.

## Phase 0 — Prerequisites
- [ ] Confirm Backstage is healthy and SSO (Authentik) login works.
- [ ] Confirm Garage is reachable in-cluster (S3 endpoint, e.g. `http://10.0.0.110:3900`,
      path-style) — same store as [ADR-0018](../adr/adr-0018-registry-blob-storage-garage-s3.md).
- [ ] Decide the bucket name (`techdocs`) and the canonical entity ref
      (`default/component/homelab-cluster`).

## Phase 1 — Storage (Garage)
- [ ] Create a Garage bucket `techdocs`.
- [ ] Create an access key scoped to `techdocs`: **read-write** for CI publish, and a **read-only**
      key for Backstage (or one key, least-privilege preferred).
- [ ] Store key material in OpenBao at `garage/techdocs` (`access_key_id`, `secret_access_key`).
- [ ] ExternalSecret → `backstage` namespace: surfaces the **read** key to Backstage.
- [ ] ExternalSecret + `forgejo-actions-secrets` CronJob: publish the **publish** key to the
      `webgrip` org as Actions secrets (mirror the `HARBOR_ROBOT_*` pattern):
      `TECHDOCS_S3_ACCESS_KEY_ID`, `TECHDOCS_S3_SECRET_ACCESS_KEY`, and vars
      `TECHDOCS_S3_ENDPOINT`, `TECHDOCS_S3_BUCKET`, `TECHDOCS_S3_REGION`.

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
- [ ] Wire the S3 creds env into the Backstage Deployment from the ExternalSecret.
- [ ] Roll Backstage; confirm it starts and the TechDocs plugin loads (docs will 404 until
      published — expected).

## Phase 3 — Catalog entity
- [ ] Add `catalog-info.yaml` to the repo root with
      `backstage.io/techdocs-ref: dir:docs/techdocs` (see [RFC §3](rfc-backstage-techdocs.md)).
- [ ] Register the entity in the Backstage catalog (static location or discovery).
- [ ] Confirm the entity shows in the catalog with a (empty) **Docs** tab.

## Phase 4 — CI publish job
- [ ] Add a reusable `webgrip/workflows/.forgejo/workflows/techdocs-deploy-backstage-s3.yml`:
      downloads the `techdocs-site` artifact and runs
      `techdocs-cli publish --publisher-type awsS3 --storage-name techdocs
      --entity default/component/homelab-cluster` with the S3 endpoint/creds from secrets/vars.
- [ ] Wire `on_docs_change.yml` to call it as the **primary** `deploy-backstage` job, **keeping**
      the existing `deploy-codeberg` job as DR (both consume the same artifact — no rebuild).
- [ ] Keep the job on `runs-on: docker`, `container: webgrip/techdocs-runner`.

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
