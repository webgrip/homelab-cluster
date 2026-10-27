---
status: accepted
date: 2026-10-27
decision-makers: Ryan Grippeling
---

# GitHub push mirrors are tracked in the model, watched for drift, and get their releases copied

## Context and Problem Statement

Forgejo is the source of truth ([ADR-0011](adr-0011-flux-source-forgejo.md)). Ten active repositories push-mirror to `github.com/webgrip/<name>`, and GitHub is the cold-bootstrap and break-glass source of this cluster ([ADR-0012](adr-0012-external-bootstrap-fallback-source.md)). The mirrors were created by hand with `scripts/forgejo-sync.sh --only mirror` and a person's `GH_MIRROR_TOKEN` (rows G10 and F7 of the [delivery-chain inventory](../general/delivery-chain-external-state.md)). They were not in the repo-config model, and nothing alerted when they stopped: every mirror was silent from 2026-07-25 to 2026-10-04. The staleness alerting ADR-0012 requires was never built (VIK-227).

A push mirror copies git refs, not Forgejo Release objects. On 2026-10-27 `webgrip/renovate-config` had the same `main` (9163c948) and the same 43 tags on both forges, but GitHub's Releases stopped at v1.4.4 while Forgejo had releases up to v1.18.0. `ai-skills` (134), `workflows` (59) and `twente.dev` (62) had no GitHub releases at all.

How do the mirrors get into the model, how do we find out that one stopped or that a copy exists outside the model, and how do releases reach GitHub, without letting tofu rewrite the settings of the GitHub repositories?

## Decision Drivers

* A stopped mirror alerts within the hour, so the July silence cannot happen again.
* The model lists every GitHub copy, and a copy outside the model shows up.
* GitHub releases follow Forgejo. Nothing deletes or changes an existing GitHub release: GitHub has releases Forgejo lacks (`telemetry-service` has 13 there and 3 on Forgejo), and `unfold` already copies its own releases from CI.
* Adding a mirror to the model must not change it on GitHub. `tofu-github` writes the full baseline profile to every active entry (wiki, projects, merge methods, Actions enabled for all actions). That would enable wiki and projects on `renovate-config` and possibly start the GitHub Actions workflows in `webgrip/workflows`.

## Considered Options

* Mirrors are tracked in the model, not managed; one reconciler CronJob checks them, copies missing releases and exports metrics
* Mirrors are fully managed by `tofu-github`, with each repository's live settings written into the model first
* A Forgejo Actions workflow in each repository that copies its release to GitHub on publish

## Decision Outcome

Chosen option: "Mirrors are tracked in the model, not managed", because it puts all ten mirrors in the model and under alerts in one change with no effect on GitHub settings, and one small service covers every repository without each one carrying a workflow.

1. **Model.** An active mirror is `webgrip/<name>: {forge: github, profile: baseline, mirror_of: <name>}`, without `settings`, `rulesets`, `release_consumers`, `kind` or `renovate`. `tofu-github` leaves a non-archived entry with `mirror_of` out of `active_repos`, so it imports and manages nothing for it. An archived mirror keeps `settings.archived: true` and stays managed as before ([ADR-0078](adr-0078-one-release-recipe-four-kinds.md) R4). `scripts/validate-repo-config-model.sh` refuses `settings`, `rulesets` or `release_consumers` on an active mirror.
2. **Reconciler.** CronJob `github-config/github-mirrors` runs every 15 minutes (`kubernetes/apps/github-config/github-mirrors`, stdlib Python like the [GitHub secrets bridge](../runbooks/secrets-level-3-bridge.md)). It reads the model from Forgejo `main`, and for each tracked mirror it compares the default-branch head, tags and releases on both forges and reads Forgejo's push-mirror status (`last_update`, `last_error`, `interval`). It also lists public GitHub repositories and Forgejo push mirrors that the model does not name.
3. **Release copies.** A release that is on Forgejo, not on GitHub, and whose tag is already on GitHub is created on GitHub, oldest first, at most 40 per run. The copy keeps the name, body, prerelease and draft flags, and all assets. It is created as a draft, gets its assets, and is then published; `make_latest` is true only for Forgejo's newest stable release. If any step fails, the reconciler deletes only the draft it just created. It never edits or deletes a release it did not create in the same run, and it never creates a tag.
4. **Credentials.** The `webgrip-gitops` App, with Contents read and write and installed on the ten mirrors, issues one token per repository with only `contents: write` (OpenBao `github/webgrip-app`, role `github-mirrors`). Push-mirror status is read with the existing repo-config bot token (`forgejo/repo-config`, ExternalSecret `github-mirrors-forgejo`). Without the App key the run exits 0 and reports `credentials_present 0`. Without a working Forgejo token, mirror status is reported as unknown.
5. **Signals.** `github_mirror_*` metrics go to vmagent. The alerts `GitHubMirrorStale`, `GitHubMirrorError`, `GitHubReleasesNotMirrored`, `MirrorModelDrift`, `GitHubMirrorAppAccessMissing`, `GitHubMirrorStatusUnknown`, `GitHubMirrorReconcilerFailing` and `GitHubMirrorReconcilerStale` are in `prometheusrule-platform-github-mirrors.yaml`. The dashboard is *GitHub Mirrors / Drift* (`platform-github-mirrors`, folder Platform), with the repo-config tofu Ready signal beside the mirror table.

### Consequences

* Good, because a mirror that stops shows as a head mismatch within 30 minutes, and a mirror that errors, or does not sync within its interval plus an hour, alerts even when its branch is quiet.
* Good, because the model lists every GitHub copy, and copies outside it raise `MirrorModelDrift` (info). On 2026-10-27 those were `discord-moon`, `techdocs-builder`, `techdocs-runner` and `webgrip.nl`, all archived on GitHub. Their Forgejo sources are not in the model, and `webgrip.nl` on GitHub has diverged from Forgejo, so they are left out on purpose.
* Good, because GitHub releases catch up without touching what is already there, and `unfold`'s own CI copies count as present.
* Bad, because the settings of the GitHub mirror repositories (wiki, issues, Actions) stay unmanaged.
* Bad, because the reconciler reuses the repo-config bot token, which holds `write:organization` and `write:repository` and is a repository admin. Reading push mirrors needs repository admin, so a read-only token would need its own bot user. The token never leaves the job, and the job only issues GET requests to Forgejo.
* Bad, because the stale-sync threshold is the mirror's interval plus one hour, not a flat hour. Mirrors push on commit with an 8-hour fallback, so a flat hour would page for every quiet repository.
* Neutral: stdlib Python cannot import code shared with the bridge, so the GitHub App JWT code is copied from `github_secrets_bridge.py`.
* Neutral: the first backfill (about 400 releases across `ai-skills`, `workflows`, `twente.dev`, `infrastructure`, `unfold` and `renovate-config`) takes about three hours at 40 per run, and `GitHubReleasesNotMirrored` may fire once during it.

### Confirmation

* `scripts/test-github-mirrors.sh` (e2e) runs the reconciler against a fake Forgejo, GitHub and OpenBao, and kills 18 mutations, including treating a missing release as present, copying an existing release again, deleting a pre-existing release when cleanup fails, creating a release before its tag exists, dropping a metric, and an unscoped token.
* `scripts/test-validate-repo-config-model.sh` passes a tracked mirror and fails one that carries settings or `release_consumers`.
* `scripts/vmalert-tests/platform-github-mirrors.test.yaml` fires and clears each alert.
* `tofu console` on `tofu-github` before and after the model change gives the same `active_repos`, `archived_repos`, `rulesets` and `release_consumers` for both `webgrip` and `ploeg-hq`, so the plans do not change.
* Live: `github_mirror_head_match` is 1 for all ten mirrors, and `github_mirror_releases_missing` reaches 0 except for releases whose tag is missing on GitHub.

## More Information

* Amends [ADR-0012](adr-0012-external-bootstrap-fallback-source.md) by building the staleness alerting it requires.
* Runbook: [GitHub mirrors](../runbooks/github-mirrors.md). App setup: [the webgrip GitHub App](../runbooks/github-app-webgrip.md).
* **Follow-up, out of scope here:** create the push mirrors from the model instead of by hand. That means a tofu `restapi` resource for Forgejo `push_mirrors`, using SSH push mirrors with a deploy key per repository that `tofu-github` manages on the GitHub side. It replaces `GH_MIRROR_TOKEN` (G10) and `forgejo-sync.sh --only mirror` (F7), and removes the person's token that broke every mirror on 2026-07-25.
* 2026-10-27 — decided by Ryan Grippeling: tracked, not managed; releases copied, never changed or deleted; the App gets Contents read and write on the ten mirrors.
* 2026-10-27 — the four copies left out above are modelled after all (owner): `discord-moon`, `techdocs-builder` and `techdocs-runner` as archived Forgejo sources with archived GitHub mirrors, and `webgrip.nl` as an archived GitHub entry without `mirror_of`. They are not in the `webgrip-gitops` installation yet, so their GitHub entries carry `managed: false`, a new model field that keeps an archived entry out of `tofu-github` until the installation covers it ([runbook](../runbooks/github-mirrors.md#mirrormodeldrift-info)).
