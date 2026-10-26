# Signed commits on the GitOps repositories

`main` of homelab-cluster and unfold-cluster is what the clusters run. Flux applies a revision only when its HEAD carries a signature from a trusted key, and Forgejo accepts on `main` only commits signed by a key it has verified. A leaked token, a compromised bot or a stray push then cannot change a cluster.

unfold-cluster already verifies HEAD in Flux (`kubernetes/clusters/main/flux-system/trusted-signers/`). homelab-cluster follows the same shape.

## Who writes to `main`, and how each signs

| Writer | How the commit reaches `main` | Signature |
| --- | --- | --- |
| Forgejo itself | the merge, squash or rebase-merge commit when a pull request is merged | the server key (`forgejo-signing-key`, an ESO-generated ed25519 key; `[repository.signing] MERGES = always`), public part at `https://forgejo.webgrip.dev/api/v1/signing-key.ssh` |
| People | their commits inside a pull request; never a direct push once `main` takes no pushes | their own SSH signing key, uploaded and verified on their Forgejo account |
| Renovate (`webgrip-forgejo` job) | its commits inside a pull request; automerge is `pr`, never `branch` | `renovate-signing-key`, an ESO-generated ed25519 key passed as `RENOVATE_GIT_PRIVATE_KEY` |
| Release bots | none: releases are tags only and push nothing to `main` | not needed |
| Agents and the agentstd adoption job | pull requests only (ADR-0048) | their commits stay unsigned, so `require_signed_commits` blocks their pull requests until each bot has a verified key |

Forgejo signs merge commits for the `merge`, `squash` and `rebase-merge` styles. It does not sign the commits a `rebase` or `fast-forward-only` merge puts on `main`, so both styles stay off on these repositories.

Because nothing but a Forgejo merge reaches `main`, HEAD is always a commit signed by the server key. The Flux trusted-signers Secret therefore needs the server key; the owner's key is in it for a break-glass push.

## Rollout order

Each step is safe on its own; do not skip ahead.

1. Flux 2.9 or later on the cluster. SSH signature verification arrived in source-controller 1.9.0 (Flux 2.9.0). homelab-cluster moves from the 2.8 distribution to 2.9.6 with `flux-operator-manifests` v0.61.0.
2. Renovate signs. The `renovate-signing-key` ExternalSecret generates the key; verify the bot's key on Forgejo (below). Branch automerge is replaced by pull request automerge, so Renovate never pushes to `main`.
3. `main` takes no direct pushes and allows only the `merge`, `squash` and `rebase-merge` styles (repo-config). From here every new HEAD is signed by the server.
4. Check that the current HEAD verifies before Flux depends on it: `curl -s https://forgejo.webgrip.dev/api/v1/repos/webgrip/homelab-cluster/commits/main | jq '.commit.verification | {verified, reason}'` must show `verified: true` with the reason `Forgejo webgrip / SHA256:…`. The commit page shows the same green badge.
5. Flux verifies HEAD (`spec.verify` on the `flux-system` GitRepository, patched in through the FluxInstance). Check `kubectl -n flux-system get gitrepository flux-system -o jsonpath='{.status.conditions[?(@.type=="SourceVerified")]}'` reports `Succeeded`.
6. Every person and bot that commits inside pull requests has a verified signing key on Forgejo. Only then does repo-config set `require_signed_commits: true` on `main`; before that it would block every pull request with an unsigned commit.

A HEAD that fails verification stops Flux on the last verified revision and sets `SourceVerified` to `False`; nothing half-applies. Recover by merging a pull request (the server signs it) or, as owner, pushing a signed commit while protection is lifted.

## Verify the Renovate bot's key on Forgejo

Forgejo trusts an SSH signing key only once its owner proves possession, and that proof exists only in the web settings, not in the API. Once per key:

1. Read the public key: `kubectl -n renovate get secret renovate-signing-key -o jsonpath='{.data.key\.pub}' | base64 -d`.
2. Sign in to Forgejo as `renovate` (its password is the `renovate-forgejo-bot-password` value in OpenBao), add the key under Settings, SSH / GPG keys, and choose Verify.
3. Sign the token Forgejo shows with the command it shows, run inside a throwaway pod in the `renovate` namespace that mounts the `renovate-signing-key` Secret, so the private key never reaches a laptop. Paste the signature back and choose Verify.

The key is generated once (`refreshInterval: "0"`); rotating it means deleting the Secret and repeating these steps.

## Set up signing as a developer

Once per machine, with the SSH key you already push with or a dedicated one:

```sh
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

Add the same public key on Forgejo under Settings, SSH / GPG keys, and choose Verify; Forgejo shows the token and the `ssh-keygen -Y sign` command. The commit email must be one of your verified Forgejo emails, or the signature shows as unverified.

`git log --show-signature -1` shows the signature locally; the commit page on Forgejo shows whether Forgejo trusts it.
