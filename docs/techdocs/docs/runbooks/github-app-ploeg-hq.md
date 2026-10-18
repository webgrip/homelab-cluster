# The ploeg-hq GitHub App: rulesets, settings and Actions secrets from git

Two mechanisms in namespace `github-config` own the GitHub side of the delivery chain
([inventory](../general/delivery-chain-external-state.md) items G1–G4, G6, G7). Both authenticate
as one GitHub App, `ploeg-hq-gitops`, installed on `ploeg-hq/ploeg` only. Creating and installing
that App is the one step git cannot do (GitHub has no API for it). Everything else is built and
waits for it.

| Mechanism | Path | Owns | Runs |
| --- | --- | --- | --- |
| GitHub module | `kubernetes/apps/github-config/ploeg-hq/` (`model/ploeg-hq.yaml`, `tofu/`) | the three rulesets, repository settings, default branch, Actions permissions, the `RELEASE_CONSUMERS` variable | tofu-controller `Terraform/ploeg-hq`, hourly, plan-only |
| GitHub secrets bridge | `kubernetes/apps/github-config/secrets-bridge/` | Actions secret `RELEASE_CONSUMER_TOKEN_FORGEJO` | CronJob `github-secrets-bridge`, hourly at :41 |

No secret value enters tofu state: the module owns shape, the bridge owns values (repo-config
RFC §8.1). The module reads the App key through an ephemeral OpenBao read; the bridge reads it
over OpenBao Kubernetes auth, encrypts the token with the repository public key (libsodium
sealed box) and keeps only a SHA-256 fingerprint of the source in ConfigMap
`github-secrets-bridge-state`.

## State until the App exists

| Piece | What it does without the App | What you see |
| --- | --- | --- |
| `Terraform/ploeg-hq` | `spec.suspend: true`: no runner pod, no plan | `kubectl -n github-config get terraform` shows it suspended |
| `github-secrets-bridge` | reads OpenBao, finds no `secret/github/ploeg-hq-app`, logs `app credentials absent`, exits 0, touches nothing on GitHub | alert `GitHubAppPloegHqPending` at severity `info` |
| `GitHubConfigPloegHqNotReady` | gated on the bridge's `github_secrets_bridge_app_credentials_present == 1` | silent |

Why suspended rather than a failing plan: without the key the ephemeral read fails with the
provider's bare `Vault response was nil`, the runner would be recreated every retry, and the
first plan has to be read and approved in git anyway. Suspension says the same thing plainly and
costs nothing. The bridge does run, because it is the one piece that can see the credentials
arrive and report it. `info` routes to the `null` receiver: it is listed in vmalert and Grafana
alerting, it never pages, and it resolves on its own the first run after the key is stored.

## Owner steps (the one UI step)

1. Open <https://github.com/organizations/ploeg-hq/settings/apps/new>.
2. Fill in:
   - **GitHub App name:** `ploeg-hq-gitops` (any free name works; nothing reads it)
   - **Homepage URL:** `https://github.com/ploeg-hq/ploeg`
   - **Webhook:** untick **Active**. Leave the URL empty.
   - **Repository permissions:**
     - **Administration:** Read and write (rulesets, repository settings, Actions permissions)
     - **Secrets:** Read and write
     - **Variables:** Read and write
     - **Metadata:** Read-only (GitHub sets this itself)
     - every other repository permission: No access
   - **Organization permissions** and **Account permissions:** No access for all.
   - **Where can this GitHub App be installed?** Only on this account.
3. Click **Create GitHub App**. On the page that opens, note the **App ID** (a number).
4. Scroll to **Private keys**, click **Generate a private key**. A `.pem` file downloads.
5. In the left menu click **Install App**, then **Install** next to `ploeg-hq`. Choose
   **Only select repositories**, pick `ploeg-hq/ploeg`, click **Install**.
6. The browser lands on `https://github.com/organizations/ploeg-hq/settings/installations/<number>`.
   That number is the **installation ID**.
7. Store the three values in OpenBao:

   ```bash
   mise exec -- just bao-login
   export BAO_ADDR="$(mise exec -- just bao-addr)"
   mise exec -- bao kv put secret/github/ploeg-hq-app \
     app_id=<App ID> installation_id=<installation ID> private_key=@<path to the .pem>
   ```

8. Delete the downloaded `.pem` from your machine. OpenBao and its snapshots hold the copy.

That is all the owner has to do. The rest can be done by an agent.

## After the key is stored

1. **Bridge.** Run it now instead of waiting for :41, then read the log:

   ```bash
   mise exec -- kubectl -n github-config create job --from=cronjob/github-secrets-bridge github-secrets-bridge-first
   mise exec -- kubectl -n github-config logs job/github-secrets-bridge-first
   ```

   Expect `ploeg-hq/ploeg/RELEASE_CONSUMER_TOKEN_FORGEJO written (absent on GitHub)`. A second run
   prints `already matches the source; no write`. Confirm on GitHub without reading the value:
   `gh api repos/ploeg-hq/ploeg/actions/secrets/RELEASE_CONSUMER_TOKEN_FORGEJO` returns its
   `updated_at`. `GitHubAppPloegHqPending` resolves.
2. **Module, plan only.** Remove `suspend: true` from
   `kubernetes/apps/github-config/ploeg-hq/app/terraform.yaml`, commit, push. Read the plan:

   ```bash
   mise exec -- kubectl -n github-config get terraform ploeg-hq -o jsonpath='{.status.plan.pending}'
   mise exec -- kubectl -n github-config get cm tfplan-default-ploeg-hq -o jsonpath='{.data.tfplan}'
   ```

   It must read **Plan: 7 to import, 0 to add, 0 to change, 0 to destroy.** This was proven on
   2026-10-18 with a read-only local plan against the live repository. Any change line means the
   model or GitHub drifted; resolve it in the model before approving.
3. **Approve.** Set `spec.approvePlan` to the pending plan id, commit, push. After that apply, set
   `approvePlan: auto` (as the [access plane](access-plane.md) does), so drift is corrected hourly.

## Switching Ploeg → Unfold bumps to the producer (D5)

Today Unfold's Renovate Ploeg group is the single writer of Unfold's Ploeg pin (unfold#437
interim). The producer path (ploeg#173 reads `RELEASE_CONSUMERS` and uses
`RELEASE_CONSUMER_TOKEN_FORGEJO`) must not run at the same time, or two writers race on the same
pin. The model holds the variable behind `release_consumers_enabled: false`. Switch in this order,
with no Ploeg release in flight:

1. Confirm `RELEASE_CONSUMER_TOKEN_FORGEJO` exists (bridge step above) and the module applies
   with `approvePlan: auto`.
2. Set `release_consumers_enabled: true` in `model/ploeg-hq.yaml`, commit, push. The next plan
   shows `1 to add` (`github_actions_variable.release_consumers["RELEASE_CONSUMERS"]`); once
   applied, `gh api repos/ploeg-hq/ploeg/actions/variables/RELEASE_CONSUMERS` returns it. Nothing
   reads it yet, so this step alone changes no behaviour.
3. Revert unfold#437 so Renovate stops bumping Ploeg in Unfold.
4. Merge ploeg#173. From the next Ploeg release the producer opens the Unfold PR.

Between steps 3 and 4 a release would get no bump at all (a gap, not a race); do them back to
back. To roll back, revert ploeg#173 first, then restore unfold#437, then set the flag to false.

## Rotate the App key

1. On the App's settings page, **Generate a private key** (the old one keeps working).
2. `mise exec -- bao kv patch secret/github/ploeg-hq-app private_key=@<new .pem>`
3. Run the bridge job by hand (above) and check it succeeds; the next module plan uses the new key.
4. Delete the old key on the App's settings page, and the `.pem` from your machine.

The Forgejo token itself rotates on its own: `ploeg-release-provisioner` re-mints it, the
PushSecret updates `secret/forgejo/ploeg-release`, the bridge sees a new fingerprint and rewrites
the GitHub secret within the hour.

## How the bridge decides to write

It writes when any of these holds, and otherwise makes no write call:

- the secret is absent on GitHub;
- the source fingerprint differs from the one in `github-secrets-bridge-state`;
- GitHub's `updated_at` for the secret differs from the one recorded after the last write
  (someone changed it outside the bridge).

Every installation token it mints is scoped to `ploeg` with `secrets: write` and revoked at the
end of the run. Output passes through a redacting writer that blanks the source, the OpenBao
token, the installation token and the key, in addition to never printing them.

The image is `python:3.14-alpine` with the standard library only: the cluster has no package
index and the root filesystem is read-only. The RS256 signature and the sealed box are therefore
implemented in the script. `scripts/test-github-secrets-bridge.sh` runs it against a fake GitHub,
OpenBao and apiserver, where the fake verifies the JWT with `cryptography` and opens the sealed
box with PyNaCl. The same script mutates the bridge ten ways (always write, ignore a source change,
ignore drift on GitHub, store the value, log the source or the token without redaction, exit
non-zero when the App is absent, treat a 403 as absent, an unscoped token, a wrong nonce) and fails
if any mutant passes. It runs in the e2e workflow.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `GitHubAppPloegHqPending` | no `secret/github/ploeg-hq-app`, or one of its three keys empty | owner steps above |
| bridge log `OpenBao denied reading secret/github/ploeg-hq-app (403)` | policy or role missing | check `config.sh` in `security/openbao/bootstrap` ran (`openbao-config` CronJob) |
| bridge log `GitHub refused an installation token … (401)` | App key revoked or wrong `app_id` | rotate the key, check the App ID |
| bridge log `… (404)` or `(422)` on the token | App uninstalled, or `ploeg` not in the installation | reinstall on `ploeg-hq/ploeg` |
| bridge log `source value … is empty` | ExternalSecret `github-secrets-bridge-source` not synced | `kubectl -n github-config get externalsecret`; check `secret/forgejo/ploeg-release` |
| plan shows changes on a ruleset | someone edited it in the GitHub UI | decide which is right; change the model or let apply restore it |
| runner cannot download providers | FQDN egress policy misses a GitHub download host | add it to `github-config-ploeg-hq-runner-egress` |
