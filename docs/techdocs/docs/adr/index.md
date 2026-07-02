# Architecture Decision Records

One defensible decision per record — the durable answer to *"why is it built this way?"*.
Design exploration lives in [RFCs](../rfc/index.md); an RFC is the umbrella, its ADRs are the
individual choices. Operational procedure lives in [runbooks](../runbooks/index.md).
Coverage of the whole estate — which domains have records, which don't — is mapped in the
[decision landscape](landscape.md) (audited 2026-07-02).

## Conventions

- **Location:** `docs/techdocs/docs/adr/adr-NNNN-<kebab-title>.md`, zero-padded, monotonically
  increasing, never reused. Start from the template: [adr-0000-template.md](adr-0000-template.md).
- **Format: [MADR 2.1.2](https://adr.github.io/madr/).** Bare-title `# H1`, then `* Status:` /
  `* Date:` bullets (`Date` = when the decision was **last updated**, per MADR), optional
  `Technical Story:` linking the parent RFC. Sections: Context and Problem Statement →
  (Decision Drivers) → Considered Options (chosen option included) → Decision Outcome
  ("Chosen option: …, because …" + Positive/Negative Consequences) → (Pros and Cons of the
  Options) → Links. Exemplar: [ADR-0001](adr-0001-adopt-harbor.md).
- **ADRs are records, not living docs.** When reality changes (revert, partial rollout,
  supersession), append a dated entry to the ADR's **Links** section and update `Status`/`Date` —
  never silently rewrite the body. A reversed decision gets a *new* ADR that supersedes the old.
- Register every new ADR in the table below (the `adr-writer` skill automates all of this).

## Status legend

| Status | Meaning |
| ------ | ------- |
| **proposed** | Decided to pursue, not yet ratified/implemented end-to-end. |
| **accepted** | Decided. Current source of truth. |
| **rejected** | Considered and declined; kept to prevent re-derivation. |
| **superseded by ADR-NNNN** | Replaced by a later ADR. Never deleted. |
| **deprecated** | No longer relevant, not directly replaced. |

The `Date` column is the decision's **last update** (MADR semantics); the dated history behind
any change lives in that ADR's **Links** section.

## Records

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0001](adr-0001-adopt-harbor.md) | Adopt Harbor as the self-hosted OCI registry | accepted | 2026-06-23 |
| [0002](adr-0002-registry-blob-storage-garage-s3.md) | Registry blob storage on Garage S3 | accepted | 2026-06-12 |
| [0003](adr-0003-external-cnpg-database.md) | External CNPG Postgres for Harbor | accepted | 2026-06-12 |
| [0004](adr-0004-chart-internal-redis.md) | Use Harbor's chart-bundled Redis | accepted | 2026-06-12 |
| [0005](adr-0005-lan-only-exposure.md) | Expose Harbor LAN-only via envoy-internal | accepted | 2026-06-12 |
| [0006](adr-0006-authentik-oidc-phased.md) | Authenticate Harbor via Authentik OIDC, phased | accepted | 2026-06-12 |
| [0007](adr-0007-cilium-wireguard-encryption.md) | Transparent pod-to-pod encryption via Cilium WireGuard | accepted | 2026-06-12 |
| [0008](adr-0008-rootless-ci-image-builds.md) | Rootless CI image builds (drop privileged Docker-in-Docker) | proposed | 2026-07-02 |
| [0009](adr-0009-secret-rotation-model.md) | Secret rotation model — vault write + Reloader | accepted | 2026-07-01 |
| [0010](adr-0010-openbao-dynamic-postgres-credentials.md) | OpenBao database engine for short-lived Postgres credentials | accepted | 2026-07-02 |
| [0011](adr-0011-dual-run-renovate-forgejo.md) | Dual-run Renovate across GitHub and Forgejo | accepted | 2026-07-02 |
| [0012](adr-0012-forgejo-static-bot-pat.md) | Authenticate Renovate to Forgejo with a static bot PAT | accepted | 2026-06-16 |
| [0013](adr-0013-github-as-renovate-data-oracle.md) | Keep GitHub as a read-only data oracle during the cutover | accepted | 2026-07-02 |
| [0014](adr-0014-flux-source-forgejo.md) | Make Forgejo the authoritative GitOps source for Flux | proposed | 2026-07-02 |
| [0015](adr-0015-external-bootstrap-fallback-source.md) | External mirror as cold-bootstrap + break-glass source | proposed | 2026-06-13 |
| [0016](adr-0016-harbor-pull-through-proxy-cache.md) | Harbor pull-through proxy cache for third-party images | accepted | 2026-06-23 |
| [0017](adr-0017-registry-mirror-talos-spegel.md) | Harbor mirror at the Talos/containerd layer, with Spegel | accepted | 2026-06-23 |
| [0018](adr-0018-harbor-config-idempotent-job.md) | Harbor proxy config via an idempotent API CronJob | accepted | 2026-06-23 |
| [0019](adr-0019-bootstrap-task-pattern.md) | Bootstrap / one-shot tasks — pick the lowest trigger tier | accepted | 2026-06-14 |
| [0020](adr-0020-codeberg-offsite-push-mirror.md) | Codeberg as a second off-site push-mirror | proposed | 2026-06-17 |
| [0021](adr-0021-cilium-gateway-egress-for-oidc.md) | Identity-based egress to the gateway for server-side OIDC | accepted (superseded in scope by 0039) | 2026-07-02 |
| [0022](adr-0022-codeberg-pages-techdocs.md) | Serve TechDocs from Codeberg Pages (interim + off-site) | accepted | 2026-06-21 |
| [0023](adr-0023-backstage-techdocs.md) | TechDocs served by Backstage + Garage S3 (target) | proposed | 2026-07-02 |
| [0024](adr-0024-forgejo-leading-application-repos.md) | Forgejo-authoritative application repos (de-mirror) | accepted | 2026-06-26 |
| [0025](adr-0025-node-taxonomy.md) | Capability-based node taxonomy; retire fringe/nodegroup | accepted | 2026-06-21 |
| [0026](adr-0026-confine-longhorn-to-workers.md) | Confine Longhorn storage to the worker nodes | accepted | 2026-06-21 |
| [0027](adr-0027-longhorn-hot-cold-tiers.md) | Longhorn hot/cold storage tiers from node annotations | proposed | 2026-07-01 |
| [0028](adr-0028-application-workload-placement.md) | Pin application workloads to the worker pool (hard) | accepted | 2026-07-02 |
| [0029](adr-0029-storageclass-consolidation.md) | Consolidate Longhorn StorageClasses | proposed | 2026-07-02 |
| [0030](adr-0030-grafana-threshold-rule-shape.md) | Standardize + lint the Grafana threshold alert-rule shape | accepted | 2026-07-02 |
| [0031](adr-0031-meta-monitoring-alert-rule-health.md) | Meta-monitoring of Grafana alert-rule health | accepted | 2026-07-01 |
| [0032](adr-0032-reenable-pyroscope-worker-pool.md) | Re-enable Pyroscope, hard-pinned to the worker pool | accepted | 2026-07-02 |
| [0033](adr-0033-kyverno-enforce-promotion-policy.md) | Gated Kyverno audit→enforce promotion + mandatory tests | accepted | 2026-07-02 |
| [0034](adr-0034-approved-registries-stays-audit.md) | `require-approved-registries` stays Audit | accepted | 2026-07-02 |
| [0035](adr-0035-action-clone-wall.md) | Action-clone wall — measure first; no offline mode exists | accepted | 2026-07-02 |
| [0036](adr-0036-amd64-default-constrictor-build.md) | amd64-by-default builds via the constrictor fast workflow | accepted | 2026-07-02 |
| [0037](adr-0037-storage-engine-gated-on-dedicated-disks.md) | Storage engine stays Longhorn v1; v2/LINSTOR gated on disks | accepted | 2026-07-01 |
| [0038](adr-0038-victoriametrics-metrics-backend.md) | VictoriaMetrics replaces kube-prometheus-stack | accepted | 2026-07-02 |
| [0039](adr-0039-default-deny-network-policies.md) | Opt-in per-namespace default-deny NetworkPolicies | accepted | 2026-07-02 |
