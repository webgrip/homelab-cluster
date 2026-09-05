# Runbook: Secrets level 2 — the cluster

**Status:** active · **Scope:** Kubernetes Secrets materialised by External Secrets Operator,
from the vault or from a generator · **Model:**
[ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) · **Authoring recipe:** the
`external-secrets` skill · **Ops and DR:** [external-secrets](external-secrets.md)

> L2 is a cache. ESO writes real Secrets into etcd; pods read them like any other Secret and
> keep running when the vault is down. That property is why nothing at this level is ever an
> original, and why the write path is a controller, never a person.

## Decide by origin

| Origin | Shape | Example by path |
| --- | --- | --- |
| Entropy no human needs (admin password, session or CSRF key, robot password) | `ExternalSecret` with `dataFrom.sourceRef.generatorRef` → `password-generator` (or `-16`, `-32` for exact lengths), `refreshInterval: "0"`, `target.deletionPolicy: Retain` | `kubernetes/apps/harbor/harbor/app/harbor-admin.externalsecret.yaml` |
| A value the vault holds (L1) | `ExternalSecret` with `secretStoreRef: {kind: ClusterSecretStore, name: openbao}`, `creationPolicy: Owner`, `data[].remoteRef` per key or `dataFrom: [{extract: {key: <provider>/<purpose>}}]` for all keys | `kubernetes/apps/forgejo/forgejo-actions-secrets/app/cloudflare-deploy.externalsecret.yaml` |
| A credential minted per lease (L4) | `ExternalSecret` against `ClusterSecretStore/openbao-db` | [dynamic-db-credentials](dynamic-db-credentials.md) |
| A value a roller produced in-cluster that must become the L1 original | `PushSecret` to `ClusterSecretStore/openbao-push`, one `data[].match` per key | `kubernetes/apps/forgejo/forgejo-actions-secrets/app/cloudflare-deploy-rolled.pushsecret.yaml` |

Consume with `existingSecret`, `envFrom`, or `extraEnvFrom`. A workload that must pick up a
rotated value carries `reloader.stakater.com/auto: "true"`; a workload holding an at-rest key
deliberately does not.

## Add

1. Write the `ExternalSecret` next to the app under `kubernetes/apps/<ns>/<app>/app/`, list it
   in that directory's `kustomization.yaml`.
2. For an L1 value, hand the seed to a person ([L1](secrets-level-1-vault.md)). The
   ExternalSecret reports `SecretSyncedError` until the path exists; that is expected.
3. Validate: `./scripts/run-flux-local-test.sh`.
4. Commit and push; Flux applies within its interval.

## Verify

```bash
kubectl get externalsecret <name> -n <ns>
kubectl get secret <name> -n <ns> -o jsonpath='{.metadata.ownerReferences[0].kind}{"\n"}'
kubectl get secret <name> -n <ns> -o jsonpath='{.data}' | jq 'keys'
```

Want `READY=True / SecretSynced`, owner `ExternalSecret`, and the exact key set. A
`refreshTime` of `null` means it has never synced, not that it is pending.

## Rotate and regenerate

- An L1-backed Secret rotates by a vault write; ESO re-reads within `refreshInterval` or on
  `kubectl annotate externalsecret <name> -n <ns> force-sync="$(date +%s)" --overwrite` →
  [secret-rotation](secret-rotation.md).
- A generated Secret regenerates by deleting it; ESO recreates every `dataFrom` entry with fresh
  values. Safe only before the app has stored data behind any of those keys.
- Break-glass across all generated class-C secrets is a label sweep → [secret-break-glass](secret-break-glass.md).

## Gotchas

- A generator with `refreshInterval: "0"` never picks up a key added later to the same
  ExternalSecret; delete the Secret once to reseed, and only on an app with nothing at rest.
- An at-rest key is an L1 value seeded once. Generating it twice corrupts everything the first
  one encrypted.
- Component-level secrets (`cnpg-backup`, `*-s3`) have no `namespace:` and render per
  namespace; one L1 path feeds every copy.
- A live Secret nobody owns is adopted in place by `creationPolicy: Owner`; there is no delete
  gap during a migration.

## See also

- [external-secrets runbook](external-secrets.md) — topology, migration recipe, diagnostics.
- [L1 vault](secrets-level-1-vault.md) — where the value came from.
- [L4 short-lived](secrets-level-4-short-lived.md) — when a lease beats a stored value.
