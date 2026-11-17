---
status: proposed
date: 2026-11-17
decision-makers: Ryan Grippeling
---

# GitHub push mirrors push over SSH with a deploy key the reconciler registers

## Context and Problem Statement

Forgejo pushes every modelled repository to `github.com/webgrip/<name>` with a native push mirror ([ADR-0085](adr-0085-github-push-mirrors-are-tracked-in-the-model-and-reconciled-for-drift-and-releases.md)). Each mirror was created by `scripts/forgejo-sync.sh --only mirror` with a person's classic GitHub token, `GH_MIRROR_TOKEN` (rows G10 and F7 of the [delivery-chain inventory](../general/delivery-chain-external-state.md)). When that token stops working, every mirror stops. It happened on 2026-07-25 (found 2026-10-04, [ADR-0012](adr-0012-external-bootstrap-fallback-source.md)) and again on 2026-11-17: the `unfold-cluster` and `infrastructure` mirrors failed with `Invalid username or token`. The cluster that deploys from the GitHub copy of `unfold-cluster` stopped deploying until the owner moved GitHub `main` forward by hand.

How do the mirrors keep pushing without any person's token, within about a minute of a Forgejo push, and without a step a person has to repeat?

## Decision Drivers

* No person's token, and no credential that expires.
* A push reaches GitHub within about a minute, because a cluster deploys from the GitHub copy.
* Few moving parts: reuse what already runs (Forgejo push mirrors, the `github-mirrors` CronJob, the `webgrip-gitops` App).
* No human step per repository. A one-time permission grant on the App is acceptable.
* A failed change never leaves a repository with no working mirror.

## Considered Options

* Forgejo SSH push mirrors with a write deploy key per repository; the reconciler creates the mirror and registers its key with the App
* The reconciler pushes refs itself with a per-repository App installation token, replacing Forgejo's push mirrors
* The reconciler keeps HTTPS push mirrors and rewrites their password with a fresh installation token

## Decision Outcome

Chosen option: "Forgejo SSH push mirrors with a write deploy key per repository", because it is the only option that keeps Forgejo's push on every commit (seconds, not a polling interval), has no credential that expires, and adds one step to a reconciler that already runs, without a new image, service or webhook.

1. **Mirror.** For every tracked mirror (`webgrip/<name>` with `mirror_of`, not archived), CronJob `github-config/github-mirrors` makes sure Forgejo has a push mirror with an SSH key. If none exists, it calls `POST /repos/webgrip/<source>/push_mirrors` with `use_ssh: true`, `sync_on_commit: true`, interval `8h0m0s` and remote `ssh://git@ssh.github.com:443/webgrip/<name>.git`. Forgejo generates an Ed25519 key pair, keeps the private key encrypted in its database, and returns the public key. Port 443 avoids depending on outbound port 22.
2. **Deploy key.** With an installation token scoped to that one repository and `administration: write` only, the reconciler adds the public key as a deploy key with write access (title `forgejo push mirror`). If GitHub refuses, the reconciler deletes the push mirror it just created. On every run it registers the key again if someone removed it on GitHub. Then it triggers `push_mirrors-sync`.
3. **Retiring the token mirror.** The old HTTPS mirror stays until the SSH mirror has pushed with no error (`last_update` set, `last_error` empty). The next run, at most 15 minutes later, deletes every other push mirror of that repository to GitHub. Until then both push.
4. **Guards.** Nothing changes when the App lacks `administration: write` (metric `github_mirror_deploy_key_access 0`, alert `GitHubMirrorDeployKeyAccessMissing`), when the GitHub repository is archived, or when GitHub answers `webgrip/<name>` with another full name (a transferred repository: a mirror would follow the redirect, see the [unfold-hq runbook](../runbooks/github-app-unfold-hq.md)).
5. **Creation by hand is retired.** `forgejo-sync.sh --only mirror` refuses to run. A new mirror is a model entry plus the repository in the App installation. `GH_MIRROR_TOKEN` (G10) has no use left.

### Consequences

* Good, because no mirror depends on a person or on an expiring credential. A deploy key is valid until someone deletes it, and the reconciler adds it again within 15 minutes.
* Good, because Forgejo still pushes on every commit, so a cluster that deploys from GitHub sees a merge within seconds, as before.
* Good, because the existing signals still apply: `GitHubMirrorError` and `GitHubMirrorStale` read the SSH mirror once it exists, and `github_mirror_token_push_mirrors` shows the token mirrors not yet retired.
* Good, because a deploy key with write access may change `.github/workflows` (GitHub: "Deploy keys with write access can perform the same actions as an organization member with admin access"), so the `workflow` scope that a token needed for `webgrip/workflows` is no longer needed.
* Bad, because the App gains Administration read and write on the mirrors, which also covers repository settings and deletion. The reconciler requests it only in a token scoped to one repository and the one permission, and only calls the deploy-key endpoints and a repository read with it.
* Bad, because the reconciler now writes to Forgejo (create, delete and sync push mirrors) with the repo-config bot token. [ADR-0085](adr-0085-github-push-mirrors-are-tracked-in-the-model-and-reconciled-for-drift-and-releases.md) recorded that it only read.
* Bad, because Forgejo trusts GitHub's SSH host key on first use (`StrictHostKeyChecking=accept-new`, `known_hosts` under Forgejo's SSH root). A spoofed first connection could receive a push of public code, but could not write to GitHub.
* Neutral: a push mirror over SSH does not push LFS objects. On 2026-11-17 no tracked repository had a root `.gitattributes` with `filter=lfs` that Forgejo serves anonymously; only `homelab-cluster` has a root `.gitattributes` at all.

### Confirmation

* `scripts/test-github-mirrors.sh` (CI `e2e`) runs the reconciler against a fake Forgejo, GitHub and OpenBao and kills mutations including: the token mirror deleted before the SSH mirror pushed or while it fails, the key added read-only, the mirror created without `sync_on_commit`, a refused key leaving the new mirror behind, a mirror changed without deploy-key access, a token not scoped to one permission, and a mirror created for a transferred repository.
* `scripts/test-forgejo-sync-skips-private.sh` checks that `--only mirror` refuses before calling the Forgejo API.
* `scripts/vmalert-tests/platform-github-mirrors.test.yaml` fires `GitHubMirrorDeployKeyAccessMissing` after an hour and keeps it quiet when access is present.
* Live, after the owner grants the permission: `github_mirror_ssh_push_mirror` is 1 and `github_mirror_token_push_mirrors` is 0 for every tracked mirror, `github_mirror_error` is 0, and each GitHub mirror lists one `forgejo push mirror` deploy key.

## Pros and Cons of the Options

### Forgejo SSH push mirrors with a write deploy key per repository

* Good, because it uses Forgejo's own push on commit and an existing CronJob.
* Good, because the key never leaves Forgejo; the reconciler only handles the public half.
* Bad, because the App needs Administration write, a broad permission.

### The reconciler pushes refs itself with an installation token

* Good, because the App's per-repository token already exists and needs only Contents write (plus Workflows write for `.github/workflows`).
* Bad, because it needs `git` in the job (a new image), a full clone or cache per repository, and either a webhook receiver or a CronJob every minute to reach the one-minute target. It also re-implements what Forgejo's mirror already does (force, prune, tags).

### The reconciler rewrites HTTPS mirror passwords with fresh installation tokens

* Good, because no new permission beyond Contents (and Workflows) write.
* Bad, because Forgejo's API cannot update a push mirror (only create, read, delete and sync, checked against the Forgejo 15 API), so every renewal is a delete and create. Installation tokens last one hour, so a reconciler delay or a missed run leaves pushes on commit failing with an expired token.

## More Information

* Amends [ADR-0085](adr-0085-github-push-mirrors-are-tracked-in-the-model-and-reconciled-for-drift-and-releases.md): item 4 (credentials) gains the Administration token and Forgejo writes, and its follow-up (mirrors created from the model) is done here by the reconciler instead of a tofu `restapi` resource.
* Replaces rows G10 and F7 of the [delivery-chain inventory](../general/delivery-chain-external-state.md).
* Runbook: [GitHub mirrors](../runbooks/github-mirrors.md).
* 2026-11-17 — proposed after the `unfold-cluster` and `infrastructure` mirrors failed with `Invalid username or token`. The owner set the goal: no personal tokens, developer experience first.
