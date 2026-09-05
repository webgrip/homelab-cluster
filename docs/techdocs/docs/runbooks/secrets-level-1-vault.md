# Runbook: Secrets level 1 — the vault

**Status:** active · **Scope:** every provided value and every preserved at-rest key, held in
OpenBao KV v2 at `secret/` · **Model:**
[ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) · **Rotation:**
[secret-rotation](secret-rotation.md) · **Compromise:** [secret-break-glass](secret-break-glass.md)
· **Backend ops and DR:** [external-secrets](external-secrets.md), [openbao-restore](openbao-restore.md)

> The vault holds the only original. Everything else that carries the value is a cache the
> vault can regenerate (L2, L5) or a bridge the vault reconciles (L3). An agent never writes
> here: OpenBao auth for humans is Authentik OIDC with MFA, interactive by design.

## What goes here

- A value the outside world issued: an API token, an OIDC client secret, an S3 key, a webhook
  secret, a password you chose for something outside the cluster.
- An at-rest key that already encrypts data and must be preserved across reinstalls (seed the
  existing value once; never generate a second one).

What does not: entropy no human needs to know, which is born at L2 by generator; anything a
vault engine can mint per request, which is L4.

## Seed a value (a person, once)

Path convention: `secret/<provider>/<purpose>`, keys named as the consumer will read them.

```bash
mise exec -- just bao-login
export BAO_ADDR="$(mise exec -- just bao-addr)"
mise exec -- bao kv put secret/<provider>/<purpose> KEY=<value> OTHER_KEY=<value>
```

Type the value at a prompt rather than on the command line when a helper exists (`just
harbor-s3-cred`, `just cloudflare-deploy-cred` use `gum input --password`). For a recurring seed,
add a `just` recipe in the `secrets` group that prompts the same way; that is the estate's
answer to "how do I get a secret into the vault without it landing in shell history".

The UI works too: `openbao.${SECRET_DOMAIN}`, sign in with Authentik, engine `secret/`, create
the path, add keys. Same result, same audit trail.

A multi-key path is replaced whole by `put`. To change one key on an existing path use
`bao kv patch`; see [secret-rotation §3.1](secret-rotation.md).

## Who may write, who may read

| Identity | Auth | Policy | Can |
| --- | --- | --- | --- |
| A person in Authentik group `homelab-admins` | OIDC + MFA, group alias `openbao-admins` | `admins` (`path "*"`, sudo) | everything, including what the reconciler owns |
| `openbao-config` CronJob | Kubernetes SA, role `openbao-config`, TTL 20m | `config-admin` | policies, roles, identity, OIDC config; cannot mount engines |
| `external-secrets` SA | Kubernetes, role `external-secrets`, TTL 1h | `external-secrets` | read `secret/*` |
| `external-secrets` SA | Kubernetes, role `external-secrets-push`, TTL 1h | `external-secrets-push` | write `secret/*` (the roller store; see the ADR on narrowing it) |
| `openbao-snapshot` SA | Kubernetes, role `openbao-snapshot`, TTL 10m | `snapshot` | raft snapshot |
| A Forgejo release job | JWT at `auth/forgejo`, TTL 10m | `cosign-signer` | transit sign only, bound to listed repos and events |

The `admins` policy is `path "*"` because the lab has one admin. The trigger to split it into
`secret/*` for humans and leave `auth/` and `sys/` to `config-admin` is the second human
account; the ADR names that as the tightening point.

Policies and roles are code: [`bootstrap/config.sh`](../../../../kubernetes/apps/security/openbao/bootstrap/config.sh)
re-asserts them every five minutes. A change to who may do what is a change to that file and
the `.hcl` beside it, reconciled by the `openbao-config` CronJob, never a hand-run `bao policy write`.

## Rotate, revoke, restore

- **Planned rotation:** one write, then ESO and Reloader carry it → [secret-rotation](secret-rotation.md).
- **Suspected leak:** revoke at the provider first, then write → [secret-break-glass](secret-break-glass.md).
- **Roll back a bad write:** KV v2 keeps versions; `bao kv rollback -version=<n-1> secret/<path>`.
- **Backups:** the `openbao-snapshot` CronJob takes a raft snapshot at 03:00 daily and uploads
  it to Garage, keeping fourteen. A snapshot is only as good as the unseal key that opens it →
  [openbao-restore](openbao-restore.md) and [L0](secrets-level-0-floor.md).

## Verify

```bash
mise exec -- bao kv get secret/<provider>/<purpose>
mise exec -- bao kv metadata get secret/<provider>/<purpose>
kubectl get externalsecret -A | grep <purpose>
```

The second command shows the version number, which is the proof that a rotation landed as a
new version rather than nowhere.

## Gotchas

- `bao` targets localhost until `BAO_ADDR` is exported in the same shell; `just bao-login`
  prints the export line but cannot export into your shell.
- `read -rs VAR` in a script can capture nothing; echo `${VAR:-EMPTY}` before a `kv put`.
- `remoteRef.key` in an ExternalSecret omits the mount: `<provider>/<purpose>`, not
  `secret/<provider>/<purpose>` and never `secret/data/...`.
- ESO aborts at the first failing `data[]` entry, so a path that is half seeded hides every
  entry after the missing one.

## See also

- [ADR-0015](../adr/adr-0015-secret-rotation-model.md) — rotation is one vault write.
- [L2 cluster](secrets-level-2-cluster.md) — how a value gets from here into a pod.
- [L3 bridge](secrets-level-3-bridge.md) — how it gets into Forgejo Actions.
- `external-secrets` skill — the in-repo authoring recipe.
