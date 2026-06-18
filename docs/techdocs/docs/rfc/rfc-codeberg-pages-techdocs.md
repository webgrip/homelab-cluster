# RFC: TechDocs hosting after GitHub Pages

> Status: **Accepted** (interim) · Date: 2026-06-18 · Owner: Ryan Grippeling (`ryan@webgrip.nl`)
> · Decisions: [ADR-0022 (Codeberg Pages, now)](../adr/adr-0022-codeberg-pages-techdocs.md) ·
> [ADR-0023 (Backstage TechDocs, target)](../adr/adr-0023-backstage-techdocs.md)
> · Companion: [Bringing the Forge Home](../blogs/2026-06-12-bringing-the-forge-home.md)

## 1. Problem

TechDocs is built by CI (`techdocs-cli generate` → a static `techdocs-site`) and was published to
**GitHub Pages**. Leaving GitHub removes that target and **Forgejo has no native Pages**. The
current `.forgejo` deploy step pushes the site to a `pages` branch that nothing serves, so docs are
effectively unpublished on the new platform. We need a serving target now, and a durable in-cluster
home eventually.

## 2. Requirements

| # | Requirement | Weight |
|---|---|---|
| R1 | A working, served docs site reachable at a stable URL (`docs.webgrip.dev`) | must |
| R2 | Survives a cluster outage (DR) | strong (interim), must (long-term mirror) |
| R3 | Low effort to stand up *now* | strong (interim) |
| R4 | Path to the real TechDocs experience — search, catalog links, SSO for private docs | must (target) |
| R5 | GitOps / reproducible; secrets from OpenBao | must |
| R6 | Sovereign (self-hosted) where it matters | medium |

No single option maximizes all of these, so we **phase** it.

## 3. Options surveyed

1. **Garage S3 static website** — sync the site into a Garage bucket; Garage's `s3_web` endpoint
   serves it behind Envoy + cert-manager. Sovereign, simple, GitOps. In-cluster only (fails R2);
   private access needs an Envoy authz hop.
2. **Backstage TechDocs (external storage)** — `techdocs-cli publish` to a Garage S3 bucket;
   Backstage (already deployed) serves it with search, catalog entity-linking, and Authentik SSO.
   The architecturally-correct home (R4). In-cluster only (fails R2 alone); larger change.
3. **Signed OCI image in Harbor + Flux** — bake the site into an image, push to Harbor,
   cosign-sign, serve via a Flux Deployment, Kyverno-verify. Most cohesive with the supply-chain
   work; immutable + rollbackable. Image build per change; in-cluster only.
4. **Codeberg Pages** — push the site to a Codeberg repo's `pages` branch; Codeberg serves it.
   Off-site (R2), zero in-cluster infra (R3), matches [ADR-0020](../adr/adr-0020-codeberg-offsite-push-mirror.md).
   Public-only; external dependency.
5. **Self-hosted Forgejo Pages server** (`pages-server` / `git-pages` / `forgejo-pages`) — serve
   the `pages` branch in-cluster; general-purpose for all repos; no CI change. Another service to
   operate; in-cluster only.

## 4. Decision: phase it — Codeberg now, Backstage later

- **Now → Option 4, Codeberg Pages** ([ADR-0022](../adr/adr-0022-codeberg-pages-techdocs.md)). It uniquely
  satisfies R2 (off-site DR) with the least effort (R3) and no in-cluster footprint, and it is the
  documentation companion to the off-site Git mirror already chosen in ADR-0020. Accepts public-only
  (R4 deferred).
- **Later → Option 2, Backstage TechDocs** ([ADR-0023](../adr/adr-0023-backstage-techdocs.md)) as the
  primary in-cluster surface (R4: search, catalog, SSO). At that point **Codeberg is retained as the
  off-site DR mirror**, so R2 still holds.

Options 1/3/5 remain viable in-cluster primaries if Backstage proves the wrong surface; they are
recorded but not chosen.

## 5. Design (Codeberg Pages)

```
on_docs_change.yml (Forgejo)
  ├─ generate-documentation  → webgrip/workflows/.forgejo/workflows/techdocs-generate.yml
  │                            (techdocs-cli generate → artifact `techdocs-site`)
  └─ deploy-documentation    → webgrip/workflows/.forgejo/workflows/techdocs-deploy-codeberg.yml
                               (download artifact → orphan `pages` branch + `.domains` →
                                force-push to codeberg.org/<owner>/<repo>)
```

- **Snapshot push.** Each deploy builds an orphan `pages` branch from the artifact and force-pushes
  it, so the published branch is always a clean snapshot (no history bloat).
- **Custom domain.** A `.domains` file in the branch carries `docs.webgrip.dev`; Codeberg issues the
  TLS cert. DNS: `docs.webgrip.dev CNAME webgrip.codeberg.page`.
- **Auth.** `git push https://<bot>:${CODEBERG_TOKEN}@codeberg.org/<owner>/<repo>.git`. The token is
  a scoped Codeberg PAT (`write:repository`) provisioned as a Forgejo org Actions secret
  (`CODEBERG_TOKEN`) by the `forgejo-actions-secrets` CronJob from OpenBao `codeberg/pages`.
- **Runs on** the in-cluster `docker` runner in the `webgrip/techdocs-runner` container (git added at
  runtime), same as the old gh-pages deploy.

## 6. Operations / one-time prerequisites (handoff)

These are deliberately **not** GitOps (external account + DNS + a root-seeded secret):

1. **Codeberg repo** — create `codeberg.org/webgrip/<docs-repo>` (a dedicated published-site repo, or
   reuse the infrastructure mirror). The `pages` branch is what gets served.
2. **Codeberg token** — mint a PAT (scope `write:repository`) for the publishing bot; store it in
   OpenBao at `codeberg/pages` (property `token`). The ExternalSecret + CronJob publish it as the
   org Actions secret `CODEBERG_TOKEN`.
3. **DNS** — `docs.webgrip.dev CNAME webgrip.codeberg.page.` (+ any Codeberg domain-verification
   record they require).

## 7. Risks & mitigations

- **External availability** — Codeberg outage = docs down. Mitigated long-term by Backstage as the
  in-cluster primary (ADR-0023), with Codeberg demoted to mirror.
- **Public exposure** — never publish access-controlled docs to Codeberg; gate those behind
  Backstage + Authentik (ADR-0023).
- **Token leakage** — scoped PAT, masked in logs, rotated via the standard OpenBao path; never
  echoed (push URL is constructed inline, not printed).

## 8. Migration to the target

When [ADR-0023](../adr/adr-0023-backstage-techdocs.md) lands, `on_docs_change` gains a Backstage-publish
job (S3) as the **primary**; the Codeberg deploy stays as a second job (off-site DR). No re-build —
both consume the same `techdocs-site` artifact.
