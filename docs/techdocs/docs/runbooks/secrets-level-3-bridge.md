# Runbook: Secrets level 3 — bridges

**Status:** active · **Scope:** copies of L1 values in stores that cannot pull from the vault:
Forgejo Actions secrets, Cloudflare Worker secrets · **Model:**
[ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) · **Engine notes:**
[forgejo-actions-engine](../general/forgejo-actions-engine.md)

> A bridge is a CronJob that reads an L2 copy of an L1 value and PUTs it into a platform on a
> timer, validates it against the provider, and fails loud when the provider rejects it. It
> never holds an original, so a rotation is a vault write and an hour of patience.

## The bridges

| CronJob | Namespace, schedule | From | To | Alert |
| --- | --- | --- | --- | --- |
| [`forgejo-actions-secrets`](../../../../kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-actions-secrets.cronjob.yaml) | `forgejo`, hourly at :23 | `forgejo-*` ExternalSecrets in the same namespace | Forgejo org and repo Actions secrets and variables | `ForgejoActionsSecretsReconcileStale` |
| [`counterscale-worker-secrets`](../../../../kubernetes/apps/forgejo/forgejo-actions-secrets/app/counterscale-worker-secrets.cronjob.yaml) | `forgejo`, hourly | `counterscale-worker`, `counterscale-jwt` | Cloudflare Worker runtime secrets | same family |
| [`cloudflare-token-roller`](../../../../kubernetes/apps/forgejo/forgejo-actions-secrets/app/cloudflare-token-roller.cronjob.yaml) | `forgejo`, monthly | the manager token | a rolled deploy token value, pushed back to L1 by PushSecret | fails loud on API error |

## Add a repo-scoped Forgejo Actions secret

Repo-scoped is the default. Org-wide is for values every release-path workflow needs
(`HARBOR_ROBOT_*`, `WEBGRIP_CI_TOKEN`, `DT_API_KEY`) and the block says why.

1. **L1:** a person seeds `secret/<provider>/<purpose>` with key `<PROVIDER>_<PURPOSE>`
   ([L1](secrets-level-1-vault.md)). Until then every step below is fail-soft: the
   ExternalSecret reports `SecretSyncedError` and the bridge logs "not present yet; skipping".
2. **L2:** add `kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-<provider>.externalsecret.yaml`
   reading that path into Secret `forgejo-<provider>`, and list it in the directory's
   `kustomization.yaml`. Template: `forgejo-brevo.externalsecret.yaml` in the same directory.
3. **Bridge:** in the CronJob, add an `env` entry with `secretKeyRef: {name: forgejo-<provider>,
   key: <NAME>, optional: true}` and, where the target repo is a fixed fact, a plain `value`
   env for the repo name. Then a block before the final reconcile line:

   ```sh
   if [ -n "${<NAME>:-}" ]; then
     put_repo_secret "${<REPO_ENV>}" <NAME> "$<NAME>" || rc=1
     _code="$(curl -sS -o /dev/null -w '%{http_code}' -H "<auth header>" <provider verify url>)" || _code=000
     if [ "$_code" != "200" ]; then
       echo "[forgejo-actions-secrets] ERROR: <NAME> rejected by <provider> (HTTP ${_code}); rotate at OpenBao secret/<provider>/<purpose>"
       rc=1
     else
       echo "[forgejo-actions-secrets] <NAME> valid"
     fi
   else
     echo "[forgejo-actions-secrets] <provider> key not present yet; skipping (seed OpenBao secret/<provider>/<purpose>)"
   fi
   ```

   The verify call is not optional. A provider without a verify endpoint is written down in the
   block as such, so a reviewer sees which tokens fail only at use.
4. **Validate and ship:** `./scripts/run-flux-local-test.sh`, commit, push. The next :23 tick
   publishes; or a person runs the job now:
   `kubectl create job --from=cronjob/forgejo-actions-secrets forgejo-actions-secrets-now -n forgejo`.
5. **Consume:** in the repo's workflow, `${{ secrets.<NAME> }}` in a job's `env`, passed to a
   reusable workflow from the calling job. `workflow_call: secrets:` is rejected by Forgejo's
   parser.

The first instance of this recipe is `BREVO_API_KEY` for `twente.dev`: `secret/brevo/twente-dev`,
`forgejo-brevo`, verified against `GET https://api.brevo.com/v3/account`.

## The Open VSX publish token

`webgrip/de-vloer` ships a VS Code extension, and its publish token needs a verify call that is
not the obvious one. It is recorded here because the block itself carries no comment.

| Secret | Vault path | Secret name | Seed | Verify |
| --- | --- | --- | --- | --- |
| `OVSX_PAT` | `secret/openvsx/de-vloer` | `forgejo-openvsx-publish` | `just openvsx-cred` | `POST https://open-vsx.org/api/-/namespace/create` |

The seed goes through `just openvsx-cred`, which prompts with `gum` so the token never reaches argv or shell history, and rejects a token Open VSX does not accept rather than writing a dead value into the vault.

**Open VSX has no whoami.** `GET /user` is session-cookie based: it answers `200` with a body of
`{"error":"Not logged in."}` for any bearer token, so its status code proves nothing. The
namespace-create endpoint checks authentication before it checks whether the namespace exists, so
it answers `401` for a dead token and something else for a live one. The block therefore treats
`401` as the only failure — a non-401 is success even when the body says the namespace already
exists, which is the expected answer now that `webgrip` is claimed. The call is idempotent and
creates nothing that should not already be there.

There is deliberately no Visual Studio Marketplace row. Publishing there needs an Azure DevOps
organization, which since 2026 requires an attached Azure subscription, and the PAT it would
issue is retired on 2026-12-01 regardless. De Vloer ships to Open VSX only until that trade is
worth making; see its
[ADR-0021](https://forgejo.webgrip.dev/webgrip/de-vloer/src/branch/development/docs/adrs/0021-the-extension-ships-through-open-vsx-first.md).

Until the table refactor named in the ADR lands, this is three edits in one file. When it
lands, steps 2 and 3 collapse into one row plus one ExternalSecret; this runbook is updated then.

## Naming

- Forgejo rejects the reserved prefixes `FORGEJO_`, `GITHUB_`, `GITEA_`; the bot token is
  published as `WEBGRIP_CI_TOKEN` for that reason.
- A repo-level secret shadows an org-level one of the same name. `TECHDOCS_S3_*` relies on
  that to give each docs repo a bucket-scoped key while the org keeps a read-only one.
- Non-secret configuration goes out as an org or repo **variable** (`put_var`), never as a
  secret, so a workflow can read it without masking.

## Rotate

Write the new value at L1 ([secret-rotation](secret-rotation.md)). The ExternalSecret refreshes
within an hour, the bridge re-publishes on its next tick, and the verify call proves the new
value works before any workflow uses it. To skip the wait: force-sync the ExternalSecret, then
run the job as in step 4.

## Revoke

Revoke at the provider first. The bridge's next tick fails its verify call, the alert fires,
and the log names the vault path to fix. Seed the replacement; the following tick clears it.
A revoked value that is still published is harmless: it no longer works anywhere.

## Verify

- The bridge log shows `created repo secret webgrip/<repo>/<NAME>` or `updated ...` and
  `<NAME> valid`.
- Forgejo, repository settings, Actions, Secrets lists `<NAME>`; the org settings do not.
- Values are write-only over the API; existence is the `PUT ... 201|204` line, never a read.
- `ForgejoActionsSecretsReconcileStale` is quiet in Alertmanager.

## Gotchas

- `secrets: inherit` is used nowhere in the estate; every secret crosses a `uses:` boundary
  explicitly, which is what makes repo scoping reviewable.
- A workflow in a repo that was never listed for a repo-scoped secret fails with an empty
  value. That is the contract, not a bug; add the repo to the block.
- The CronJob reads Secrets only from its own namespace, which is why the Cloudflare Worker
  bridge lives in `forgejo` beside its transport credential.

## See also

- [L4 short-lived](secrets-level-4-short-lived.md) — the direction that retires bridge rows.
- [workflows ADR-0004](https://forgejo.webgrip.dev/webgrip/workflows/src/branch/main/docs/adrs/0004-ci-bot-identity-and-forgejo-package-distribution.md) — the `CI_TOKEN` contract.
