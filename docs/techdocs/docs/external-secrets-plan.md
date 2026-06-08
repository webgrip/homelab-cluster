# Plan: External Secrets / secret automation

> Status: **planned, not implemented.** Goal: take the human out of the menial
> "generate → `sops --encrypt` → commit → uncomment" loop, without losing the
> GitOps model. Captured here so the work can be picked up later.

## The core insight: two classes of secret

| Class | Examples | Human judgement? | Automation |
| --- | --- | --- | --- |
| **Random / internal** | `BETTER_AUTH_SECRET`, `ENCRYPTION_SECRET`, Forgejo `SECRET_KEY`/`INTERNAL_TOKEN`/`JWT`/`LFS_JWT_SECRET`, runner 40-char secret, any app "session key" | **None** — pure entropy | **Fully automatable** (generate in-cluster) |
| **External / provider** | GitHub PAT, Codeberg token, Garage S3 keys, Authentik OIDC client secret, SMTP creds, `cnpg-backup-s3` | Obtain once from another system | **Centralize** (enter once, sync everywhere) |

Most of the day-to-day toil is the *random* class — that's the win to grab first.

## Phase 1 — kill the random-secret toil (no backend needed)

Deploy **one** of:

- **`mittwald/kubernetes-secret-generator`** (simplest): commit a normal Secret with
  `secret-generator.v1.mittwald.de/autogenerate: "BETTER_AUTH_SECRET,ENCRYPTION_SECRET"`;
  the operator fills stable random values in place. No SOPS, no human.
- **External Secrets Operator (ESO) `Password` generator** with `refreshInterval: 0`
  (generate once, never rotate unless asked). More moving parts, but unifies with Phase 2.

Convert these existing SOPS secrets to generated ones (values are throwaway entropy):
`gitea-mirror-secret`, the optional `forgejo-security-secret`, and (with a small
register Job) `forgejo-runner-secret`.

**Deliverable:** `kubernetes/apps/security/external-secrets/` (or `…/secret-generator/`)
as a normal Flux app (OCIRepository/HelmRelease), plus per-app `ExternalSecret`/annotated
Secret manifests replacing the random `*.sops.yaml` files.

## Phase 2 — centralize the external/provider secrets

Deploy **ESO** + a backend `ClusterSecretStore`. Backend options (self-hostable first):

- **Infisical** — self-hosted, good UI, CNPG-friendly. Recommended for this cluster.
- **OpenBao / Vault** — heavier, most powerful.
- **1Password Connect** — if a 1Password account already exists (this is what the
  `eleboucher/homelab` reference uses).

Flow: paste each external secret **once** into the backend → an `ExternalSecret` per app
syncs it into the right namespace. One place to enter, one place to rotate. ESO writes a
real k8s Secret, so a transient backend outage doesn't break running pods.

Migrate: `cnpg-backup-s3`, `forgejo-s3-secret`, `forgejo-oidc-secret`,
`forgejo-runner-scaler-token`, future GitHub/Codeberg tokens.

## Bonus eliminations

- **OIDC client secret**: have the Authentik blueprint **set** `client_secret` to a
  *generated* value (Phase 1) instead of letting Authentik mint it and copying it by hand.
  Both sides reference the same generated secret → zero copy. Applies to every
  `*-oidc-secret` (grafana, n8n, backstage, forgejo, …).
- **Runner registration**: generated 40-char secret + a one-shot Job running
  `forgejo forgejo-cli actions register --secret …` → no manual registration.

## Trade-offs / decisions to make

- **SOPS stays for the bootstrap floor**: the age key and `cluster-secrets` (which
  provides `${SECRET_DOMAIN}` to every ks) should remain SOPS — ESO can't bootstrap
  itself. SOPS and ESO coexist.
- **Runtime dependency**: ESO/backends must be reachable to *create/rotate* a secret
  (not to *use* one — k8s Secrets are cached). SOPS has no runtime dependency. Acceptable
  given ESO caching.
- **Blast radius**: a backend is a new high-value target; lock down its access + audit.

## First concrete steps (when picked up)

1. `add-app` scaffold ESO under `kubernetes/apps/security/external-secrets/` (chart
   `oci://ghcr.io/external-secrets/charts/external-secrets`), CRDs on.
2. Add a `Password` generator + convert `gitea-mirror-secret` as the pilot.
3. Stand up Infisical (or chosen backend) + a `ClusterSecretStore`; migrate one external
   secret (e.g. `forgejo-s3-secret`) as the pilot.
4. Roll the pattern across apps; delete the corresponding `*.sops.yaml`.
