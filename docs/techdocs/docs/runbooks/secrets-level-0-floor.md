# Runbook: Secrets level 0 — the floor

**Status:** active · **Scope:** the secrets that must exist before OpenBao does · **Model:**
[ADR-0055 — one secrets model, six levels](../adr/adr-0055-one-secrets-model-six-levels.md)
· **Siblings:** [L1 vault](secrets-level-1-vault.md), [OpenBao restore](openbao-restore.md)

> The floor is a closed list. Nothing joins it without a new ADR, and nothing on it is ever
> migrated to the vault, because the vault cannot bootstrap itself from secrets it manages.

## What is on the floor

| Item | Where it rests | Who reads it |
| --- | --- | --- |
| The age private key | On the operator's machine as `SOPS_AGE_KEY_FILE`; in-cluster as the Secret Flux decrypts with, seeded from `bootstrap/sops-age.sops.yaml` by `scripts/bootstrap-apps.sh` | `sops`, Flux's kustomize-controller |
| `talos/talsecret.sops.yaml` | Git, encrypted | `talhelper` when generating machine configs |
| `kubernetes/components/sops/cluster-secrets.sops.yaml` | Git, encrypted | Flux `postBuild.substituteFrom` in every `ks.yaml` that renders `${SECRET_DOMAIN}` |
| The OpenBao unseal key | The Secret `security/openbao-keys`, written once by the `openbao-init` CronJob; not in Git, not in S3 | The `openbao-unsealer` Deployment |

Exactly three `*.sops.yaml` secret files exist for the floor. Confirm with:

```bash
find . -name '*.sops.yaml' -not -name '.sops.yaml'
```

Any path beyond `bootstrap/sops-age`, `talos/talsecret` and `kubernetes/components/sops/cluster-secrets`
is a straggler, not floor. On 2026-09-05 four such files remain, all live-wired:
`kubernetes/apps/erfbeeld/{dev,staging,production}/app/secret.sops.yaml` and
`kubernetes/apps/zomboid/zomboid/app/secret.sops.yaml`. Migrate them with the seed-then-swap
recipe in the [ESO runbook](external-secrets.md) or delete them; until then the floor check fails.

`AGENTS.md` and the ESO runbook also list `bootstrap/github-deploy-key.sops.yaml`. No such file
exists in the tree; the Flux source moved to Forgejo
([ADR-0011](../adr/adr-0011-flux-source-forgejo.md)). Treat those two mentions as stale.

## Add to the floor

Write the ADR first. It has to say why the value is needed before the vault exists, because
that is the only reason the floor accepts. Then:

1. If the path pattern is new, add a `creation_rules` entry in [`.sops.yaml`](../../../../.sops.yaml)
   with `mac_only_encrypted: true` and, for Kubernetes Secrets, `encrypted_regex: "^(data|stringData)$"`.
2. Write the plaintext to a scratch file outside the repo, encrypt it into place:

   ```bash
   mise exec -- sops --encrypt --input-type yaml --output-type yaml /path/outside/repo.yaml > <target>.sops.yaml
   ```

3. Commit the ciphertext only. The `guard-secrets` hook refuses a `*.sops.yaml` write without
   `ENC[`, and refuses any path containing `decrypted`.

## Rotate the age key

The age key wraps every floor file, so its rotation touches all of them at once and every
place a copy lives.

1. Generate a new key pair on the operator machine: `age-keygen -o <new-key-file>`.
2. Add the new recipient to every `creation_rules` entry in `.sops.yaml` alongside the old one.
3. Re-encrypt each floor file to both recipients: `mise exec -- sops updatekeys <file>` for the
   three paths above.
4. Replace the in-cluster copy: re-encrypt `bootstrap/sops-age.sops.yaml` with the new private
   key as its payload and re-run the bootstrap step that seeds Flux's decryption Secret.
5. Remove the old recipient from `.sops.yaml`, run `sops updatekeys` again, commit.
6. Update every off-repo copy. Known copies on 2026-09-05: the Forgejo Actions secret
   `SOPS_AGE_KEY`, referenced by nine workflows in `webgrip/workflows` and not published by any
   bridge, so it is hand-entered. Where it is stored between rotations is an open item of this
   runbook; the ADR's rule says it should be an L1 value with an L3 row, so that a rotation is
   one vault write.

## The unseal key

The unseal key is the one floor item with no encrypted copy in Git. The restore runbook's
warning stands: a raft snapshot cannot be opened without the unseal key that was active when it
was taken, and a namespace wipe destroys `openbao-keys`. Back it up off-cluster once, and again
after any re-init:

```bash
mise exec -- kubectl get secret openbao-keys -n security -o jsonpath='{.data.unseal-key}' | base64 -d
```

Store the result where the age key lives, with the same care. Do not paste it into a file in
any repo. This is the second open item of this runbook: the ADR names the unseal key as floor,
and floor items have an encrypted copy in Git; this one does not yet.

## Verify

- `find . -name '*.sops.yaml' -not -name '.sops.yaml'` lists exactly three paths.
- `mise exec -- sops --decrypt kubernetes/components/sops/cluster-secrets.sops.yaml >/dev/null`
  succeeds on the operator machine (proves the local age key still matches).
- `kubectl get secret openbao-keys -n security` exists and the `openbao-0` pod reports
  unsealed within a minute of a restart.

## See also

- [ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) — why the floor is closed.
- [OpenBao restore](openbao-restore.md) — the unseal key's role in disaster recovery.
- [The long goodbye to SOPS](../blogs/2026-06-12-the-long-goodbye-to-sops.md) — how the floor was drawn.
- `guard-secrets` skill in `webgrip/ai-skills` — the hook that keeps plaintext out of this level.
