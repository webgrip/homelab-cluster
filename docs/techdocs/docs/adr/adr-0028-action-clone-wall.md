# The action-clone wall — measure first; no offline mode exists

* Status: accepted
* Date: 2026-07-02

Technical Story: [RFC: CI pipeline performance](../rfc/rfc-ci-pipeline-performance.md)

## Context and Problem Statement

Each CI job runs in a fresh ephemeral runner pod ([ADR-0026](adr-0026-rootless-ci-image-builds.md)),
so the act action cache at `/home/runner/.cache/act` is empty every run and every action
(`actions/checkout`, the `docker/*` set, `actions/github-script`) is `git clone`'d from
`data.forgejo.org` / `github.com` before any real work.

## Considered Options

* Measure first; build no action-cache infrastructure yet
* Runner offline mode
* Pre-bake `~/.cache/act` into the runner image
* Global `DEFAULT_ACTIONS_URL` → in-cluster Forgejo
* RWX shared cache PVC

## Decision Outcome

Chosen option: "Measure first; build no action-cache infrastructure yet", because verification
against the exact runner image disproved the original plan's load-bearing assumption — no offline
mode exists in this runner, at any layer — so cache infrastructure is paid for only if
measurement says the wall still dominates.

The original plan was "pre-bake the actions into the runner image + enable runner **offline
mode** so they're never re-fetched." **Verification against the exact image
(`code.forgejo.org/forgejo/runner:12.10.2`) disproved the load-bearing assumption:**

* `generate-config` → the `cache:` block is **only** the `actions/cache` server
  (`ACTIONS_CACHE_URL`), not the action-repo cache.
* `one-job --help` (the daemon path) → exposes only `--url/--uuid/--token-url/--wait/--fetch-interval`.
* `exec --help` → this Forgejo act fork has **stripped** `--action-offline-mode` and
  `--action-cache-path`; the only action lever left is `--default-actions-url`.

So **there is no offline mode in this runner, at any layer.** Two consequences fall out: (1) a
pre-baked/persisted `~/.cache/act` would *still* `git fetch` upstream every job — baking only
converts *clone* → *fetch*, and the cache path's run-to-run stability is unverified; (2) what
actually governs where actions come from is the Forgejo **server's** `DEFAULT_ACTIONS_URL` (unset
today → `data.forgejo.org`). A truly shared cache would need `ReadWriteMany`, which cluster policy
forbids (`storage-cnpg-governance.disallow-rwx-pvcs`; Longhorn RWX = a fragile NFS `share-manager`
SPOF).

Ship [ADR-0027](adr-0027-amd64-default-constrictor-build.md) (drop emulated arm64 — the larger
cost), verify the existing Harbor layer cache, then **re-time a real job**; pay for cache infra
only if measurement says the wall still dominates. The workflows and the measurement live in
`webgrip/workflows`, not this repo.

**Explicitly rejected now:** runner offline mode (verified to not exist) and pre-baking
`~/.cache/act` (no offline mode ⇒ still fetches per job; fragile path).

**If measurement warrants it, the chosen mechanism is a *scoped LAN mirror*:** mirror just the
docker-build action repos into the in-cluster Forgejo and reference them by explicit in-cluster
URLs in the `-fast` composite only — **without** flipping the server-wide `DEFAULT_ACTIONS_URL`
(which would make local Forgejo authoritative for *every* action any workflow uses, breaking
un-mirrored ones).

### Positive Consequences

* No runner-image or runner-config change ships for the cache; the durable record matches reality
  (no offline mode), so a future engineer won't rebuild the disproven approach.
* Carries forward to the RFC's topology C unchanged — action resolution is independent of the build
  engine.

### Negative Consequences

* The action-cache work is gated on a measurement of a real post-ADR-0027 job.
* A later scoped LAN mirror needs a small mirror provisioner (~6 repos) and a `github-script`
  reference change (it uses an explicit `github.com` URL); both land in the `-fast` workflow, not
  globally.

## Pros and Cons of the Options

### Measure first; build no action-cache infrastructure yet

* Good, because the durable record matches reality (no offline mode), so a future engineer won't
  rebuild the disproven approach.
* Bad, because the action-cache work is gated on a measurement that lives in `webgrip/workflows`
  and is not verifiable from this repo.

### Runner offline mode

The original plan.

* Bad, because impossible: no flag/config/env in 12.10.2 (evidence above).

### Pre-bake `~/.cache/act` into the runner image

* Bad, because without offline mode it only turns clone→fetch (still a per-job internet
  round-trip); fragile, low ROI. Revisit only if a future runner gains offline mode.

### Global `DEFAULT_ACTIONS_URL` → in-cluster Forgejo

* Good, because one server line.
* Bad, because it makes local Forgejo authoritative for *all* actions (15+); each must be mirrored
  or that job breaks. Too broad.

### RWX shared cache PVC

* Bad, because forbidden by cluster policy; marginal benefit once the hot path is mirrored. (A
  per-node `hostPath` is the lower-risk step if a shared cache is ever needed.)

## Links

* 2026-06-25 — accepted (eea51342)
* 2026-07-02 — audit: still in effect — the runner remains ephemeral DinD, no LAN mirror exists,
  RWX is still policy-forbidden; the gating re-measurement lives in `webgrip/workflows` and is not
  verifiable from this repo
* 2026-07-03 — renumbered from ADR-0035 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
