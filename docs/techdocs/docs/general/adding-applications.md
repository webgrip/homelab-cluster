# Adding applications

**The authoritative recipe is the `add-app` skill** (`.claude/skills/add-app/SKILL.md`) — it owns
the scaffold, current conventions, and gotchas. Companion skills: `external-secrets` (ESO +
OpenBao), `cnpg-database` (Postgres), `authentik-oidc` (SSO), `workload-placement` (node
pinning), `flux-validate` (pre-commit checks).

Skeletal outline (details live in the skills):

1. **`ks.yaml`** — Flux Kustomization under `kubernetes/apps/<ns>/<app>/` with
   `postBuild.substituteFrom: cluster-secrets` and `dependsOn` for platform services.
2. **HelmRelease** — bjw-s `app-template` from OCI for most apps; raw manifests + Kustomize for
   bespoke ones (see `invoiceninja`).
3. **HTTPRoute** — `envoy-internal` (LAN) or `envoy-external` (public), hostname
   `<app>.${SECRET_DOMAIN}`. Inventory: [Applications](applications.md).
4. **Secrets** — `ExternalSecret` (OpenBao KV or `password-generator`); consume via
   `existingSecret`/`envFrom`. No new SOPS files.
5. **Placement + storage** — worker-pool component for write-heavy/stateful workloads; Longhorn
   StorageClass explicitly set (no cluster default). CNPG `Cluster` if Postgres is needed.
6. **Validate** — `./scripts/run-flux-local-test.sh` before committing.

Observability wiring (ServiceMonitor, alerts, dashboards): [Observability](observability.md),
`victoriametrics` + `grafana-dashboard` skills.
