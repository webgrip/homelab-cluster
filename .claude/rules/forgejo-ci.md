---
paths:
  - ".forgejo/**"
---

# Forgejo Actions

- Reference a reusable workflow in shorthand, pinned to a SHA: `uses: webgrip/workflows/.forgejo/workflows/<name>.yml@<sha> # vX.Y.Z`. A full `https://` URL leaves the job waiting forever for runner labels.
- An `if:` on a `uses:` job does nothing: Forgejo v15 flattens the called jobs and drops it. Gate inside the reusable workflow (`only-refs`, `enabled`) or give the calling job its own `runs-on`.
- Use `runs-on: docker`, the `Europe/Amsterdam` timezone (cron schedules too) and `@webgrip/semantic-release-config` for releases.
- Check that a GitHub Marketplace action works on forgejo-runner before proposing it ([Forgejo CI](https://forgejo.webgrip.dev/webgrip/agent-standards/src/branch/main/docs/forgejo-ci.md)).
