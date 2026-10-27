# The wellhead-dev Renovate GitHub App

Renovate keeps the dependencies of `wellhead-dev/wellhead` current through its own GitHub App,
`wellhead-dev-renovate`, installed on that repository only. The cluster side is a copy of the
ploeg-hq Renovate path ([github-app-ploeg-hq](github-app-ploeg-hq.md#the-renovate-app)) with other
names; the token minter runs the same script.

| What | Where | Behaviour |
| --- | --- | --- |
| App | [settings](https://github.com/organizations/wellhead-dev/settings/apps/wellhead-dev-renovate), App ID `5500760`, installation `175945578` on `wellhead-dev/wellhead` | Contents, Pull requests, Issues, Workflows: read and write. Checks, Commit statuses, Dependabot alerts, Metadata: read. Nothing else. No webhook |
| Key | OpenBao `secret/github/wellhead-dev-renovate-app` (`app_id`, `installation_id`, `private_key`) | read by the minter over Kubernetes auth, role `renovate-github-app-token-wellhead-dev` |
| Token minter | `kubernetes/apps/renovate/renovate-operator/jobs/github-app-token-wellhead-dev.cronjob.yaml` | CronJob at :09 and :39; mints an installation token for `wellhead` with the permissions above and writes Secret `renovate/renovate-wellhead-dev-token`. Without credentials it logs `app credentials absent` and exits 0 |
| RenovateJob | `kubernetes/apps/renovate/renovate-operator/jobs/wellhead-dev.yaml` | every 10 minutes, platform `github`, discovery filter `wellhead-dev/wellhead`; reads the token Secret as optional |
| Global config | `kubernetes/apps/renovate/renovate-operator/jobs/configmap-wellhead-dev.yaml` | `requireConfig: required`, `onboarding: false`, `platformCommit: enabled`, no `allowedCommands` |

Until the token Secret exists, `GitHubAppWellheadDevRenovatePending` (info, no receiver) stays
listed.

## Store the key

```bash
mise exec -- just bao-login
export BAO_ADDR="$(mise exec -- just bao-addr)"
mise exec -- bao kv put secret/github/wellhead-dev-renovate-app \
  app_id=5500760 installation_id=175945578 private_key=@<path to the .pem>
```

Delete the `.pem` afterwards.

## First run

```bash
mise exec -- kubectl -n renovate create job --from=cronjob/renovate-github-app-token-wellhead-dev renovate-github-app-token-wellhead-dev-first
mise exec -- kubectl -n renovate logs job/renovate-github-app-token-wellhead-dev-first
```

Expect `installation token for wellhead written to Secret renovate/renovate-wellhead-dev-token`. A
`(422)` reading `The permissions requested are not granted` means the App lacks a permission
listed above: add it on the App's page and accept it on the installation page.

## Rotate the key

1. On the App's settings page, **Generate a private key**.
2. `mise exec -- bao kv patch secret/github/wellhead-dev-renovate-app private_key=@<new .pem>`
3. Run the first-run job above and check it succeeds.
4. Delete the old key on the App's page and the `.pem` from your machine.
