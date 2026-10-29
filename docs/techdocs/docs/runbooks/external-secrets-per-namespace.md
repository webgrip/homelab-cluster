# External Secrets per namespace

Each namespace logs in to OpenBao with its own role and reads only the paths its own manifests name ([ADR-0087](../adr/adr-0087-each-namespace-reads-only-its-own-openbao-paths.md)). This page is how to add a secret under that rule, how to move a namespace onto it, and what to check when a store is not ready.

## The pieces

| Piece | Where | Written by |
| --- | --- | --- |
| Grants, one line per `<namespace> read\|database\|push <path>` | `kubernetes/apps/security/openbao/bootstrap/eso-grants.txt` | `python3 scripts/eso_grants.py --write` |
| ServiceAccounts `eso-openbao` and `eso-openbao-push`, SecretStores `openbao`, `openbao-db`, `openbao-push` per namespace | `kubernetes/apps/security/external-secrets/tenants/stores.generated.yaml` | the same command |
| Policies and roles `eso-read-<ns>`, `eso-push-<ns>` (tokens must carry audience `openbao`) | OpenBao | `eso-grants.sh`, run by the `openbao-eso-grants` Job whenever the grants change (Flux recreates it) and by the `openbao-config` CronJob every 5 minutes |
| The gate | lefthook `validate-eso-grants`, `e2e` step "Each namespace reads and writes only the OpenBao paths granted to it" | `scripts/eso_grants.py`, mutation test `scripts/test-eso-grants.sh` |

Never edit the two generated files by hand. Change the ExternalSecret or PushSecret, then regenerate.

## Add a secret

1. Write the ExternalSecret with `secretStoreRef: {kind: SecretStore, name: openbao}` (or `openbao-db` for `database/creds/<role>`). A PushSecret names `{kind: SecretStore, name: openbao-push}`.
2. Run `mise exec -- python3 scripts/eso_grants.py --write`.
3. Read the diff of `eso-grants.txt`. Every new line is a namespace gaining a path. A path that another namespace already reads is a shared credential; say why in the PR.
4. Commit the manifest, `eso-grants.txt` and `stores.generated.yaml` together.

The grants ride in a content-hashed ConfigMap, so the `openbao-eso-grants` Job is recreated and writes the new policy as soon as the `openbao-bootstrap` Kustomization reconciles. If the ExternalSecret's own Kustomization applies first it reports `permission denied` once and retries. If the Job failed: `kubectl -n security logs job/openbao-eso-grants`; the CronJob catches up within 5 minutes.

`dataFrom.find` and paths built from `${...}` are refused: a policy can only grant paths it can name.

## Move a namespace onto its own store

The rollout runs in three stages. Each stage is its own PR and can stop there.

1. **Roles and stores beside the old ones.** Merge, then check:
    * `kubectl -n security logs job/<latest openbao-config job> | grep "per-namespace ESO roles converged"` shows the count of roles.
    * `kubectl get secretstore -A` lists every store as `Valid` and `Ready`.
2. **Move namespaces.** For a batch of namespaces:
    1. `mise exec -- python3 scripts/eso_grants.py --move <ns> [<ns> ...]` swaps `ClusterSecretStore` for `SecretStore` in every file that lands only in those namespaces. A file rendered into several namespaces (the `cnpg-backup` component) moves only when all of them are in the batch; the command lists it as skipped otherwise.
    2. Merge, then for each moved namespace: `kubectl -n <ns> get externalsecret,pushsecret` shows every object `SecretSynced` / `Synced`. If one fails, its target Secret keeps its last value; revert the PR and look at the failing path.
    3. `mise exec -- python3 scripts/eso_grants.py --summary` shows `files-on-cluster-store=0` for the namespace.
Before merging any stage PR, bring it onto the current `main`: rebase, run `--write` (main may have gained or dropped ExternalSecrets), and for a stage 2 PR re-run its `--move` batch so files added since are moved too. The gate in that PR's `e2e` run then proves the grants match.

3. **Remove the broad roles.** When the summary shows 0 for every namespace: delete the `openbao`, `openbao-db` and `openbao-push` ClusterSecretStores, the `external-secrets` and `external-secrets-push` roles and their policies, and make the gate refuse any `ClusterSecretStore` named `openbao*`. Done: `openbao-config` deletes the two retired roles and policies on every run, and the gate refuses `kind: ClusterSecretStore`.

## A store is not ready

The `SecretStoreNotReady` alert fires after 15 minutes.

* `kubectl -n <ns> get secretstore <name> -o yaml | yq '.status'`. `permission denied` on login means the role does not exist yet or names another ServiceAccount.
* The latest `openbao-config` job log prints `WARN: eso-read-<ns> policy or role write FAILED` when a write failed.
* `mise exec -- python3 scripts/eso_grants.py .` lists any path that a manifest names and no grant covers.
* OpenBao sealed: see [External Secrets](external-secrets.md).

## Check the boundary

From a namespace's store, a path outside its grants must fail. In a scratch namespace that has a store (or a copy of one), an ExternalSecret naming `litellm` reports `permission denied`. The mutation test proves the gate's side of this on every run: it changes a freshrss ExternalSecret to read `litellm` and expects the check to fail.
