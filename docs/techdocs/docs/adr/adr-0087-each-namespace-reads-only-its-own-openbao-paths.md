---
status: proposed
date: 2026-10-25
decision-makers: Ryan Grippeling
---

# Each namespace reads only its own OpenBao paths

## Context and Problem Statement

On 2026-10-24 the three ClusterSecretStores `openbao`, `openbao-db` and `openbao-push` all logged in to OpenBao as the External Secrets Operator's own ServiceAccount, through two roles whose policies cover every path: `external-secrets.hcl` reads `secret/data/*` and `database/creds/*`, and `push.hcl` reads and writes `secret/data/*`. A ClusterSecretStore can be named from any namespace. So anyone who can create an ExternalSecret in any namespace can pull any credential in the vault into a Secret they can read: the LiteLLM master key, the bot passwords, the Cloudflare tokens. An ExternalSecret that names `openbao-push` can do the same, and can also overwrite the value.

[ADR-0055](adr-0055-one-secrets-model-six-levels.md) placed ESO at level 2 and asked for the push policy to be narrowed. It did not say who may read what.

How should a namespace be limited to the secrets its own workloads use, without breaking an app that runs today?

## Decision Drivers

* A namespace that is compromised, or that an agent can write to, must not reach another namespace's credentials.
* The grant must be visible in review: adding a secret path to a namespace is a line in a diff, not an edit in the vault.
* Every app keeps syncing during the change. No value is re-entered.
* KV paths follow `<provider>/<purpose>`, not `<namespace>/...`, and several paths are read by more than one namespace on purpose (`harbor/robot-webgrip`, `s3/cnpg-backup`, the honeytokens).

## Considered Options

* A SecretStore per namespace, each logging in as its own role with a policy generated from what that namespace's manifests name
* Keep the ClusterSecretStores and use ESO referent authentication, with per-namespace policies attached to OpenBao identity entities
* One templated policy that allows `secret/data/<namespace>/*`
* ClusterSecretStores per namespace, restricted with `spec.conditions`
* Keep the cluster-wide stores and audit reads in OpenBao's log

## Decision Outcome

Chosen option: **"A SecretStore per namespace"**, because it enforces the boundary in OpenBao itself, needs no path renames, keeps the change to each ExternalSecret to one word, and lets each namespace prove its role works (its store turns `Valid`) before any ExternalSecret depends on it.

* **Inventory:** [`scripts/eso_grants.py`](../../../../scripts/eso_grants.py) walks the tree the way Flux applies it, from `kubernetes/flux/cluster/ks.yaml` through every Flux Kustomization and kustomize resource, works out the namespace each ExternalSecret and PushSecret lands in, and lists the OpenBao paths it names.
* **Data:** [`eso-grants.txt`](../../../../kubernetes/apps/security/openbao/bootstrap/eso-grants.txt) holds one line per grant, `<namespace> read|database|push <path>`. `--write` regenerates it; a reviewer reads its diff.
* **Vault side:** the `openbao-config` CronJob runs [`eso-grants.sh`](../../../../kubernetes/apps/security/openbao/bootstrap/eso-grants.sh), which writes a policy and a Kubernetes-auth role per namespace, each requiring tokens for the audience `openbao`: `eso-read-<ns>` bound to ServiceAccount `<ns>/eso-openbao`, and `eso-push-<ns>` bound to `<ns>/eso-openbao-push`. Read policies list exact paths with `read`; push policies list exact paths with `create, read, update, delete`. Roles whose namespace left the file are deleted. The grants travel in their own content-hashed ConfigMap, so a change to them gives the `openbao-eso-grants` Job a new spec; Flux recreates it (`kustomize.toolkit.fluxcd.io/force`) and the grant lands within a minute of the reconcile. The CronJob re-asserts everything every five minutes.
* **Cluster side:** [`stores.generated.yaml`](../../../../kubernetes/apps/security/external-secrets/tenants/stores.generated.yaml) puts the two ServiceAccounts and the `SecretStore`s `openbao`, `openbao-db` and `openbao-push` in each namespace that needs them. A namespaced SecretStore can only use a ServiceAccount from its own namespace, so a namespace cannot borrow another's role.
* **Gate:** `python3 scripts/eso_grants.py .` fails when a manifest names a path its namespace is not granted, when a grant is unused, or when the generated stores are stale. It runs in lefthook and in the `e2e` workflow, with the mutation test [`scripts/test-eso-grants.sh`](../../../../scripts/test-eso-grants.sh).
* **Push stays apart:** PushSecrets use their own ServiceAccount, role and store per namespace. This is the narrowing ADR-0055 asked for: a namespace can only write the paths its PushSecrets name.

The rollout has three stages, each safe to stop after: add the per-namespace roles and stores beside the old ones; move namespaces from `ClusterSecretStore` to `SecretStore` one batch at a time; then delete the three ClusterSecretStores and the `external-secrets` and `external-secrets-push` roles. The [runbook](../runbooks/external-secrets-per-namespace.md) has the steps and the checks.

### Consequences

* Good, because a namespace that is taken over can read only the paths it already used, and write only the paths it already pushed.
* Good, because every new grant is a reviewed line in `eso-grants.txt`.
* Good, because the ESO controller keeps the same RBAC: it already creates ServiceAccount tokens to log in.
* Bad, because a new secret now needs `python3 scripts/eso_grants.py --write` before the commit; the hook says so when it is missing.
* Bad, because a grant reaches OpenBao one Job run after Flux applies it, and the ExternalSecret and the grant land in different Kustomizations. An ExternalSecret that syncs first reports `permission denied` once and retries.
* Bad, because shared paths stay shared: every CNPG namespace still reads, and pushes, `s3/cnpg-backup`. Removing that PushSecret, a leftover of the SOPS migration, is a separate change.
* Bad, because grants that should disappear are carried over until their ExternalSecrets go: `ploeg` reads `litellm` (the LiteLLM master key), `forgejo/agent-builder` (the shared `AGENT_BUILDER_TOKEN`) and `forgejo/agent-builder-password`. RFC-0011 removes them; when it deletes those ExternalSecrets the gate refuses the now-unused grants until they are dropped.
* Neutral, because what a namespace may read is still decided by whoever can merge to `main`. This record limits the blast radius of a namespace, not of the repository.

### Confirmation

* `python3 scripts/eso_grants.py .` passes on `main`, and `bash scripts/test-eso-grants.sh` reports `wrong verdicts: 0`.
* `kubectl get secretstore -A` lists `openbao` as `Valid` in every namespace in `eso-grants.txt`.
* After stage 3, `kubectl get clustersecretstore` lists none of `openbao`, `openbao-db`, `openbao-push`, and `bao read auth/kubernetes/role/external-secrets` fails.
* From a namespace's store, an ExternalSecret naming a path outside its grants reports `permission denied`.

## Pros and Cons of the Options

### ESO referent authentication with identity-entity policies

ESO 2.11 supports it for the Vault provider: a ClusterSecretStore whose `serviceAccountRef` has no `namespace` requests the token for that ServiceAccount in the ExternalSecret's namespace, and caches one client per namespace (`providers/v1/vault/auth.go` `createServiceAccountToken`, `provider.go` `isReferentSpec`). The store can name only one `role`, so per-namespace rights would come from OpenBao identity: the role sets `alias_name_source=serviceaccount_name` (alias `<ns>/<sa>`, `builtin/credential/kubernetes/path_login.go`), and the reconciler pre-creates one entity per namespace carrying its policy.

* Good, because no ExternalSecret changes.
* Bad, because ESO cannot validate a referent store (`ValidationResultUnknown`), so nothing proves a namespace's identity works before the switch, and the switch is one flip for every namespace at once.
* Bad, because the grant lives in identity entities and aliases, which are harder to review and to reason about than a role per namespace.

### One templated policy on `secret/data/<namespace>/*`

* Good, because there is one policy and nothing to generate.
* Bad, because every one of the 131 KV paths would move, with a PushSecret-and-swap per path, and the shared paths would need a copy per reader.

### ClusterSecretStores per namespace with `spec.conditions`

* Good, because ExternalSecrets could keep `kind: ClusterSecretStore`.
* Bad, because the boundary is enforced by ESO's condition check, not by OpenBao, so one wrong condition or one ESO bug opens it, and 23 cluster-scoped stores clutter the cluster scope.

### Audit only

* Good, because nothing changes.
* Bad, because it detects a read after the credential has left.

## More Information

* Ticket: [VIK-2384](https://vikunja.webgrip.dev/tasks/2384).
* Refines [ADR-0055](adr-0055-one-secrets-model-six-levels.md) (level 2, and its `openbao-push` narrowing) and [ADR-0016](adr-0016-openbao-dynamic-postgres-credentials.md) (`database/creds/*` is now granted per namespace).
* 2026-10-25 — Proposed with stage 1.
* 2026-10-25 — Stages 2 and 3 prepared as stacked PRs: every reachable ExternalSecret and PushSecret names its namespace's SecretStore, the ClusterSecretStores and the `external-secrets`, `external-secrets-push` roles are removed, and the gate refuses `kind: ClusterSecretStore`.
