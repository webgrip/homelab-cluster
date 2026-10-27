# The webgrip GitHub App: archive the dead GitHub mirrors from git

The `webgrip` GitHub organisation still holds the push mirrors of Forgejo repositories whose
release paths are dead, and one GitHub-leading fork. [ADR-0078](../adr/adr-0078-one-release-recipe-four-kinds.md)
(R4) archives dead release paths through the repo-config model; the Forgejo side was archived on
2026-10-23 and 2026-10-24. This runbook covers the GitHub side (VIK-2320).

| Piece | Path |
| --- | --- |
| Model | `kubernetes/apps/repo-config/repo-config/model/repos.yaml`: entries keyed `webgrip/<name>` with `forge: github` |
| Module | `kubernetes/apps/repo-config/repo-config/tofu-github/` (shared with `ploeg-hq`) |
| Terraform object | `kubernetes/apps/github-config/webgrip/app/terraform.yaml`: `Terraform/webgrip` in namespace `github-config`, `vars.github_owner: webgrip`, **`suspend: true`** |
| OpenBao | policy `github-config-webgrip` (read `secret/data/github/webgrip-app`), Kubernetes role `github-config-webgrip` bound to ServiceAccount `github-config/github-config-webgrip-runner`; written by the `openbao-config` CronJob |
| Alert | `GitHubConfigWebgripNotReady` (warning, 3h) |
| Also used by | CronJob `github-config/github-mirrors`, which copies Forgejo releases to the ten tracked push mirrors with a `contents: write` token per repository ([GitHub mirrors](github-mirrors.md)); it needs **Contents: Read and write** and those ten repositories in the installation |

## What the model archives

| GitHub repository | Kind | `mirror_of` | Live on 2026-10-24 |
| --- | --- | --- | --- |
| `webgrip/application-template` | push mirror | `application-template` | not archived |
| `webgrip/backstage-application` | push mirror | `backstage-application` | **already archived** (by hand, 2026-10-23) |
| `webgrip/common-charts` | push mirror | `common-charts` | not archived |
| `webgrip/freshrss-application` | push mirror | `freshrss-application` | not archived |
| `webgrip/invoiceninja-application` | push mirror | `invoiceninja-application` | not archived |
| `webgrip/ledgerflow` | push mirror | `ledgerflow` | not archived |
| `webgrip/monitoring-platform` | push mirror | `monitoring-platform` | not archived |
| `webgrip/searxng-application` | push mirror | `searxng-application` | not archived |
| `webgrip/traefik-local-development` | push mirror | `traefik-local-development` | not archived |
| `webgrip/whisperx-application` | push mirror | `whisperx-application` | not archived |
| `webgrip/twitch_exporter` | GitHub-leading fork | none | not archived |

An archived GitHub entry is managed as `github_repository.archived`: the module writes only
`archived = true` and ignores every other attribute, so descriptions, homepages, wiki and issue
settings stay as they are. `prevent_destroy` holds every repository. The validator refuses an
archived GitHub entry that carries `rulesets` or `release_consumers` (an archived repository is
read-only), and a `mirror_of` entry whose Forgejo source is archived while the mirror is not.

## Why it is suspended

No credential in the estate may administer the `webgrip` organisation from the cluster. The
`ploeg-hq-gitops` App is installed on `ploeg-hq/ploeg` only. The Renovate App on `webgrip`
(`renovate/operator`, G8 in the [delivery-chain inventory](../general/delivery-chain-external-state.md))
must not gain Administration: whoever holds that key could then switch off the checks Renovate's
own merges depend on, the same split the [ploeg-hq Renovate App](github-app-ploeg-hq.md#the-renovate-app)
keeps. The `github/ci-pat` token is a person's classic PAT for image mirroring, not an
organisation admin credential.

Without the key the ephemeral OpenBao read fails with `Vault response was nil` and the runner
would be recreated every retry, so the object is suspended until the owner has created the App.

## Owner steps (the one UI step)

1. Open <https://github.com/organizations/webgrip/settings/apps/new>.
2. Fill in:
   - **GitHub App name:** `webgrip-gitops` (any free name works; nothing reads it)
   - **Homepage URL:** `https://github.com/webgrip`
   - **Webhook:** untick **Active**. Leave the URL empty.
   - **Repository permissions:**
     - **Administration:** Read and write (archiving a repository)
     - **Metadata:** Read-only (GitHub sets this itself)
     - every other repository permission: No access
   - **Organization permissions** and **Account permissions:** No access for all.
   - **Where can this GitHub App be installed?** Only on this account.
3. Click **Create GitHub App**. On the page that opens, note the **App ID**.
4. Scroll to **Private keys**, click **Generate a private key**. A `.pem` file downloads.
5. In the left menu click **Install App**, then **Install** next to `webgrip`. Choose
   **Only select repositories** and pick the eleven repositories in the table above. Click **Install**.
6. The browser lands on `https://github.com/organizations/webgrip/settings/installations/<number>`.
   That number is the **installation ID**.
7. Store the three values in OpenBao:

   ```bash
   mise exec -- just bao-login
   export BAO_ADDR="$(mise exec -- just bao-addr)"
   mise exec -- bao kv put secret/github/webgrip-app \
     app_id=<App ID> installation_id=<installation ID> private_key=@<path to the .pem>
   ```

8. Delete the downloaded `.pem` from your machine.

An agent can do the rest.

## After the key is stored

1. **Policy and role.** The `openbao-config` CronJob (every five minutes) writes them. Confirm:

   ```bash
   mise exec -- bao policy read github-config-webgrip
   mise exec -- bao read auth/kubernetes/role/github-config-webgrip
   ```

2. **Plan only.** Remove `suspend: true` from `kubernetes/apps/github-config/webgrip/app/terraform.yaml`
   (the object has no `approvePlan`, so it plans and waits), commit, push. Read the plan:

   ```bash
   mise exec -- kubectl -n github-config get terraform webgrip -o jsonpath='{.status.plan.pending}'
   mise exec -- kubectl -n github-config get cm tfplan-default-webgrip -o jsonpath='{.data.tfplan}'
   ```

   It must read **Plan: 11 to import, 0 to add, 10 to change, 0 to destroy**, and every change
   must be `archived = false -> true`. This was proven on 2026-10-24 with a read-only local plan
   against the live organisation. `backstage-application` imports with no change because it is
   archived already. Anything else means the model or GitHub drifted; resolve it before approving.
3. **Approve.** Set `spec.approvePlan` to the pending plan id, commit, push. After the apply,
   `gh repo view webgrip/<name> --json isArchived` reads `true` for all eleven. Then set
   `approvePlan: auto` so a hand unarchive is reverted within the hour.

## Adding a repository

An active push mirror is tracked, not managed: `webgrip/<name>` with `mirror_of` and no
`settings` imports nothing into this Terraform object
([ADR-0085](../adr/adr-0085-github-push-mirrors-are-tracked-in-the-model-and-reconciled-for-drift-and-releases.md),
procedure in [GitHub mirrors](github-mirrors.md#adding-or-retiring-a-mirror)). The steps below are
for an archived mirror, a fork, or a GitHub-leading repository. An archived entry whose repository
is not in the installation yet carries `managed: false`, which keeps it out of this Terraform
object; remove the line once the repository is added.

1. Add the entry to `repos.yaml` (`webgrip/<name>`, `forge: github`, `mirror_of` when
   it is a push mirror of a Forgejo repository).
2. Add the repository to the App installation (**Settings → GitHub Apps → webgrip-gitops →
   Configure → Repository access**). Without it the import fails with `404 Not Found`.
3. An active (not archived) repository is managed in full: its settings need `default_branch` and
   every key of `baseline`'s `github.settings`, and the App needs the same permissions as
   `ploeg-hq-gitops` (Administration, Variables) before the plan can read Actions permissions.
4. `./scripts/validate-repo-config-model.sh`, push, read the plan.

## Local verification without the App

The module accepts a personal token instead of the App key, for a read-only plan:

```bash
cp -r kubernetes/apps/repo-config/repo-config/model kubernetes/apps/repo-config/repo-config/tofu-github "$scratch"/
mise exec -- tofu -chdir="$scratch"/tofu-github init -backend=false
TF_VAR_local_verification_github_token="$(gh auth token)" \
  mise exec -- tofu -chdir="$scratch"/tofu-github plan -var github_owner=webgrip -state="$scratch"/local.tfstate
```

Never run `apply` this way: the cluster object owns the state.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| plan error `Vault response was nil` | no `secret/github/webgrip-app`, or the object was unsuspended before the key was stored | owner steps above |
| plan error `permission denied` on `auth/kubernetes/login` | role `github-config-webgrip` not written yet | wait for the `openbao-config` CronJob, check its log |
| import `404 Not Found` for one repository | the repository is not in the App installation | add it to the installation |
| apply `403 Resource not accessible by integration` | the App lacks Administration write | edit the App's permissions, accept them on the installation page |
| runner cannot reach OpenBao | ingress rule missing | `security-allow-github-config-openbao` must list `app.kubernetes.io/part-of: github-config-webgrip` |
