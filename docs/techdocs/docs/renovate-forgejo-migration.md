# Renovate → Forgejo migration

> Status: **planned, ready to implement.** This is the **execution checklist** for moving the
> self-hosted Renovate from GitHub to the in-cluster [Forgejo](forgejo.md). The **design,
> rationale, and decisions** live in the umbrella RFC — read that first:
> [RFC: Renovate on Forgejo](architecture/rfc-renovate-forgejo.md) ·
> [ADR-0011 (dual-run)](architecture/adr-0011-dual-run-renovate-forgejo.md) ·
> [ADR-0012 (static bot PAT)](architecture/adr-0012-forgejo-static-bot-pat.md) ·
> [ADR-0013 (GitHub as data oracle)](architecture/adr-0013-github-as-renovate-data-oracle.md).
> How Renovate runs today is in [Renovate](renovate.md). Part of the
> [forge migration](blog/2026-06-12-bringing-the-forge-home.md).

## The one thing to keep in your head

Renovate's Forgejo autodiscover **skips mirror repos**, and you can't push branches to a pull-mirror
anyway. `gitea-mirror` runs continuous **inbound** sync (GitHub → Forgejo), so a `webgrip/*` repo in
Forgejo is a read-only mirror **until you turn that mirror off**. Therefore the gate for every repo
is: **"is this repo Forgejo-authoritative yet?"** Build the Forgejo path now; it picks up each repo as
that repo flips; `homelab-cluster` flips last, at the GitOps cutover. Full reasoning in
[ADR-0011](architecture/adr-0011-dual-run-renovate-forgejo.md).

## Required Forgejo token scopes

The provisioner mints a **scoped access token** on the `renovate` bot user (Forgejo scope names;
`write:` implies `read:`):

| Scope | Grants |
| --- | --- |
| `write:repository` | clone, push branches, open/manage PRs |
| `read:user` | identify the bot |
| `write:issue` | the Dependency Dashboard issue + PR comments |
| `read:organization` | discover org repos (for the eventual `webgrip/*` rollout) |

`platformAutomerge` needs **Forgejo ≥ v10.0.0** — confirm the running version, else Renovate falls
back to branch automerge.

## Phased work

### Phase 0 — Forgejo bot + token (zero-touch, GitOps)

**Automated** by an idempotent provisioner CronJob — no manual Forgejo, token, or OpenBao steps.
Manifests under `kubernetes/apps/renovate/renovate-operator/jobs/`:

- `renovate-forgejo-admin.externalsecret.yaml` — replicates `forgejo/admin` from OpenBao (the only
  input; already present).
- `renovate-forgejo-bot-password.externalsecret.yaml` — ESO `password-generator` (generate-once +
  Retain) — the bot's password, never human-typed.
- `forgejo-bot-provisioner.{rbac,cronjob}.yaml` — the converging CronJob.

On each run the CronJob: (1) ensures the `renovate` bot user exists (admin API), (2) reuses the stored
token if it still authenticates — else resyncs the bot password and mints a fresh scoped token into
Secret `renovate-forgejo-token`, and (3) ensures the throwaway pilot repo exists + is seeded. It only
writes when something is missing/invalid, so re-runs are no-ops. All Forgejo calls go to the in-cluster
Service (`forgejo-http.forgejo.svc:3000`).

- [ ] Activate (uncomment the block in `kustomization.yaml`), then kick the first run:
      `kubectl -n renovate create job --from=cronjob/renovate-forgejo-provisioner provision-now`.
- [ ] Confirm `renovate-forgejo-token` exists and `renovate/forgejo-renovate-pilot` was created + seeded.

### Phase 1 — registry (GHCR) auth — nothing to do during dual-run

No separate GHCR PAT or OpenBao entry. The Forgejo RenovateJob **reuses the GitHub-App
token-minter's `RENOVATE_HOST_RULES`** (`renovate-runtime-token`), which already runs for the
GitHub path ([ADR-0013](architecture/adr-0013-github-as-renovate-data-oracle.md)) — wired as an
`extraEnv` `valueFrom` (`optional: true`) in `webgrip-forgejo.yaml`. GHCR re-homes to Harbor at
GitHub-path retirement (Phase 5).

### Phase 2 — manifests (dual-run, pilot-scoped)

Under `kubernetes/apps/renovate/renovate-operator/jobs/` (**already scaffolded, dormant**):

- `renovate-config-forgejo` **ConfigMap** — clone of `configmap-gitops.yaml` with
  `"platform": "forgejo"`, the `/api/v1` endpoint, the Forgejo `gitAuthor`
  (`Renovate Bot <renovate@${SECRET_DOMAIN}>`), and the `api.github.com` hostRules **kept** (version
  oracle).
- `webgrip-forgejo.yaml` **RenovateJob** — `provider: {name: forgejo, endpoint:
  https://forgejo.${SECRET_DOMAIN}/api/v1}`, `secretRef: renovate-forgejo-token` (minted by the Phase-0
  provisioner), `discoveryFilters: [renovate/forgejo-renovate-pilot]`, GHCR host-rules reused from
  `renovate-runtime-token` via `extraEnv` `valueFrom`, same `fringe` placement/securityContext as
  `webgrip-gitops`.

`${SECRET_DOMAIN}` is substituted by the jobs Kustomization `postBuild.substituteFrom: cluster-secrets`.
Validated via `./scripts/run-flux-local-test.sh`.

### Phase 3 — Forgejo-native webhook

- [ ] Add the operator `webhook.forgejo.sync` block to `webgrip-forgejo.yaml` (as a sibling of
      `authentication:` under `webhook:`), pointing at `/webhook/v1/forgejo`, reusing
      `renovate-webhook-auth` and the bot PAT for registration. **Confirm the exact
      `webhook.forgejo.*` field names against the installed operator CRD (chart 4.10.1) first** —
      the bot PAT also needs webhook-create rights on the target repo(s):

      ```yaml
      webhook:
        enabled: true
        authentication:
          enabled: true
          secretRef:
            name: renovate-webhook-auth
            key: token
        forgejo:
          sync:
            enabled: true
            webhookURL: https://renovate-webhook.${SECRET_DOMAIN}/webhook/v1/forgejo
            topic: renovate
            tokenSecretRef:
              name: renovate-forgejo-token
              key: FORGEJO_TOKEN
            authTokenSecretRef:
              name: renovate-webhook-auth
              key: token
      ```

### Phase 4 — pilot

The pilot repo is **bot-created** by the Phase-0 provisioner (`renovate/forgejo-renovate-pilot`,
seeded with a deliberately-stale `FROM alpine:3.18`), so **no real repo is de-mirrored for the pilot** —
zero risk to the live mirrors.

- [ ] Confirm the loop: *discovery → branch push → PR (alpine bump) → Dependency Dashboard → automerge*,
      with the Forgejo `renovate` bot as PR author. This flips the RFC + ADRs to **Accepted**.
- [ ] (Real repos are de-mirrored later, as part of each repo's actual cutover — Phase 5.)

### Phase 5 — scale-out + GitHub retirement

- [ ] Widen `webgrip-forgejo` `discoveryFilters` as repos flip to Forgejo-authoritative.
- [ ] At the final GitOps cutover (`homelab-cluster` **last**): delete `webgrip-gitops`,
      `renovate-config-gitops`, the `renovate-github-app-token` CronJob + RBAC, and the GitHub-App keys
      in OpenBao (`renovate/operator`); switch presets to `forgejo>webgrip/renovate-config`.

## Out of scope / sequenced elsewhere

- Porting `.github/workflows/` (incl. `renovate-dry-run`, `renovate-trigger`) to Forgejo Actions — CI
  thread of the forge migration.
- GHCR → Harbor — the `read:packages` PAT is the stopgap; re-homes under
  [RFC: Harbor](architecture/rfc-harbor-registry.md).
- GitOps source cutover — Flux still reconciles from GitHub; this must not precede it for
  `homelab-cluster`.
