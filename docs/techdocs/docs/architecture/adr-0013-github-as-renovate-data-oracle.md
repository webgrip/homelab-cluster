# ADR-0013: Keep GitHub as a read-only data oracle during the Renovate cutover

> Status: **Proposed** · Date: 2026-06-13 · Part of [RFC: Renovate on Forgejo](rfc-renovate-forgejo.md)

## Context

"Leave GitHub" is two separable claims for Renovate. As the **employer** — the host it logs into,
pushes branches to, and opens PRs against — GitHub must go, and [ADR-0011](adr-0011-dual-run-renovate-forgejo.md)
/ [ADR-0012](adr-0012-forgejo-static-bot-pat.md) move it to Forgejo. But Renovate also reaches GitHub
as **public data**, and that role is legitimate and not coupled to where the code lives:

- **Version datasources** — `github-releases` and `github-tags` resolve upstream versions for a large
  share of the estate's dependencies (tools, charts, pinned releases). These query `api.github.com`
  regardless of platform.
- **Config presets** — `.renovaterc.json5` extends `github>webgrip/renovate-config#vX`, fetched from
  github.com. The `webgrip/renovate-config` repo is itself a migration candidate, but until it is
  Forgejo-authoritative the preset must resolve from GitHub.
- **GHCR images** — every image is still `ghcr.io/webgrip/*`. Today GHCR is authenticated by the
  GitHub-App token; once that token is gone ([ADR-0012](adr-0012-forgejo-static-bot-pat.md)), GHCR
  needs its own credential or it goes anonymous (and rate-limited / blind to private packages).

Cutting *all* GitHub access at once would break version resolution, preset loading, and private-image
datasources — none of which is what "leave GitHub" is actually about.

## Decision

During the transition, **keep GitHub as a read-only data oracle** and re-home it only when its
downstream lands:

- **Datasources:** retain the `api.github.com` `hostRules` (throttling) in the Forgejo admin
  ConfigMap. `github-releases` / `github-tags` continue to query GitHub.
- **Presets:** keep `extends: ["github>webgrip/renovate-config#vX", …]` until `webgrip/renovate-config`
  is Forgejo-authoritative, then switch to `forgejo>webgrip/renovate-config`.
- **GHCR:** authenticate with a **fine-grained GitHub PAT scoped to `read:packages`** for
  `ghcr.io/webgrip/*`, baked into the static `RENOVATE_HOST_RULES` JSON in OpenBao. Re-homes to Harbor
  under [RFC: Harbor](rfc-harbor-registry.md) when Harbor exists.

The principle: **employer ≠ oracle.** A GitHub credential that can only *read public release data and
pull packages* is not "still on GitHub" in the sense that matters — it holds no write authority over
the source of truth.

## Consequences

- Version resolution, preset loading, and private-image datasources keep working the instant the
  employer flips to Forgejo — no regression in what Renovate can *see*.
- A residual, **read-only** GitHub dependency remains by design, with three explicit exit ramps:
  presets (→ `forgejo>` when the config repo migrates), GHCR (→ Harbor), and datasources (largely
  permanent and legitimate — GitHub is where upstream OSS publishes).
- The `read:packages` PAT is a new credential to manage, but minimal-scope and read-only; it lives in
  OpenBao like everything else.
- Honest scoping: "Renovate left GitHub" will be true for the **write/employer** path well before the
  **read/oracle** path is fully re-homed, and the status board should say so.

## Alternatives considered

- **Anonymous GHCR.** No new credential, but private `ghcr.io/webgrip/*` packages become invisible to
  datasources and anonymous pulls are aggressively rate-limited. Rejected as the default; acceptable
  only if every relevant package is public.
- **Block the migration on Harbor.** Cleanest end-state (no GitHub at all), but Harbor has zero cluster
  footprint today ([RFC: Harbor](rfc-harbor-registry.md) is Proposed), so this would stall the entire
  Renovate cutover behind an unstarted registry. Rejected — the PAT is the deliberate bridge.
- **Mirror `renovate-config` to Forgejo immediately and switch presets now.** Possible, but pointless
  while the repo is an inbound mirror (writes go the wrong way) and it couples the preset switch to the
  bulk mirror's progress. Deferred until that repo is authoritative.
- **Drop GitHub datasources entirely.** Not feasible — upstream OSS releases live on GitHub; this isn't
  a sovereignty concern, it's reading a public catalog. Kept permanently.
