# RFCs & design docs

Broad designs and programs; each spawns [ADRs](../adr/index.md) for its individual decisions.
Statuses: Proposed (open) · Accepted (decided, executing) · Implemented (done) · Withdrawn.

- **Implemented** — [Harbor registry](rfc-harbor-registry.md), [Harbor proxy
  cache](rfc-harbor-proxy-cache.md), [node taxonomy & storage
  placement](rfc-node-taxonomy-and-storage-placement.md), [observability alerting
  reliability](rfc-observability-alerting-reliability.md), [external-secrets migration
  plan](external-secrets-plan.md) (complete; canonical secret inventory), [Flux source →
  Forgejo](rfc-flux-forgejo-source.md) (Accepted 2026-07-14 and executed — the RFC itself has said
  so since; this index was still listing it as the open "big cutover" as late as 2026-08-05.
  Verified live: flux-system's GitRepository is
  `http://forgejo-http.forgejo.svc.cluster.local:3000/webgrip/homelab-cluster.git`).
- **Accepted, executing** — [Renovate on Forgejo](rfc-renovate-forgejo.md) (GitHub retirement
  gated on the Flux cutover), [CI pipeline performance](rfc-ci-pipeline-performance.md) (lives in
  `webgrip/workflows`), [Codeberg Pages TechDocs](rfc-codeberg-pages-techdocs.md) (interim;
  publish path unproven), [security hardening](rfc-security-hardening.md) (program frame),
  [Kyverno audit→enforce hardening](rfc-kyverno-audit-enforce-hardening.md) (waves pending).
- **Proposed / open** — [Forgejo repo config as GitOps](rfc-forgejo-repo-config-gitops.md)
  (2026-09-28 draft: repo settings and branch protection move from `forgejo-sync.sh` to a git
  profile model applied by tofu-controller; git selects profiles, topics are a projection),
  [CI isolation on Talos](rfc-ci-isolation-talos.md)
  (2026-08-11 incident-driven: shared privileged dind is unsupported on Talos per Sidero;
  containment wrapper shipped, staged plan → Talos v1.13.8, cilium OOM-exemption, kata for
  KinD e2e, rootless end-state gated on moby#52268),
  [dynamic database credentials](rfc-dynamic-database-credentials.md)
  (pilot rolled back),
  [Backstage TechDocs](rfc-backstage-techdocs.md) (+ [implementation
  plan](plan-backstage-techdocs.md)), [docs estate rollout plan](plan-docs-estate-rollout.md)
  (2026-08-11: every repo's docs onto docs.\${SECRET_DOMAIN} path-per-repo — inventory, security
  posture, Zensical adoption), [docs platform 2026](rfc-docs-platform-2026.md) (2026-08-09
  landscape survey: Material-for-MkDocs EOL 2026-11-05, Zensical succession via Backstage RFC
  #33990, agent-era llms.txt affordances — verdict: keep ADR-0039, build it now), [layered hardware
  architecture](rfc-layered-hardware-architecture.md) (program doc),
  [task management](rfc-task-management.md) (top-20 field survey → Vikunja, ADR-0040),
  [Proxmox evacuation & offsite storage](rfc-proxmox-evacuation-offsite-storage.md) (object storage
  goes offsite, Immich/deadman to a cloud VM, reclaim the host as a Talos worker).

## Security-audit RFCs (2026-08-04)

Spawned by the [full-estate Kyverno audit](rfc-kyverno-audit-enforce-hardening.md#audit-2026-08-04)
— problems larger than a single enforcement wave. All **Proposed**, listed by urgency:

- [Policy estate gap analysis](rfc-policy-estate-gap-analysis.md) — **read first**. ~half our 79
  rules reimplement published standards, incompletely: our "PSS Baseline" covers **4 of ~13**
  Baseline controls. Adopt upstream for those; hand-write only what encodes our own decisions.
  Also records the fix that unblocks the CEL migration.
- [Kyverno CEL migration](rfc-kyverno-cel-migration.md) — **dated**. All 25 policies are on the
  legacy `kyverno.io/v1` API, deprecated in 1.17 and targeted for **removal in v1.20, October
  2026**. A routine Renovate chart bump is currently an unguarded trapdoor.
- [Gating the verify policies](rfc-verify-policy-gating.md) — waves 6/13/14 are `verifyImages`, and
  **neither** ADR-0032 gate can evaluate them (near-empty PolicyReports, unsweepable offline).
  Builds the missing evidence source; also records an inverted `failurePolicy` posture.
- [Request authorization at the gateway](rfc-request-authorization-envoy.md) — admission is
  enforce-grade, request authorization is ungoverned; Envoy Gateway's `SecurityPolicy`/`extAuth`
  closes the forward-auth hole named in the [identity RFC](rfc-identity-sso.md).
- [Attack-path analysis](rfc-attack-path-analysis.md) — the 17 waivers are each justified
  individually and have never been evaluated as a *graph*. Read-only, laptop-run, deploys nothing.
- [Third-party image supply chain](rfc-third-party-image-supply-chain.md) — the first-party chain
  covers **7 of 151** images; the other 144 have scan data that gates nothing (117 critical / 2,165
  high) and 114 bypass Harbor entirely. Four phases, routing first.
- [Workload identity (SPIFFE)](rfc-workload-identity-spiffe.md) — gap acknowledged and
  **deliberately deferred**, with named re-evaluation triggers.

## Decision-landscape gap RFCs (2026-07-02)

Spawned by the [decision-landscape audit](../adr/landscape.md): the parts of the running platform
that had no decision record. All **Proposed**. Roughly by stakes:

- [Alert delivery](rfc-alert-delivery.md) — **delivery is solved** (ntfy receivers wired and
  working). Reframed 2026-08-05: the open problem is alert *saturation*, not delivery.
- [Backup & DR program](rfc-backup-dr.md) — tier map, the OpenBao unseal-key escrow hole, second
  backup leg, drill cadence.
- [Object storage — Garage](rfc-object-storage-garage.md) — the unrecorded S3 backbone everything
  depends on.
- [Runtime detection & response](rfc-runtime-detection-response.md) — Falco *and* Tetragon
  uninstalled since 2026-06-19; pick one, gate the return, wire the response.
- [Platform foundations](rfc-platform-foundations.md) — retroactive ADRs for Talos, Flux topology,
  Cilium datapath.
- [Ingress, DNS & edge](rfc-ingress-dns-edge.md) — dual gateways, tunnel, split DNS; enforce the
  internal-by-default posture.
- [Identity & SSO](rfc-identity-sso.md) — Authentik adoption record + the non-OIDC/forward-auth
  hole.
- [kagent or Glide for the in-cluster agent runtime](rfc-agent-runtime-kagent-vs-glide.md) —
  five options against ADR-0063's kagent 1.0 pilot, including kagent embedded in Glide; verdict:
  Glide on agent-sandbox with the existing `kata` RuntimeClass, no embedding; Draft 2026-09-27
- [Glide runs on Omnigraph](spec-glide-omnigraph.md) — implementation spec for the Glide side: per-run LiteLLM keys with the `glide` MCP group, the MCP server handed to each harness through the key-isolation proxy, runs working on `glide/<trace-id>` branches that only Ryan merges; cluster side live 2026-09-28
- [Personal archive](rfc-personal-archive.md) — all mail, calls and chats searchable from the chat: originals in Garage, a CNPG Postgres full-text and `pgvector` index, the brain distilled from personal items only, client content never sent to an external model; Proposed 2026-09-27
- [MCP endpoints carry the caller's identity](rfc-mcp-identity.md) — the six MCP routes behind the broker at the gateway and `k8s-mcp` calling the API as the person; Proposed 2026-09-15
- [The access plane](rfc-access-plane.md) — Google as the only identity, one four-file
  entitlement model, one OpenTofu module reconciled by tofu-controller; supersedes the open
  items above.
- [Postgres data layer](rfc-postgres-data-layer.md) — CNPG-as-standard, the single-instance
  posture, pooling.
- [Observability pipeline](rfc-observability-pipeline.md) — logs/traces/profiles composition,
  retention tiers, Kepler's fate.
- [Image signing & verification](rfc-image-signing-verification.md) — record the OpenBao Transit
  anchor, own the verify-enforce waves, DT-vs-GUAC.
- [GitHub Actions retirement](rfc-github-actions-retirement.md) — ARC has been 0/0 "TEMP" since
  2026-06-18; retire or restore, on purpose.
