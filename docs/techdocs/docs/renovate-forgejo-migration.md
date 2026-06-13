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

A **scoped access token** on the `renovate` bot user:

| Scope | Permission |
| --- | --- |
| `repo` | Read **and Write** |
| `user` | Read |
| `issue` | Read **and Write** |
| `organization` | Read |
| `read:packages` | Read (only if Forgejo packages become a datasource) |

`platformAutomerge` needs **Forgejo ≥ v10.0.0** — confirm the running version, else Renovate falls
back to branch automerge.

## Phased work

### Phase 0 — Forgejo bot identity + token (manual, one-time)

- [ ] Create a local `renovate` bot user (`gitea_admin` break-glass / `forgejo admin user create` —
      **not** an Authentik SSO login; the forge allows external registration only).
- [ ] Generate the scoped PAT above for that user.
- [ ] Store it in OpenBao at `renovate/forgejo` (key `RENOVATE_TOKEN`):
      `bao kv put secret/renovate/forgejo RENOVATE_TOKEN=<forgejo-bot-pat>`. That is the **only**
      manual OpenBao write for this migration.

### Phase 1 — registry (GHCR) auth — nothing to do during dual-run

No separate GHCR PAT or OpenBao entry. The Forgejo RenovateJob **reuses the GitHub-App
token-minter's `RENOVATE_HOST_RULES`** (`renovate-runtime-token`), which already runs for the
GitHub path ([ADR-0013](architecture/adr-0013-github-as-renovate-data-oracle.md)) — wired as an
`extraEnv` `valueFrom` (`optional: true`) in `webgrip-forgejo.yaml`. GHCR re-homes to Harbor at
GitHub-path retirement (Phase 5).

### Phase 2 — manifests (dual-run, pilot-scoped)

Under `kubernetes/apps/renovate/renovate-operator/jobs/` (**already scaffolded, dormant**):

- [ ] `renovate-forgejo-token` **ExternalSecret** (`openbao` ClusterSecretStore) → `RENOVATE_TOKEN` +
      `FORGEJO_TOKEN` (operator discovery), both from the single `renovate/forgejo` PAT.
- [ ] `renovate-config-forgejo` **ConfigMap** — clone of `configmap-gitops.yaml` with
      `"platform": "forgejo"`, the Forgejo `gitAuthor` (`Renovate <renovate@${SECRET_DOMAIN}>`), and
      the `api.github.com` hostRules **kept** (version oracle).
- [ ] `webgrip-forgejo.yaml` **RenovateJob** — `provider: {name: forgejo, endpoint:
      https://forgejo.${SECRET_DOMAIN}/api/v1}`, `secretRef: renovate-forgejo-token`, same `fringe`
      nodeSelector/tolerations + securityContext as `webgrip-gitops`. **Scope `discoveryFilters` to
      the pilot repo only.**
- [ ] Register the new files in the jobs `kustomization.yaml`. `${SECRET_DOMAIN}` is substituted by the
      jobs Kustomization `postBuild.substituteFrom: cluster-secrets`.
- [ ] Validate: `./scripts/run-flux-local-test.sh`.

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

### Phase 4 — pilot on one authoritative repo

- [ ] De-mirror one low-stakes repo in `gitea-mirror` (make it Forgejo-authoritative).
- [ ] Confirm the loop: *discovery → branch push → PR → Dependency Dashboard → webhook → automerge*,
      with the Forgejo bot as PR author. This flips the RFC + ADRs to **Accepted**.

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
