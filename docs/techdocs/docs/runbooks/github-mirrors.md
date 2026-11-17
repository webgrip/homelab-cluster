# GitHub mirrors: drift, release copies, and what to do when one stops

Forgejo is the source of truth. Ten repositories push-mirror to `github.com/webgrip/<name>`, and
GitHub is the cold-bootstrap and break-glass source of this cluster
([ADR-0012](../adr/adr-0012-external-bootstrap-fallback-source.md)). A push mirror copies git refs,
not Forgejo Releases. The `github-mirrors` reconciler watches every mirror the repo-config model
names, copies missing releases to GitHub
([ADR-0085](../adr/adr-0085-github-push-mirrors-are-tracked-in-the-model-and-reconciled-for-drift-and-releases.md)),
and creates each push mirror itself: an SSH push mirror whose key it registers as a GitHub deploy
key, so no person's token is involved
([ADR-0091](../adr/adr-0091-github-push-mirrors-push-with-a-deploy-key-the-reconciler-registers.md)).

| Piece | Where |
| --- | --- |
| Model | `kubernetes/apps/repo-config/repo-config/model/repos.yaml`: `webgrip/<name>` with `forge: github` and `mirror_of: <name>`, no `settings` (tracked, not managed by `tofu-github`) |
| Reconciler (CronJob every 15 minutes) | `kubernetes/apps/github-config/github-mirrors/`, namespace `github-config` |
| Code and tests | `app/github_mirrors.py`, `scripts/test_github_mirrors.py`, `scripts/test-github-mirrors.sh` (mutations, CI `e2e`) |
| Alerts and their tests | `victoria-metrics/app/rules/prometheusrule-platform-github-mirrors.yaml`, `scripts/vmalert-tests/platform-github-mirrors.test.yaml` |
| Dashboard | Grafana, folder Platform, **GitHub Mirrors / Drift** (`/d/platform-github-mirrors`) |
| GitHub credential | OpenBao `secret/github/webgrip-app` (the `webgrip-gitops` App), read with Kubernetes role `github-mirrors`; per repository one token with `contents: write` only and one with `administration: write` only (deploy keys) |
| Forgejo credential | OpenBao `secret/forgejo/repo-config` key `FORGEJO_TOKEN` (the repo-config bot) → `ExternalSecret/github-mirrors-forgejo`; reads status and creates, syncs and deletes push mirrors |
| Push credential | a deploy key with write access per GitHub repository; Forgejo holds the private key (generated per push mirror, never leaves Forgejo) |
| Mirror creation | the reconciler, from the model. `scripts/forgejo-sync.sh --only mirror` and `GH_MIRROR_TOKEN` are retired |

## What one run does

1. Reads `repos.yaml` from Forgejo `main` and takes every `webgrip/*` GitHub entry with `mirror_of`
   that is not archived.
2. For each one it reads, on Forgejo: the default-branch head, tags, releases, and the push mirror
   whose remote is `github.com/webgrip/<name>` (`last_update`, `last_error`, `interval`). On GitHub,
   with a token for that repository only, it reads the head, tags and releases.
3. With a token for that repository and `administration: write` only, it converges the push mirror:
   - No Forgejo push mirror with an SSH key: it creates one (`use_ssh`, push on commit, 8h
     fallback, remote `ssh://git@ssh.github.com:443/webgrip/<name>.git`), adds Forgejo's public
     key as a write deploy key titled `forgejo push mirror`, and triggers a sync. If GitHub refuses
     the key, it deletes the mirror it just created.
   - An SSH mirror exists: it adds the deploy key again if it is missing on GitHub.
   - The SSH mirror has pushed with no error: it deletes every other push mirror of that
     repository to GitHub (the old token mirrors).
   - It changes nothing when the App lacks `administration: write`, when the GitHub repository is
     archived, or when GitHub answers with another full name (a transferred repository).
4. It copies each release that is on Forgejo and not on GitHub, oldest first, at most 40 per run.
   A release is skipped until its tag is on GitHub, because the reconciler never creates a tag.
   A copy is created as a draft, gets every asset, and is then published with the Forgejo draft
   and prerelease flags; only Forgejo's newest stable release is marked latest. If any step fails,
   the draft it just created is deleted. Releases already on GitHub, including ones Forgejo does
   not have, are counted and never edited or deleted.
5. It lists public GitHub repositories with a Forgejo namesake, and Forgejo repositories that push
   to GitHub. Any of them that the model does not name is model drift.
6. It pushes `github_mirror_*` metrics to vmagent. The run exits 1 when it could not read a tracked
   mirror; missing credentials exit 0.

## Metrics

| Metric | Meaning |
| --- | --- |
| `github_mirror_head_match{repository}` | 1 when GitHub's default branch is at the Forgejo head |
| `github_mirror_last_update_timestamp_seconds`, `github_mirror_interval_seconds` | Forgejo's last push attempt and the mirror's fallback interval |
| `github_mirror_error` | 1 when Forgejo's push mirror has a `last_error` |
| `github_mirror_push_status_known`, `github_mirror_push_mirror_configured` | the Forgejo token could read push mirrors; a GitHub push mirror exists |
| `github_mirror_tags_missing` | Forgejo tags not on GitHub |
| `github_mirror_releases_missing_before`, `github_mirror_releases_missing` | Forgejo releases not on GitHub before and after the run's copies |
| `github_mirror_releases_extra` | GitHub releases without a Forgejo release (information only) |
| `github_mirror_releases_copied`, `github_mirror_releases_copy_failed` | copies made and refused in this run (sum over time for totals) |
| `github_mirror_app_access` | the App could issue a token for the repository |
| `github_mirror_deploy_key_access` | the App could issue an `administration: write` token for the repository |
| `github_mirror_ssh_push_mirror`, `github_mirror_token_push_mirrors` | the push mirror the metrics read has an SSH key; how many push mirrors to GitHub still use a token |
| `github_mirror_model_drift{forge,repository}`, `github_mirror_model_drift_known{forge}` | a copy outside the model; whether the check could run |
| `github_mirror_credentials_present{credential}` | `github_app` and `forgejo_token` |
| `github_mirror_reconciler_last_success_timestamp_seconds` | last run that read every mirror |

The job pushes every 15 minutes, so every alert and panel reads these with `last_over_time(...[1h])`.

## Owner steps (once)

1. **App permission.** On <https://github.com/organizations/webgrip/settings/apps>, open
   `webgrip-gitops`, then **Permissions & events → Repository permissions → Contents: Read and
   write** and **Administration: Read and write** (deploy keys), and **Save changes**. Then accept the new permission on
   <https://github.com/organizations/webgrip/settings/installations> (the installation shows a
   **Review request** banner).
2. **Installation.** In the same installation's **Repository access**, add the ten mirrors:
   `action-typescript-template`, `ai-skills`, `homelab-cluster`, `infrastructure`,
   `renovate-config`, `telemetry-service`, `twente.dev`, `unfold`, `unfold-cluster`, `workflows`.
3. Nothing else: the App key is already at `secret/github/webgrip-app`, the `openbao-config`
   CronJob writes policy and role `github-mirrors`, and the repo-config bot token is already in
   OpenBao. Check:

   ```bash
   mise exec -- bao policy read github-mirrors
   mise exec -- bao read auth/kubernetes/role/github-mirrors
   mise exec -- kubectl -n github-config get externalsecret github-mirrors-forgejo
   mise exec -- kubectl -n github-config create job --from=cronjob/github-mirrors github-mirrors-manual
   ```

A repository missing from the installation shows as `GitHubMirrorAppAccessMissing`; a missing
Administration permission shows as `GitHubMirrorDeployKeyAccessMissing`. The run still checks the
others. If the organisation or its enterprise disables deploy keys, GitHub refuses the key and the
log names the status; enable deploy keys in the organisation settings.

## Alerts

### GitHubMirrorStale

GitHub's head differs from Forgejo's for 30 minutes, or Forgejo has not pushed for longer than the
mirror's interval (8h) plus an hour.

1. On the dashboard, read **Mirror error** and **Since last mirror sync** for the repository.
2. In Forgejo, **Settings → Repository → Mirror settings** of `webgrip/<name>`: read the error and
   press **Synchronize now**.
3. If the error says `Invalid username or token` or authentication failed, the mirror is an old
   token mirror (`github_mirror_token_push_mirrors` above 0). The reconciler replaces it once it
   may manage deploy keys: check `GitHubMirrorDeployKeyAccessMissing`, then run it now:

   ```bash
   mise exec -- kubectl -n github-config create job --from=cronjob/github-mirrors github-mirrors-manual
   ```

   It creates the SSH mirror and pushes; the run after the first clean push deletes the token
   mirror. No token is needed.
4. If the error says `Permission denied (publickey)`, the deploy key is missing on GitHub. The next
   run adds it again; run the job now to skip the wait.
5. If the error names a host key, GitHub's SSH host key changed or the first connection was not to
   GitHub. Compare with <https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints>
   and remove the `ssh.github.com` lines from `known_hosts` under Forgejo's SSH root only when
   GitHub announced the change.
6. If GitHub push protection rejected a commit, rotate the leaked secret before unblocking the push
   on GitHub (ADR-0012, 2026-10-04).
7. If GitHub's branch moved on its own (a commit or force-push on GitHub), Forgejo wins: the next
   mirror push overwrites it.

### GitHubMirrorError

Forgejo's push mirror has a `last_error`. Same steps as above; the error text names the cause.

### GitHubMirrorDeployKeyAccessMissing

GitHub refused an `administration: write` token for one repository, so the reconciler cannot
create its SSH mirror or register the deploy key. Grant **Administration: Read and write** to the
App and accept it on the installation (owner step 1). Until then the repository pushes with
whatever credential its mirror already has.

### GitHubReleasesNotMirrored

Forgejo releases are still missing on GitHub after two hours of runs.

- **Tags missing** above zero: the tag has not reached GitHub. Fix the mirror first; the release
  follows on the next run.
- **Copy failed** above zero: the job log names the release and GitHub's status. 422 usually means
  the body is longer than GitHub accepts or an asset name collides. 403 means the App lost Contents
  write. Copy that release by hand with `gh release create` from a checkout, or fix the cause.
- The first backfill (about 400 releases) takes about three hours at 40 per run; the alert can fire
  once during it.

```bash
mise exec -- kubectl -n github-config logs job/$(mise exec -- kubectl -n github-config get jobs -l app.kubernetes.io/name=github-mirrors --sort-by=.status.startTime -o name | tail -1 | cut -d/ -f2)
```

### MirrorModelDrift (info)

A GitHub copy exists that the model does not list. Either add it to `repos.yaml` (a tracked
mirror, or `settings.archived: true` for an archived one; the Forgejo source must be in the model),
or archive or delete the GitHub copy.

Adding an archived entry imports it into `Terraform/webgrip`, so the repository must be in the
`webgrip-gitops` installation first, or that plan fails with `404 Not Found`. Until it is, give the
entry `managed: false`: the model lists it (so it is no drift) and `tofu-github` leaves it alone.
The validator accepts `managed: false` only on an archived entry.

On 2026-10-27 the four copies this listed were modelled that way: `discord-moon`,
`techdocs-builder` and `techdocs-runner` (archived on both forges; Forgejo source entries archived,
GitHub entries archived with `mirror_of`), and `webgrip.nl` (archived on GitHub with an older
history than Forgejo, so an archived GitHub entry without `mirror_of`: not a mirror, no head check,
no release copies). Once the owner adds those four to the installation, delete their
`managed: false` lines; the next `Terraform/webgrip` plan then reads 4 to import and no change,
because all four are already archived on GitHub.

### GitHubMirrorAppAccessMissing

GitHub refused a `contents: write` token for one repository: add it to the installation (owner
step 2) or accept the pending Contents permission (owner step 1).

### GitHubMirrorStatusUnknown (info)

- `credential="github_app"`: `secret/github/webgrip-app` is missing; see
  [the webgrip GitHub App](github-app-webgrip.md).
- `credential="forgejo_token"`: `ExternalSecret/github-mirrors-forgejo` has not synced.
- No credential label: the token exists but `GET /repos/webgrip/<name>/push_mirrors` was refused.
  That endpoint needs repository admin. The repo-config bot is admin through team `repo-config`
  (`forgejo-actions-secrets/app/repo-config-provisioner.job.yaml`), so check its team membership.

### GitHubMirrorReconcilerFailing, GitHubMirrorReconcilerStale

The job could not read a tracked mirror, or has not succeeded for two hours. The log names the
repository and call. Usual causes: a modelled repository was renamed or deleted on one forge, the
OpenBao role is missing, or egress to `api.github.com`, `uploads.github.com` or `forgejo-http` is
blocked (`app/networkpolicy.yaml`, `forgejo/networkpolicy.yaml`, `security/netpol`).

## Adding or retiring a mirror

1. Create the empty GitHub repository `webgrip/<name>` and add it to the `webgrip-gitops`
   installation.
2. Add `webgrip/<name>: {forge: github, mirror_of: <name>}` to `repos.yaml`.
   Leave out `settings`, `kind` and `renovate`; the validator refuses them on an active mirror.
3. Nothing else: the next reconciler run after the merge creates the SSH push mirror, registers its
   deploy key and pushes.
4. Retiring: set `settings.archived: true` on both the Forgejo source and the GitHub entry
   (ADR-0078 R4). `Terraform/webgrip` then archives the GitHub copy, and the reconciler stops
   tracking it. Delete the Forgejo push mirror by hand; the reconciler never deletes the last one.
5. Before a GitHub repository is transferred to another owner, delete its Forgejo push mirror: the
   deploy key moves with the repository and the mirror would follow GitHub's redirect. The
   reconciler refuses to touch a mirror whose GitHub repository answers with another name.
