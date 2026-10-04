# Runbook: Secrets level 4 — short-lived

**Status:** active · **Scope:** credentials that exist only for a request or a lease: OIDC
tokens exchanged at the vault, dynamic database roles, transit signatures, per-run forge tokens
· **Model:** [ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) · **Deep dives:**
[dynamic-db-credentials](dynamic-db-credentials.md), [cosign-transit-key-rotation](cosign-transit-key-rotation.md)

> Nothing at this level rests anywhere. A job or a pod proves who it is, the vault mints
> something bound to that identity for a few minutes or hours, and it dies on its own. This is
> the direction for anything the vault can mint; the bridge (L3) is for what it cannot.

## The three shapes

| Shape | Identity | Minted by | TTL | Where configured |
| --- | --- | --- | --- | --- |
| CI signing | Forgejo Actions OIDC token, audience `openbao-cosign` | `auth/forgejo` JWT role `cosign-signer` | 10m | [`bootstrap/config.sh`](../../../../kubernetes/apps/security/openbao/bootstrap/config.sh), the role JSON with `bound_claims` |
| Database credentials | Kubernetes SA of ESO, store `openbao-db` | `database` engine role per app | per role | [ADR-0016](../adr/adr-0016-openbao-dynamic-postgres-credentials.md), `app/clustersecretstore-db.yaml` |
| Agent push rights | a Run holding a Lease | ploeg's minter, a repo-scoped Forgejo token | the Lease | [ploeg ADR-0013](https://forgejo.webgrip.dev/webgrip/ploeg/src/branch/main/docs/adrs/0013-push-rights-are-minted-per-run.md) |

## Let a repo's release workflow sign

`bound_claims` on the `cosign-signer` role is the allow-list. It is a JSON map in `config.sh`
because the CLI cannot take a map inline.

1. Add the repository to `"repository": [...]` in the `cosign-signer` role block of
   `config.sh`. Keep `event_name` and `ref` as they are unless the workflow shape differs.
2. Commit; the `openbao-config` CronJob re-asserts the role within five minutes.
3. In the workflow, request the token with Forgejo's OIDC and call cosign with
   `--key hashivault://cosign-webgrip`; the composite action in `webgrip/infrastructure`
   (`.forgejo/actions/cosign-sign-attest`) does both.
4. Verify: `bao read auth/forgejo/role/cosign-signer` lists the repo; the job log prints its
   claims and a signature without ever printing a key.

A fork pull request gets no token: its `repository` claim is not on the list.

## Give a CI job a scoped read on the vault

This is the pattern that retires bridge rows, and the ADR names the trigger for adopting it
widely. Today it is done per role, the same way as signing:

1. A policy `ci-<repo>` in `bootstrap/` granting `read` on `secret/data/<provider>/<purpose>`.
2. A JWT role `ci-<repo>` at `auth/forgejo` with `bound_claims.repository` set to that repo and
   `token_policies: ["ci-<repo>"]`, TTL 10m, in `config.sh`.
3. The workflow job sets `enable-openid-connect: true` and uses
   [`openbao-read`](https://forgejo.webgrip.dev/webgrip/workflows/src/branch/main/.forgejo/composite-actions/openbao-read/action.yml)
   from `webgrip/workflows` (audience `openbao-ci`), which exchanges the token at
   `auth/forgejo/login` and exports each value masked. The job must be declared in the repo's own
   workflow: Forgejo 15 gives no OIDC token to a job expanded from a reusable workflow.

`ci-unfold` and `ci-twente-dev` (DNS preview, [ADR-0061](../adr/adr-0061-ci-reads-over-oidc-writes-from-the-cluster.md))
are the first roles of this shape.

## Dynamic database credentials

Rollout state, verification and the PgBouncer pattern for single-replica apps are in
[dynamic-db-credentials](dynamic-db-credentials.md). The short version: a role per app on the
`database` engine, an ExternalSecret against `openbao-db`, and a TTL chosen by workload shape
(8 to 24h for surge-capable apps, about 1h behind a pooler).

## Revoke

- **A minted token:** it expires; there is nothing to revoke. For an emergency,
  `bao lease revoke -prefix auth/forgejo/` ends every live one.
- **Database leases:** `bao lease revoke -prefix database/creds/<role>` →
  [secret-break-glass](secret-break-glass.md) part 1.
- **The transit key:** rotate to a new version; old signatures stay valid →
  [cosign-transit-key-rotation](cosign-transit-key-rotation.md).

## Verify

```bash
mise exec -- bao read auth/forgejo/role/cosign-signer
mise exec -- bao list sys/leases/lookup/database/creds/<role>
mise exec -- bao read transit/keys/cosign-webgrip
```

The first shows the allow-list, the second the live leases, the third confirms the private key
is still a name and not a value.

## Gotchas

- Enabling an engine or an auth method needs root, which only exists during a fresh bootstrap.
  On a running instance that is a one-time break-glass `bao operator generate-root`, written
  down in [`init.sh`](../../../../kubernetes/apps/security/openbao/bootstrap/init.sh); the
  reconciler cannot do it.
- Token `iss` for Forgejo is `https://forgejo.<domain>/api/actions`; the role's discovery URL
  must match it exactly.
- The `workflow` claim is not yet bound on the signing role; the config comments name it as the
  next hardening once its exact value is confirmed from a job's printed claims.

## See also

- [infrastructure ADR-0004](https://forgejo.webgrip.dev/webgrip/infrastructure/src/branch/main/docs/adrs/0004-supply-chain-on-forgejo-harbor-openbao.md) — why signing went through the vault.
- [ADR-0016](../adr/adr-0016-openbao-dynamic-postgres-credentials.md) — why database credentials are leases.
