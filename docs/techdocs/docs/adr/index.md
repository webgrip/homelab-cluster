# Architecture Decision Records

One defensible decision per record — the durable answer to *"why is it built this way?"*.
Design exploration lives in [RFCs](../rfc/index.md); an RFC is the umbrella, its ADRs are the
individual choices. Operational procedure lives in [runbooks](../runbooks/index.md).
Coverage of the whole estate — which domains have records, which don't — is mapped in the
[decision landscape](landscape.md) (audited 2026-07-02).

## Conventions

- **Location:** `docs/techdocs/docs/adr/adr-NNNN-<kebab-title>.md`, zero-padded, monotonically
  increasing, never reused. Start from the template: [adr-0000-template.md](adr-0000-template.md).
- **No front-matter.** `# H1` states the decision, then a one-line
  `> Status: **…** · Date: …` banner. Sections: Context → Decision → Alternatives considered
  (omit if none) → Consequences → Status log.
- **ADRs are records, not living docs.** When reality changes (revert, partial rollout,
  supersession), append a dated line to the ADR's **Status log** and update the status banner —
  never silently rewrite the body. A reversed decision gets a *new* ADR that supersedes the old.
- Register every new ADR in the table below.

## Status legend

| Status | Meaning |
| ------ | ------- |
| **Proposed** | Decided to pursue, not yet ratified/implemented end-to-end. |
| **Accepted** | Decided. Current source of truth. |
| **Rejected** | Considered and declined; kept to prevent re-derivation. |
| **Superseded** | Replaced by a later ADR (banner links to it). Never deleted. |
| **Deprecated** | No longer relevant, not directly replaced. |

*"· amended"* = the Status log records a material change (rollback, scope change, re-ratification).

## Records

| ADR | Decision | Status | Date |
| --- | -------- | ------ | ---- |
| [0001](adr-0001-adopt-harbor.md) | Adopt Harbor as the self-hosted OCI registry | Accepted | 2026-06-12 |
| [0002](adr-0002-registry-blob-storage-garage-s3.md) | Registry blob storage on Garage S3 | Accepted | 2026-06-12 |
| [0003](adr-0003-external-cnpg-database.md) | External CNPG Postgres for Harbor | Accepted | 2026-06-12 |
| [0004](adr-0004-chart-internal-redis.md) | Use Harbor's chart-bundled Redis | Accepted | 2026-06-12 |
| [0005](adr-0005-lan-only-exposure.md) | Expose Harbor LAN-only via envoy-internal | Accepted | 2026-06-12 |
| [0006](adr-0006-authentik-oidc-phased.md) | Authenticate Harbor via Authentik OIDC, phased | Accepted | 2026-06-12 |
| [0007](adr-0007-cilium-wireguard-encryption.md) | Transparent pod-to-pod encryption via Cilium WireGuard | Accepted | 2026-06-12 |
| [0008](adr-0008-rootless-ci-image-builds.md) | Rootless CI image builds (drop privileged Docker-in-Docker) | Proposed · amended | 2026-06-12 |
| [0009](adr-0009-secret-rotation-model.md) | Secret rotation model — vault write + Reloader | Accepted | 2026-06-12 |
| [0010](adr-0010-openbao-dynamic-postgres-credentials.md) | OpenBao database engine for short-lived Postgres credentials | Accepted · amended | 2026-06-12 |
| [0011](adr-0011-dual-run-renovate-forgejo.md) | Dual-run Renovate across GitHub and Forgejo | Accepted | 2026-06-13 |
| [0012](adr-0012-forgejo-static-bot-pat.md) | Authenticate Renovate to Forgejo with a static bot PAT | Accepted | 2026-06-13 |
| [0013](adr-0013-github-as-renovate-data-oracle.md) | Keep GitHub as a read-only data oracle during the cutover | Accepted · amended | 2026-06-13 |
| [0014](adr-0014-flux-source-forgejo.md) | Make Forgejo the authoritative GitOps source for Flux | Proposed | 2026-06-13 |
| [0015](adr-0015-external-bootstrap-fallback-source.md) | External mirror as cold-bootstrap + break-glass source | Proposed | 2026-06-13 |
| [0016](adr-0016-harbor-pull-through-proxy-cache.md) | Harbor pull-through proxy cache for third-party images | Accepted | 2026-06-13 |
| [0017](adr-0017-registry-mirror-talos-spegel.md) | Harbor mirror at the Talos/containerd layer, with Spegel | Accepted | 2026-06-13 |
| [0018](adr-0018-harbor-config-idempotent-job.md) | Harbor proxy config via an idempotent API CronJob | Accepted | 2026-06-13 |
| [0019](adr-0019-bootstrap-task-pattern.md) | Bootstrap / one-shot tasks — pick the lowest trigger tier | Accepted | 2026-06-14 |
| [0020](adr-0020-codeberg-offsite-push-mirror.md) | Codeberg as a second off-site push-mirror | Proposed | 2026-06-17 |
| [0021](adr-0021-cilium-gateway-egress-for-oidc.md) | Identity-based egress to the gateway for server-side OIDC | Accepted · superseded in scope by 0039 | 2026-06-17 |
| [0022](adr-0022-codeberg-pages-techdocs.md) | Serve TechDocs from Codeberg Pages (interim + off-site) | Accepted | 2026-06-18 |
| [0023](adr-0023-backstage-techdocs.md) | TechDocs served by Backstage + Garage S3 (target) | Proposed | 2026-06-18 |
| [0024](adr-0024-forgejo-leading-application-repos.md) | Forgejo-authoritative application repos (de-mirror) | Accepted | 2026-06-18 |
| [0025](adr-0025-node-taxonomy.md) | Capability-based node taxonomy; retire fringe/nodegroup | Accepted | 2026-06-19 |
| [0026](adr-0026-confine-longhorn-to-workers.md) | Confine Longhorn storage to the worker nodes | Accepted · amended | 2026-06-19 |
| [0027](adr-0027-longhorn-hot-cold-tiers.md) | Longhorn hot/cold storage tiers from node annotations | Proposed · amended | 2026-06-19 |
| [0028](adr-0028-application-workload-placement.md) | Pin application workloads to the worker pool (hard) | Accepted · amended | 2026-06-19 |
| [0029](adr-0029-storageclass-consolidation.md) | Consolidate Longhorn StorageClasses | Proposed · amended | 2026-06-19 |
| [0030](adr-0030-grafana-threshold-rule-shape.md) | Standardize + lint the Grafana threshold alert-rule shape | Accepted | 2026-06-21 |
| [0031](adr-0031-meta-monitoring-alert-rule-health.md) | Meta-monitoring of Grafana alert-rule health | Accepted · amended | 2026-06-21 |
| [0032](adr-0032-reenable-pyroscope-worker-pool.md) | Re-enable Pyroscope, hard-pinned to the worker pool | Accepted | 2026-06-21 |
| [0033](adr-0033-kyverno-enforce-promotion-policy.md) | Gated Kyverno audit→enforce promotion + mandatory tests | Accepted | 2026-06-21 |
| [0034](adr-0034-approved-registries-stays-audit.md) | `require-approved-registries` stays Audit | Accepted | 2026-06-21 |
| [0035](adr-0035-action-clone-wall.md) | Action-clone wall — measure first; no offline mode exists | Accepted | 2026-06-25 |
| [0036](adr-0036-amd64-default-constrictor-build.md) | amd64-by-default builds via the constrictor fast workflow | Accepted | 2026-06-25 |
| [0037](adr-0037-storage-engine-gated-on-dedicated-disks.md) | Storage engine stays Longhorn v1; v2/LINSTOR gated on disks | Accepted | 2026-07-01 |
| [0038](adr-0038-victoriametrics-metrics-backend.md) | VictoriaMetrics replaces kube-prometheus-stack | Accepted · amended | 2026-07-01 |
| [0039](adr-0039-default-deny-network-policies.md) | Opt-in per-namespace default-deny NetworkPolicies | Accepted | 2026-07-01 |
