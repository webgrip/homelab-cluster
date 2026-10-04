---
status: accepted
date: 2026-10-04
tags:
  - docs
  - adr
---

# Zensical builds the human docs site, served in-cluster from Garage's web endpoint

Technical Story: [RFC: Docs platform 2026](../rfc/rfc-docs-platform-2026.md). Supersedes
[ADR-0038](adr-0038-codeberg-pages-techdocs.md).

## Context and Problem Statement

The docs stack decided in 2026-06 had two serving legs: Codeberg Pages as the interim/off-site
host ([ADR-0038](adr-0038-codeberg-pages-techdocs.md)) and Backstage TechDocs as the target
([ADR-0039](adr-0039-backstage-techdocs.md)). By 2026-08-09 the publish pipeline finally existed
and was proven (the Garage `techdocs` bucket serves the built artifact), but the Codeberg leg's
§Operations handoff was never done — no pages repo exists, and infrastructure's caller claims the
same `docs` hostname — and Backstage's serving side is blocked on a dormant release path with more
unrelated work behind it. Meanwhile the [docs-platform survey](../rfc/rfc-docs-platform-2026.md)
established that the MkDocs/Material toolchain is EOL 2026-11-05 with **Zensical** as its
`mkdocs.yml`-compatible successor — the same engine Backstage TechDocs upstream proposes adopting.

The owner's constraints (2026-08-09): keep the docs **pluggable into Backstage later** (satisfied
by the ADR-0039 artifact pipeline, which stays), drop Codeberg entirely, and get a human-facing
docs site live now — on Zensical.

## Decision Drivers

* A working human docs surface **now**, without waiting on the Backstage release-path repair.
* Ride the engine succession early: the spike proved Zensical 0.0.53 builds this exact tree
  (166 pages, 1.95 s, mermaid + search native) from the unmodified `mkdocs.yml`.
* Sovereign + in-cluster, LAN-only by default (ADR-0021); no new platform component.
* Keep the agent affordances (llms.txt, per-page raw markdown) and the ~100 legacy redirect URLs
  working — both are Python-plugin outputs Zensical does not produce itself.

## Considered Options

* Zensical-built site in the Garage `docs-site` bucket, served by Garage's web endpoint
* Zensical site served by a dedicated nginx Deployment (preview-host pattern)
* Complete the Codeberg Pages leg (ADR-0038 as designed)
* Wait for Backstage TechDocs (ADR-0039 only, no human site until then)

## Decision Outcome

Chosen option: "Zensical-built site in the Garage `docs-site` bucket, served by Garage's web
endpoint", because it reuses the storage and publish machinery ADR-0039's build-out just proved,
adds zero new workloads, and puts the docs on the engine the whole MkDocs ecosystem — including
Backstage TechDocs upstream — is migrating to.

Mechanics:

* CI (`techdocs-deploy-docs-site.yml` in webgrip/workflows) builds the site with **Zensical**
  from the same `mkdocs.yml`, then grafts from the mkdocs-built `techdocs-site` artifact the
  things Zensical's no-Python-plugins model drops: `llms.txt`/`llms-full.txt`/per-page raw `.md`
  (mkdocs-llms-source) and generated redirect stubs for the `redirect_maps` legacy URLs. One
  `rclone sync` lands it in the `docs-site` bucket.
* Garage gains `[s3_web]` on :3902; the `docs-site` bucket is website-enabled by the
  `garage-techdocs-bootstrap` Job (grants converged on every run).
* An HTTPRoute (`kubernetes/apps/garage/docs-site/`) serves `docs.${SECRET_DOMAIN}` on
  envoy-internal, **rewriting the Host header to the bare bucket alias** `docs-site` so the
  SOPS-guarded domain literal never appears in Garage config or bucket names. LAN-only:
  external-dns is excluded; split DNS (k8s-gateway) resolves it.
* The **ADR-0039 artifact pipeline is untouched**: `techdocs-cli publish` keeps filling the
  `techdocs` bucket, so Backstage TechDocs can be switched on later with zero re-work
  (the "pluggable later" requirement).
* Codeberg Pages is dropped entirely — DNSEndpoint deleted, no docs deploy leg. The off-site DR
  posture for docs reverts to what git already provides (Forgejo + the GitHub/Codeberg git
  mirrors of the repo; the *rendered* site is regenerable from any clone in seconds).

### Consequences

* Good, because the human site is decoupled from both broken external dependencies (Codeberg
  handoff, backstage-application release path) and ships now.
* Good, because the Material→Zensical migration risk named in the survey's watchlist is retired
  early on the low-stakes surface, before the 2026-11-05 EOL forces it.
* Bad, because the rendered site no longer has an off-cluster copy — a full cluster outage takes
  the *rendered* docs down (the sources survive in three git mirrors and rebuild in seconds;
  accepted by the owner in dropping Codeberg).
* Bad, because Zensical is pre-1.0 — pinned at 0.0.53 in the techdocs-builder image, bumped
  deliberately via Renovate, so churn arrives as reviewable PRs.

### Confirmation

From the LAN: `curl -sI https://docs.${SECRET_DOMAIN}/` returns the Zensical site's 200;
`curl -s https://docs.${SECRET_DOMAIN}/adding-applications/` returns the redirect stub to
`/general/adding-applications/`; `curl -s https://docs.${SECRET_DOMAIN}/llms.txt` returns the
agent index. The publish leg is the `deploy-docs-site` job in the `on_docs_change` workflow run
for the triggering commit.

## Pros and Cons of the Options

### Zensical site in the Garage docs-site bucket via Garage web

* Good, because storage, keys, netpols and CI secrets already exist from the ADR-0039 build-out —
  the delta is one config block, one bucket, one HTTPRoute, one CI job.
* Good, because Garage's web endpoint is purpose-built for serving website buckets; no new pod.
* Neutral, because Garage web serves anonymously — acceptable for LAN-only docs behind
  envoy-internal; revisit if docs ever need auth (that is ADR-0039's Backstage lane).

### Zensical site behind a dedicated nginx Deployment

* Good, because full control of headers/caching.
* Bad, because a new always-on workload plus image lifecycle for something Garage already does.

### Complete the Codeberg Pages leg

* Bad, because the owner dropped Codeberg (2026-08-09); also the domain claim collides with
  infrastructure's caller and the manual repo handoff has sat undone since June.

### Wait for Backstage TechDocs only

* Bad, because serving is blocked on the backstage-application release path (broken GitHub
  push-mirror, Forgejo Actions never enabled-and-run) and the owner explicitly deferred that
  workstream; no human docs surface in the meantime.

## More Information

* Technical story: [RFC: Docs platform 2026](../rfc/rfc-docs-platform-2026.md) — the 2026-08-09
  landscape survey that reaffirmed the TechDocs artifact bet and put Zensical on the watchlist;
  this ADR pulls the Zensical trigger early for the human surface at the owner's direction.
* Supersedes [ADR-0038](adr-0038-codeberg-pages-techdocs.md) (Codeberg Pages interim + DR —
  dropped without ever serving; the publish workflow existed for two hours).
* Coexists with [ADR-0039](adr-0039-backstage-techdocs.md): the `techdocs` bucket artifact
  pipeline this site's graft step feeds on is ADR-0039's, and stays its Backstage on-ramp.
* 2026-08-09 — accepted; Garage web endpoint + `docs-site` bucket + HTTPRoute landed
  (homelab-cluster e9cd2ae1), deploy reusable landed (webgrip/workflows 5a7edb1),
  zensical+rclone baked into techdocs-builder (webgrip/infrastructure f8f5b6d).
* 2026-08-11 — **estate rollout executed** ([plan](../rfc/plan-docs-estate-rollout.md), all
  phases): 11 more repos publish under path prefixes — infrastructure, telemetry-service,
  ledgerflow, monitoring-platform (default branch `master`), searxng-application, workflows,
  action-typescript-template, application-template, freshrss-application,
  invoiceninja-application, backstage-application (bootstrapped from a 0-byte mkdocs.yml).
  Pipeline hardening landed en route: gitleaks publish gate (techdocs-builder 1.5.0,
  mutation-tested), `--strict` link validation on the flagship, prefix-scoped sync, and two
  reusable fixes found by per-repo verification (tag-tolerant YAML in the redirect-stub graft;
  stubs escaping their prefix to the domain root). GitHub-side docs workflows retired in six
  repos. Excluded with reason: twente.dev (empty repo on Forgejo), ploeg (no docs tree),
  erfbeeld (not on this Forgejo).
* 2026-08-11 — **estate wipe incident, same day**: every homelab docs publish erased all other
  prefixes — the root (empty-prefix) `rclone sync`'s deletion scope is the whole bucket; the
  "prefix-scoped, repos cannot clobber each other" claim held only for *prefixed* syncs. Caught
  by a user-reported bare-URL 404 that verification had misread as a redirect gap (the earlier
  200s were pre-wipe reads). Fixed in the reusable (workflows fd6771a): the root sync now
  dynamically excludes every top-level remote directory absent from its source tree, logged per
  run; all 11 prefixes re-published. Trade-off accepted: a top-level dir REMOVED from homelab's
  docs stays in the bucket until cleaned manually (stale beats wiped).

* 2026-08-12 — **bucket-per-repo isolation** (estate item #2): every docs repo now publishes
  with its own Garage key into its own `docs-<repo>` + `docs-<repo>-trash` bucket pair — the
  key has rw on exactly that pair, so the estate-wipe class is structurally impossible, not
  just excluded-by-flag. Keys flow bootstrap Job → OpenBao → repo-level `TECHDOCS_S3_*`
  Actions secrets (shadowing the org pair; a precedence regression 403s loudly because the org
  key is read-only on repo buckets). The docs HTTPRoute maps each `/<repo>` prefix to its
  bucket via hostname rewrite + prefix strip; the root rule stays homelab's `docs-site`
  (which also carries `/offline`). The old prefix copies inside `docs-site` are dead weight —
  unreachable and excluded from the offline bundle — and can be purged at leisure.
* 2026-10-04 — correction: the Codeberg git mirror named here as an off-site leg was never built ([ADR-0014](adr-0014-codeberg-offsite-push-mirror.md) rejected); sources rest on Forgejo plus the GitHub push-mirror (logged in audit 2026-10-04)
