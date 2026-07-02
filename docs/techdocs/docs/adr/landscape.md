# Decision landscape — coverage map & gap register

> Point-in-time audit, **2026-07-02**. Maps every decision domain to its RFCs/ADRs, then registers
> the gaps — load-bearing architecture running in production with **no decision record**. Each gap
> has a Proposed RFC (linked below); as those RFCs spawn ADRs, refresh this map rather than letting
> it rot silently.

## How to read this

The ADR practice started **2026-06-12** (ADR-0001). Everything decided *after* that date is well
covered — the Harbor family, the forge exit, node taxonomy, Kyverno promotion, VictoriaMetrics.
Everything decided *before* it — Talos, Flux, Cilium, the ingress edge, Authentik, CNPG, Garage —
exists only as running configuration: the decisions are real, load-bearing, and unrecorded.
[ADR-0039](adr-0039-default-deny-network-policies.md) set the precedent for recording such
decisions retroactively; the gap RFCs below extend that to the rest of the foundation.

## Covered domains (RFC → ADRs)

| Domain | RFC(s) | ADRs | State |
| --- | --- | --- | --- |
| Registry & artifacts | [Harbor registry](../rfc/rfc-harbor-registry.md) · [proxy cache](../rfc/rfc-harbor-proxy-cache.md) | 0001–0006, 0016–0018 | Implemented |
| Security hardening (program) | [Security hardening](../rfc/rfc-security-hardening.md) | 0007, 0008 (Proposed), 0009, 0039 | Executing |
| Secrets | [external-secrets plan](../rfc/external-secrets-plan.md) · [dynamic DB creds](../rfc/rfc-dynamic-database-credentials.md) | 0009, 0010 | Plan done; pilot paused |
| Forge exit — Renovate | [Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md) | 0011–0013 | Dual-run, retirement gated |
| Forge exit — GitOps source | [Flux → Forgejo](../rfc/rfc-flux-forgejo-source.md) | 0014, 0015, 0020 (all Proposed) | The big open cutover |
| Forge exit — repos & CI | [CI pipeline performance](../rfc/rfc-ci-pipeline-performance.md) | 0024, 0035, 0036 | Executing |
| TechDocs hosting | [Codeberg Pages](../rfc/rfc-codeberg-pages-techdocs.md) · [Backstage](../rfc/rfc-backstage-techdocs.md) | 0022, 0023 (Proposed) | Interim live; target unbuilt |
| Nodes & storage placement | [Node taxonomy](../rfc/rfc-node-taxonomy-and-storage-placement.md) | 0025–0029 | Implemented (0027/0029 tails open) |
| Hardware evolution (program) | [Layered hardware](../rfc/rfc-layered-hardware-architecture.md) | 0037 | Path not yet chosen |
| Alerting reliability | [Observability alerting](../rfc/rfc-observability-alerting-reliability.md) | 0030, 0031 | Implemented (delivery excluded — see gaps) |
| Policy / admission | [Kyverno audit→enforce](../rfc/rfc-kyverno-audit-enforce-hardening.md) | 0033, 0034 | Waves ongoing |
| Metrics backend | — (standalone) | 0038 | Implemented |
| Platform conventions | — (standalone) | 0019, 0021 (superseded), 0032 | Accepted |

## Gap register (each gap → a Proposed RFC)

Ordered by how much is silently at stake, not by effort.

| # | Gap | Evidence (verified 2026-07-02) | RFC |
| --- | --- | --- | --- |
| 1 | **No alert reaches a human.** Both alerting planes end in the void: VMAlertmanager's only receiver is `"null"`; Grafana has zero contact points. | `victoria-metrics/app/vmalertmanager.yaml` (receiver `"null"`, "no paging wired up yet"); no `GrafanaContactPoint` anywhere | [Alert delivery](../rfc/rfc-alert-delivery.md) |
| 2 | **Backup & DR has never been decided as a program.** Every backup lands on one Garage host; the OpenBao unseal key lives only in-cluster; metrics/logs/traces have no (decided) durability. | [openbao-restore runbook](../runbooks/openbao-restore.md) ("not a complete DR story"); ADR-0038 ("no vmbackup") | [Backup & DR](../rfc/rfc-backup-dr.md) |
| 3 | **Garage is the S3 backbone of everything and has no record.** 10 CNPG ObjectStores, Longhorn backups, Loki, Tempo, Harbor blobs, Forgejo LFS, GUAC, OpenBao snapshots — all on one off-cluster host outside GitOps. | grep `10.0.0.110` across `kubernetes/` | [Object storage](../rfc/rfc-object-storage-garage.md) |
| 4 | **Runtime detection is uninstalled.** Falco *and* Tetragon both disabled 2026-06-19 after cluster outages; no decision on reinstate/pick-one/respond. | `kubernetes/apps/security/kustomization.yaml` (commented out) | [Runtime detection & response](../rfc/rfc-runtime-detection-response.md) |
| 5 | **The platform foundations predate the ADR era.** Talos, Flux topology, Cilium datapath (kube-proxy replacement, DSR, L2/LB-IPAM) — all unrecorded. | `talos/`, `kubernetes/flux/cluster/ks.yaml`, `kube-system/cilium/app/helmrelease.yaml` | [Platform foundations](../rfc/rfc-platform-foundations.md) |
| 6 | **The ingress/DNS edge is unrecorded.** Dual Envoy gateways, Cloudflare tunnel, split-horizon DNS, single wildcard cert, the internal-by-default convention (enforced by nothing). | `network/envoy-gateway/app/envoy.yaml`, `cloudflare-tunnel`, `k8s-gateway` | [Ingress, DNS & edge](../rfc/rfc-ingress-dns-edge.md) |
| 7 | **Identity architecture is unrecorded and SSO coverage is partial.** Authentik itself has no adoption ADR; integration is OIDC-only (5 apps) — no outposts/forward-auth, so non-OIDC UIs (Longhorn, searxng, flux-ui, …) sit on the LAN with no auth. | `authentik/app/blueprints/` (8 files); zero outpost/forward-auth hits repo-wide | [Identity & SSO](../rfc/rfc-identity-sso.md) |
| 8 | **CNPG is "the cluster standard" that no record established.** All 11 databases are single-instance by unstated policy; guac silently deviates from the backup pattern; pooling is unresolved after the freshrss pause. | 11 `Cluster` CRs, all `instances: 1`; guac = pg_dump only | [Postgres data layer](../rfc/rfc-postgres-data-layer.md) |
| 9 | **The logs/traces/profiles pipeline is unrecorded.** Loki, Tempo, the two-Alloy collector topology, Beyla, retention tiers (30d/14d), single-replica-everything — only metrics (ADR-0038) has a record. | `observability/loki`, `tempo`, `alloy-*`, `beyla` | [Observability pipeline](../rfc/rfc-observability-pipeline.md) |
| 10 | **Image signing was re-anchored to OpenBao Transit and nobody wrote it down.** The security-hardening RFC still describes a GitHub-OIDC→Authentik re-anchor that reality has bypassed; verify policies are Audit with no owned enforce path; DT and GUAC both ingest the same SBOMs. | `openbao/bootstrap/init.sh` (transit key), `cosign-pubkey/`, 3 audit verify policies | [Image signing & verification](../rfc/rfc-image-signing-verification.md) |
| 11 | **ARC is at 0/0 with "TEMP" in a comment since 2026-06-18.** GitHub Actions self-hosted capacity is de facto retired; no decision says whether it returns or when it's deleted. | `arc-systems/gha-runner-scale-set*/helmrelease.yaml` (`minRunners: 0, maxRunners: 0`) | [GitHub Actions retirement](../rfc/rfc-github-actions-retirement.md) |

## Minor gaps — acknowledged, deliberately not RFC'd

One-line rationale each; promote to an RFC only if one starts hurting:

- **KEDA** — adopted as the forgejo-runner scaler; instrumental to ADR-0008, no independent decision surface.
- **Reloader / metrics-server / spegel** — single-purpose utilities; spegel is covered by ADR-0017, Reloader by ADR-0009.
- **Backstage as the portal** — the [engineering-experience program doc](../general/engineering-experience-program.md) covers intent; the TechDocs half has RFCs. Record an adoption ADR if the catalog becomes load-bearing.
- **Upgrade cadence (Talos/k8s/charts)** — Renovate + runbooks carry the practice; a cadence policy ADR is a nice-to-have.
- **Capacity & cost governance** — OpenCost/Kepler observe; no governance decisions exist yet to record.
- **App-level additions** (freshrss, sparkyfitness, drawio, games, …) — covered by the add-app pattern; ADRs are for architecture, not app inventory.
