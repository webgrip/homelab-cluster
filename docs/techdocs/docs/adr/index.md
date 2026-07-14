# Architecture Decision Records

One defensible decision per record — the durable answer to *"why is it built this way?"*.
Design exploration lives in [RFCs](../rfc/index.md); an RFC is the umbrella, its ADRs are the
individual choices. Operational procedure lives in [runbooks](../runbooks/index.md).
Coverage of the whole estate — which domains have records, which don't — is mapped in the
[decision landscape](landscape.md) (audited 2026-07-02).

## Conventions

- **Location:** `docs/techdocs/docs/adr/adr-NNNN-<kebab-title>.md`, zero-padded, monotonically
  increasing, never reused. Start from the template: [adr-0000-template.md](adr-0000-template.md).
- **Format: [MADR 4.0.0](https://adr.github.io/madr/)** (new records since 2026-07-12).
  `status` / `date` live in YAML frontmatter (`date` = when the decision was **last updated**,
  per MADR; MkDocs does not render frontmatter, so status is also visible in the table below and
  in the record's dated history). Bare-title `# H1`, then: Context and Problem Statement →
  (Decision Drivers) → Considered Options (chosen option first) → Decision Outcome
  ("Chosen option: …, because …" + Consequences as `Good/Bad, because` bullets + Confirmation:
  the concrete check that proves compliance) → (Pros and Cons of the Options) → More
  Information (parent RFC as `Technical story:`, dated history, cross-ADR relations).
  Exemplar: [ADR-0017](adr-0017-adopt-harbor.md).
- **Records keep their birth format.** ADRs written before 2026-07-12 are MADR 2.1.2
  (`* Status:`/`* Date:` bullets, Positive/Negative Consequences, `## Links`) and are **not**
  retro-migrated — amendments append in the record's own format. Sole exception: ADR-0017 was
  restructured to 4.0.0 (format-only) to serve as the exemplar.
- **ADRs are records, not living docs.** When reality changes (revert, partial rollout,
  supersession), append a dated entry to the ADR's **More Information** section (`## Links` in
  2.1.2-era records) and update `status`/`date` — never silently rewrite the body. A reversed
  decision gets a *new* ADR that supersedes the old.
- **Ordering (re-baselined 2026-07-03):** 0001–0039 read bottom-up through the stack — nodes
  first, then network, storage, delivery, and so on up to docs — so reading the set in order
  tells the story of the platform. This was a **one-time renumbering** (mapping
  [below](#renumbering-2026-07-03)); from here on, a new ADR simply takes the next free number
  and its layer is expressed by the section it joins in the table below, not by its number.
- **Register every new ADR** in the table below AND in `docs/techdocs/mkdocs.yml` nav (numeric
  slot). Verify with `./scripts/check-docs-links.sh` and
  `python3 scripts/validate_adr_consistency.py .` — both run in e2e CI, which enforces file ↔
  table consistency (status, date, sections). The `adr-writer` plugin skill
  (webgrip-ai-skills) automates all of this and defers to these conventions.
- **Dates come from git** — `git log --follow --oneline -- <file>` or the triggering commit,
  never from memory. If no ratification commit exists, log
  `status corrected in audit YYYY-MM-DD` in the history; don't backdate acceptance. (Repo
  markdownlint MD060: table delimiter rows need spaced pipes, `| --- |`.)

## Status legend

| Status | Meaning |
| ------ | ------- |
| **proposed** | Decided to pursue, not yet ratified/implemented end-to-end. |
| **accepted** | Decided. Current source of truth. |
| **rejected** | Considered and declined; kept to prevent re-derivation. |
| **superseded by ADR-NNNN** | Replaced by a later ADR. Never deleted. |
| **deprecated** | No longer relevant, not directly replaced. |

The `Date` column is the decision's **last update** (MADR semantics); the dated history behind
any change lives in that ADR's **More Information** section (`## Links` in 2.1.2-era records).

## Records

### 1. Foundation — nodes & platform patterns

What the cluster runs on, and the cross-cutting patterns everything above assumes.

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0001](adr-0001-node-taxonomy.md) | Capability-based node taxonomy; retire fringe/nodegroup | accepted | 2026-06-21 |
| [0002](adr-0002-application-workload-placement.md) | Pin application workloads to the worker pool (hard) | accepted | 2026-07-02 |
| [0003](adr-0003-bootstrap-task-pattern.md) | Bootstrap / one-shot tasks — pick the lowest trigger tier | accepted | 2026-06-14 |

### 2. Network & zero trust

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0004](adr-0004-cilium-wireguard-encryption.md) | Transparent pod-to-pod encryption via Cilium WireGuard | accepted | 2026-06-12 |
| [0005](adr-0005-cilium-gateway-egress-for-oidc.md) | Identity-based egress to the gateway for server-side OIDC | accepted (superseded in scope by 0006) | 2026-07-02 |
| [0006](adr-0006-default-deny-network-policies.md) | Opt-in per-namespace default-deny NetworkPolicies | accepted | 2026-07-02 |

### 3. Storage

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0007](adr-0007-storage-engine-gated-on-dedicated-disks.md) | Storage engine stays Longhorn v1; v2/LINSTOR gated on disks | accepted | 2026-07-01 |
| [0008](adr-0008-confine-longhorn-to-workers.md) | Confine Longhorn storage to the worker nodes | accepted | 2026-06-21 |
| [0009](adr-0009-longhorn-hot-cold-tiers.md) | Longhorn hot/cold storage tiers from node annotations | proposed | 2026-07-01 |
| [0010](adr-0010-storageclass-consolidation.md) | Consolidate Longhorn StorageClasses | proposed | 2026-07-02 |

### 4. GitOps source & delivery

How change reaches the cluster — the forge, the Flux source, and the escape hatches.

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0011](adr-0011-flux-source-forgejo.md) | Make Forgejo the authoritative GitOps source for Flux | accepted | 2026-07-14 |
| [0012](adr-0012-external-bootstrap-fallback-source.md) | External mirror as cold-bootstrap + break-glass source | accepted | 2026-07-14 |
| [0013](adr-0013-forgejo-leading-application-repos.md) | Forgejo-authoritative application repos (de-mirror) | accepted | 2026-06-26 |
| [0014](adr-0014-codeberg-offsite-push-mirror.md) | Codeberg as a second off-site push-mirror | proposed | 2026-06-17 |

### 5. Secrets

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0015](adr-0015-secret-rotation-model.md) | Secret rotation model — vault write + Reloader | accepted | 2026-07-01 |
| [0016](adr-0016-openbao-dynamic-postgres-credentials.md) | OpenBao database engine for short-lived Postgres credentials | accepted | 2026-07-02 |

### 6. Registry & artifacts

The Harbor family — adoption, backing services, exposure, SSO — then the caching tier.

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0017](adr-0017-adopt-harbor.md) | Adopt Harbor as the self-hosted OCI registry | accepted | 2026-06-23 |
| [0018](adr-0018-registry-blob-storage-garage-s3.md) | Registry blob storage on Garage S3 | accepted | 2026-06-12 |
| [0019](adr-0019-external-cnpg-database.md) | External CNPG Postgres for Harbor | accepted | 2026-06-12 |
| [0020](adr-0020-chart-internal-redis.md) | Use Harbor's chart-bundled Redis | accepted | 2026-06-12 |
| [0021](adr-0021-lan-only-exposure.md) | Expose Harbor LAN-only via envoy-internal | accepted | 2026-06-12 |
| [0022](adr-0022-authentik-oidc-phased.md) | Authenticate Harbor via Authentik OIDC, phased | accepted | 2026-06-12 |
| [0023](adr-0023-harbor-pull-through-proxy-cache.md) | Harbor pull-through proxy cache for third-party images | accepted | 2026-06-23 |
| [0024](adr-0024-registry-mirror-talos-spegel.md) | Harbor mirror at the Talos/containerd layer, with Spegel | accepted | 2026-06-23 |
| [0025](adr-0025-harbor-config-idempotent-job.md) | Harbor proxy config via an idempotent API CronJob | accepted | 2026-06-23 |

### 7. CI & dependency automation

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0026](adr-0026-rootless-ci-image-builds.md) | Rootless CI image builds (drop privileged Docker-in-Docker) | proposed | 2026-07-02 |
| [0027](adr-0027-amd64-default-constrictor-build.md) | amd64-by-default builds via the constrictor fast workflow | accepted | 2026-07-02 |
| [0028](adr-0028-action-clone-wall.md) | Action-clone wall — measure first; no offline mode exists | accepted | 2026-07-02 |
| [0029](adr-0029-dual-run-renovate-forgejo.md) | Dual-run Renovate across GitHub and Forgejo | accepted | 2026-07-02 |
| [0030](adr-0030-forgejo-static-bot-pat.md) | Authenticate Renovate to Forgejo with a static bot PAT | accepted | 2026-06-16 |
| [0031](adr-0031-github-as-renovate-data-oracle.md) | Keep GitHub as a read-only data oracle during the cutover | accepted | 2026-07-02 |

### 8. Policy & admission

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0032](adr-0032-kyverno-enforce-promotion-policy.md) | Gated Kyverno audit→enforce promotion + mandatory tests | accepted | 2026-07-02 |
| [0033](adr-0033-approved-registries-stays-audit.md) | `require-approved-registries` stays Audit | accepted | 2026-07-02 |

### 9. Observability

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0034](adr-0034-victoriametrics-metrics-backend.md) | VictoriaMetrics replaces kube-prometheus-stack | accepted | 2026-07-02 |
| [0035](adr-0035-grafana-threshold-rule-shape.md) | Standardize + lint the Grafana threshold alert-rule shape | accepted | 2026-07-02 |
| [0036](adr-0036-meta-monitoring-alert-rule-health.md) | Meta-monitoring of Grafana alert-rule health | accepted | 2026-07-01 |
| [0037](adr-0037-reenable-pyroscope-worker-pool.md) | Re-enable Pyroscope, hard-pinned to the worker pool | accepted | 2026-07-02 |
| [0041](adr-0041-victorialogs-logging-backend.md) | VictoriaLogs replaces Loki as the logging backend | accepted | 2026-07-10 |
| [0042](adr-0042-victoriatraces-tracing-backend.md) | VictoriaTraces replaces Tempo as the tracing backend | accepted | 2026-07-12 |

### 10. Docs & developer portal

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0038](adr-0038-codeberg-pages-techdocs.md) | Serve TechDocs from Codeberg Pages (interim + off-site) | accepted | 2026-06-21 |
| [0039](adr-0039-backstage-techdocs.md) | TechDocs served by Backstage + Garage S3 (target) | proposed | 2026-07-02 |

### 11. Applications

Tenant apps the platform hosts — decisions about *what* runs, not how the platform works.

| ADR | Decision | Status | Last updated |
| --- | -------- | ------ | ------------ |
| [0040](adr-0040-vikunja-task-management.md) | Vikunja as the task-management system, complementing Forgejo issues | proposed | 2026-07-09 |
| [0043](adr-0043-vikunja-roadmap-system-of-record.md) | Vikunja board is the roadmap system of record; roadmap.md retired | accepted | 2026-07-12 |
| [0044](adr-0044-metered-inference-plane-litellm.md) | All inference is metered through a self-hosted LiteLLM proxy | proposed | 2026-07-14 |
| [0045](adr-0045-opencode-runtime-server-side-guards.md) | opencode is the agent runtime; safety guards move server-side | proposed | 2026-07-14 |

## Renumbering (2026-07-03)

The set was renumbered **once** so it reads bottom-up through the stack. Slugs never changed —
only the number prefix — and mkdocs redirects cover every old URL. Anything written before
2026-07-03 (commit messages, PR threads, external links) uses **old** numbers; translate with
this table. Each ADR also carries a dated `renumbered from` entry in its own Links section.

| Old | New | Old | New | Old | New |
| --- | --- | --- | --- | --- | --- |
| 0001 | 0017 | 0014 | 0011 | 0027 | 0009 |
| 0002 | 0018 | 0015 | 0012 | 0028 | 0002 |
| 0003 | 0019 | 0016 | 0023 | 0029 | 0010 |
| 0004 | 0020 | 0017 | 0024 | 0030 | 0035 |
| 0005 | 0021 | 0018 | 0025 | 0031 | 0036 |
| 0006 | 0022 | 0019 | 0003 | 0032 | 0037 |
| 0007 | 0004 | 0020 | 0014 | 0033 | 0032 |
| 0008 | 0026 | 0021 | 0005 | 0034 | 0033 |
| 0009 | 0015 | 0022 | 0038 | 0035 | 0028 |
| 0010 | 0016 | 0023 | 0039 | 0036 | 0027 |
| 0011 | 0029 | 0024 | 0013 | 0037 | 0007 |
| 0012 | 0030 | 0025 | 0001 | 0038 | 0034 |
| 0013 | 0031 | 0026 | 0008 | 0039 | 0006 |
