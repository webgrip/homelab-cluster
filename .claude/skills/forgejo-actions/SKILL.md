---
name: forgejo-actions
description: Forgejo Actions engine quirks that differ from GitHub Actions — reusable-workflow expansion/racing builds, data.forgejo.org action-resolution 404s, workflow_dispatch context gotchas, semantic-release tag handling. Use when authoring or debugging a .forgejo/ workflow.
when_to_use: Use when authoring/debugging a .forgejo workflow, a duplicate/racing build, `uses:` 404 `remote: Not found`, empty `github.sha`/`github.repository_owner`, a release that didn't trigger the build, or a semantic-release version double-prefix. NOT repo cutover (forgejo-leading) nor runner pod/KEDA infra (forgejo-runner runbook).
---

# Forgejo Actions engine — GitHub-Actions divergences

Decision-first gotchas below; the full reference (snippets, the resolution table, the precedence
lever) is **[docs/techdocs/docs/general/forgejo-actions-engine.md](../../../docs/techdocs/docs/general/forgejo-actions-engine.md)** — single source of truth, don't restate it here.

Runner label is **`docker`**. Direct-step jobs pin `runs-on: docker`; pure-`uses:` orchestrator jobs omit it.

## Gotchas (decision-first)

- **Duplicate/racing build?** Reusable-workflow expansion flattens inner jobs into the caller graph
  **only when the caller job OMITS `runs-on`** — and then the caller's `if:` does NOT gate them, so two
  mutually-exclusive `if:`-gated calls both build (same tag + buildx `:cache`). Fix: (a) keep `runs-on`
  on the caller (suppresses expansion), or (b) one call, push the condition into `inputs`.
- **`the workflow must contain at least one job without dependencies`** (and you have no real cycle)?
  Under active expansion the caller job id collides with an inner job id — **rename the caller**.
- **`uses:` → `remote: Not found` / 404?** Step-level composite-actions resolve against
  `DEFAULT_ACTIONS_URL` = `data.forgejo.org` (incomplete mirror; 404s `actions/github-script`,
  `sigstore/cosign-installer`, `anchore/sbom-action`, all `webgrip/*`). Pin those to absolute URLs
  (`https://github.com/...` or `https://forgejo.${SECRET_DOMAIN}/...`). Job-level reusables resolve
  locally and are fine. (`DEFAULT_ACTIONS_URL` is intentionally unset here — don't flip it globally.)
- **Disable a repo's Actions:** add an **empty `.forgejo/workflows`** dir — first-existing of
  `.forgejo`/`.gitea`/`.github` wins.
- **A file stopped running on push/PR?** `workflow_call.secrets` is rejected by the parser; on a
  mixed-trigger file it suppresses push/PR too (forgejo#6069). Drop it; pass secrets from the calling job.
- **Empty `github.sha` / `github.repository_owner`?** Both can be empty on `workflow_dispatch`
  (`github.repository` is fine) → hardcode `webgrip` in derived image/cache refs.
- **Release didn't trigger the build?** A CI-created release fires no release event — dispatch the
  build explicitly; every `workflow_dispatch` input needs `type: string`.
- **semantic-release version double-prefix** (`techdocs-builder-vtechdocs-builder-v...`)?
  `semantic-release-monorepo` `outputs.version` is already the full namespaced tag — pass verbatim,
  never re-prefix.

## Not this skill

- GitHub→Forgejo repo cutover (un-mirror, remotes, push-mirror, branch protection) → `forgejo-leading`.
- Runner KEDA ScaledJob / DinD / pod sizing → [Forgejo runner runbook](../../../docs/techdocs/docs/runbooks/forgejo-runner.md).
