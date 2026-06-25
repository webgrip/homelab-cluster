# ADR-0035: The action-clone wall — measure first; no offline mode exists

> Status: **Accepted** · Date: 2026-06-25 · Part of [RFC: CI pipeline performance](../rfc/rfc-ci-pipeline-performance.md)

## Context

Each CI job runs in a fresh ephemeral runner pod ([ADR-0008](adr-0008-rootless-ci-image-builds.md)),
so the act action cache at `/home/runner/.cache/act` is empty every run and every action
(`actions/checkout`, the `docker/*` set, `actions/github-script`) is `git clone`'d from
`data.forgejo.org` / `github.com` before any real work.

The original plan (this RFC's first draft) was "pre-bake the actions into the runner image + enable
runner **offline mode** so they're never re-fetched." **Verification against the exact image
(`code.forgejo.org/forgejo/runner:12.10.2`) disproved the load-bearing assumption:**

- `generate-config` → the `cache:` block is **only** the `actions/cache` server (`ACTIONS_CACHE_URL`),
  not the action-repo cache.
- `one-job --help` (the daemon path) → exposes only `--url/--uuid/--token-url/--wait/--fetch-interval`.
- `exec --help` → this Forgejo act fork has **stripped** `--action-offline-mode` and
  `--action-cache-path`; the only action lever left is `--default-actions-url`.

So **there is no offline mode in this runner, at any layer.** Two consequences fall out: (1) a
pre-baked/persisted `~/.cache/act` would *still* `git fetch` upstream every job (nothing can tell it
"don't"), so baking only converts *clone* → *fetch* — and the cache path's run-to-run stability is
unverified, making it fragile; (2) what actually governs where actions come from is the **Forgejo
server's `DEFAULT_ACTIONS_URL`** (unset today → defaults to `data.forgejo.org`).

A truly shared cache would need `ReadWriteMany`, which the cluster forbids by policy
(`storage-cnpg-governance.disallow-rwx-pvcs`; Longhorn RWX = a fragile NFS `share-manager` SPOF) — so
RWX is off the table regardless.

## Decision

**Measure first. Do not build action-cache infrastructure yet.** Ship
[ADR-0036](adr-0036-amd64-default-constrictor-build.md) (amd64-default builds — drop emulated arm64,
the larger cost) and verify the existing Harbor layer cache, then **re-time a real job**. The action
clones are likely a few seconds once QEMU emulation is gone; pay for cache infra only if measurement
says the wall still dominates.

**Explicitly rejected now:** runner "offline mode" (verified to not exist) and pre-baking
`~/.cache/act` (no offline mode ⇒ still fetches per job; fragile path).

**If measurement still warrants it, the chosen mechanism is a _scoped LAN mirror_:** mirror just the
docker-build action repos into the in-cluster Forgejo and reference them by explicit in-cluster URLs
in the `-fast` composite only (e.g. `uses: https://forgejo.webgrip.dev/<mirror>/checkout@v4`). LAN
clones are guaranteed fast, the blast radius is one composite, and it composes with the constrictor —
**without** flipping the server-wide `DEFAULT_ACTIONS_URL` (which would make local Forgejo
authoritative for *every* action any workflow uses, breaking un-mirrored ones).

## Consequences

- No runner-image or runner-config change ships for the cache in this round; the durable record now
  matches reality (no offline mode), avoiding a future engineer rebuilding the disproven approach.
- The action-cache work is **gated on a measurement**, captured against a real post-ADR-0036 job.
- If the scoped LAN mirror is later adopted, it needs a small mirror provisioner for ~6 repos and a
  `github-script` reference change (it currently uses an explicit `github.com` URL); both land in the
  `-fast` workflow, not globally.
- Carries forward to topology C unchanged — action resolution is independent of the build engine.

## Alternatives considered

- **Runner offline mode** — the original plan. **Impossible:** no flag/config/env in 12.10.2
  (evidence above). Rejected.
- **Pre-bake `~/.cache/act` into the image** — without offline mode it only turns clone→fetch (still
  a per-job internet round-trip), and the cache path's stability across runs is unverified. Low ROI,
  fragile. Rejected (revisit only if a future runner gains offline mode).
- **Global `DEFAULT_ACTIONS_URL` → in-cluster Forgejo** — one server line, but makes local Forgejo
  authoritative for *all* actions; every action any workflow uses (15+) must be mirrored or that job
  breaks. Too broad. Rejected in favor of the scoped per-action mirror.
- **RWX shared cache PVC** — forbidden by cluster policy (NFS `share-manager` SPOF); marginal benefit
  once the hot path is mirrored. Rejected. (A per-node `hostPath` is the lower-risk step if a shared
  cache is ever needed.)
