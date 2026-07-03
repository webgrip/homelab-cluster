# Keep GitHub as a read-only data oracle during the Renovate cutover

* Status: accepted
* Date: 2026-07-02

Technical Story: [RFC: Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md)

## Context and Problem Statement

"Leave GitHub" is two separable claims for Renovate. As the **employer** — the host it logs into
and opens PRs against — GitHub must go ([ADR-0029](adr-0029-dual-run-renovate-forgejo.md) /
[ADR-0030](adr-0030-forgejo-static-bot-pat.md)). But Renovate also reaches GitHub as **public
data**, a role not coupled to where the code lives: **version datasources** (`github-releases` /
`github-tags` query `api.github.com` for a large share of the estate's dependencies regardless of
platform); **config presets** (the shared policy in `webgrip/renovate-config`); and **GHCR
images** (`ghcr.io/webgrip/*`), which need a credential or go anonymous — rate-limited and blind
to private packages. Cutting *all* GitHub access at once would break all three — none of which is
what "leave GitHub" is actually about.

## Considered Options

* GitHub as a read-only data oracle
* A dedicated `read:packages` GitHub PAT for GHCR (the original plan)
* Anonymous GHCR
* Block the migration on Harbor
* Mirror `renovate-config` to Forgejo immediately and switch presets
* Drop GitHub datasources entirely

## Decision Outcome

Chosen option: "GitHub as a read-only data oracle", because Renovate's reads of GitHub — version
datasources, config presets, GHCR images — are public-data roles not coupled to where the code
lives, and cutting all GitHub access at once would break all three; none of which is what "leave
GitHub" is actually about.

Keep GitHub as a **read-only data oracle** and re-home each use only when its downstream lands:

* **Datasources:** retain the `api.github.com` `hostRules` (throttling); `github-releases` /
  `github-tags` keep querying GitHub — largely permanent and legitimate, since that is where
  upstream OSS publishes.
* **Presets:** resolve from wherever `webgrip/renovate-config` is authoritative. That is now
  Forgejo — the Forgejo job extends `local>webgrip/renovate-config:forgejo`
  (`renovate-operator/jobs/configmap-forgejo.yaml`); repo-local configs on repos still
  GitHub-authoritative continue to extend `github>webgrip/renovate-config`.
* **GHCR:** during dual-run, **reuse the GitHub-App token-minter's `RENOVATE_HOST_RULES`** — the
  minter CronJob keeps running for the GitHub path anyway, and the Forgejo RenovateJob consumes
  the same value via an `extraEnv` `valueFrom` (`optional: true`): no separate GHCR PAT, no
  OpenBao entry. At GitHub-path retirement the minter goes away, so GHCR re-homes to Harbor
  ([RFC: Harbor](../rfc/rfc-harbor-registry.md)) or, failing that, a retained minimal
  packages-only token.

The principle: **employer ≠ oracle.** A GitHub credential that can only *read public release data
and pull packages* is not "still on GitHub" in the sense that matters — it holds no write
authority over the source of truth.

### Positive Consequences

* Version resolution, preset loading, and private-image datasources keep working while the
  employer flips to Forgejo — no regression in what Renovate can *see*.
* Honest scoping: "Renovate left GitHub" is true for the **write/employer** path well before the
  **read/oracle** path is fully re-homed.

### Negative Consequences

* A residual, **read-only** GitHub dependency remains by design, with explicit exit ramps: presets
  (taken — now `local>` on Forgejo), GHCR (→ Harbor at retirement), datasources (permanent).
* **Coupling:** the Forgejo path's GHCR access depends on the GitHub-App minter still running, so
  GHCR re-homing must land *with* the GitHub-path retirement, not after it.

## Pros and Cons of the Options

### GitHub as a read-only data oracle

* Good, because version resolution, preset loading, and private-image datasources keep working
  while the employer flips to Forgejo.
* Good, because the retained credential holds no write authority over the source of truth.
* Bad, because a residual read-only GitHub dependency remains, and the Forgejo path's GHCR access
  is coupled to the GitHub-App minter still running.

### A dedicated `read:packages` GitHub PAT for GHCR (the original plan)

* Bad, because a new hand-minted credential and OpenBao entry for something the App-minter already
  produces.

### Anonymous GHCR

* Bad, because private packages are invisible and rate limits aggressive; acceptable only as the
  transient `optional: true` fallback.

### Block the migration on Harbor

* Bad, because it would stall the Renovate cutover behind a registry with zero cluster footprint
  at decision time.

### Mirror `renovate-config` to Forgejo immediately and switch presets

* Bad, because pointless while that repo was an inbound mirror; deferred until authoritative
  (since done — see Links).

### Drop GitHub datasources entirely

* Bad, because not feasible; upstream OSS releases live on GitHub.

## Links

* 2026-06-13 — proposed with the RFC; GHCR plan revised the same day to reuse the App-minter's
  host-rules instead of a dedicated PAT
* 2026-06-16 — accepted
* 2026-07-02 — presets exit ramp taken: `webgrip/renovate-config` is Forgejo-authoritative and the
  Forgejo job now extends `local>webgrip/renovate-config:forgejo`. GHCR still rides the App-minter
* 2026-07-03 — renumbered from ADR-0013 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
