# RFC: One delivery contract for every project

> Status: **Accepted** 2026-10-17 · Owner: Ryan · Decision record:
> [ADR-0069](../adr/adr-0069-one-delivery-contract.md) · Plan with old and new maps:
> [Release supply chain](https://claude.ai/artifact/RNeXfn8qdVH8XhutYXHta8) (private artifact).
> Replaces this RFC's first draft (a custom homelab release bot, `c3f2c7a5`).

## Why

On 2026-10-17 a change reached the homelab through eight hand steps across three release models:

| Component | Forge | Hand steps | Which |
| --- | --- | --- | --- |
| Ploeg | GitHub | 3 | prepare PR (CHANGELOG + `Chart.yaml`), tag, homelab pin |
| Unfold app | Forgejo | 2 | Ploeg submodule pin PR, homelab pin |
| CI runner image | Forgejo | 1 | pinned by digest only, which Renovate cannot follow |
| Agent runner image | Forgejo | 1 | excluded from Renovate |
| Renovate presets | Forgejo | 1 | `next` → `main` merge (an intended promotion gate) |
| Erfbeeld, Unfold site, shared CI workflows | Forgejo | 0 | already on semantic-release and channels |

Erfbeeld is the model: `development` cuts prereleases, `main` cuts stables, and Renovate automerges
each channel into its environment. The only human step is merging `development` into `main`.

## The contract

**Forges produce, registries carry, clusters consume.** After the release step nothing reads a
forge, so the forge a project lives on stops mattering.

| Layer | Rule | Proven in | New work |
| --- | --- | --- | --- |
| Branches | `development` → `-rc.N`, `main` → stable; merging development into main is the promotion | Erfbeeld, Unfold, shared config | Ploeg adopts it |
| Release | semantic-release with `@webgrip/semantic-release-config`; the home forge is the release authority; a forge adapter picks the platform plugin | Forgejo repos via `makeConfig` | forge adapter (the config throws today without `SEMANTIC_RELEASE_GITEA`) |
| Artifacts | OCI image + OCI Helm chart, pushed by digest, signed, with SBOM; open source to GHCR, private to Harbor; clusters pull through Harbor | Ploeg (GHCR), Unfold and Erfbeeld (Harbor) | Ploeg publishes a contract bundle (schemas, domain model) per release |
| Consumption | Renovate reads registries only; one preset maps the prerelease channel to automerge-every-rc and the stable channel to automerge-stables | Erfbeeld's rules in `.renovaterc.json5` | lift those rules into a `renovate-config` preset; Ploeg, Unfold and both runner images join the prerelease channel |
| Verify | post-deploy readiness and running-digest check; failure reverts and pages; success records a deploy event (Ploeg ADR-0047) | Flux health, blackbox probes | the check job |

## Forge adapters

Every adapter runs the same release container (`semantic-release-monorepo` from
`webgrip/infrastructure`) with the same config; only a small CI wrapper and the platform plugin differ.

| Forge | Release plugin | CI wrapper | Renovate job | When |
| --- | --- | --- | --- | --- |
| Forgejo | Gitea plugin | reusable workflow in `webgrip/workflows` | `webgrip-forgejo` | running |
| GitHub | `@semantic-release/github` | reusable workflow published on GitHub | `webgrip-gitops` (exists) | now, for Ploeg |
| GitLab | `@semantic-release/gitlab` | CI component | new RenovateJob | first GitLab project |
| Bitbucket | none official: tags + notes | pipe | new RenovateJob | first Bitbucket project |

An adapter counts only after a conformance run on a fixture repository on that forge: it cuts an rc,
publishes an image, and Renovate picks it up.

## Plugging in a project

1. Conventional commits; `development` and `main` protected (ADR-0050).
2. A 3-line `.releaserc.cjs` calling `makeConfig({})`.
3. The CI wrapper for its forge, copied from the template.
4. An image and chart that build from the repository, published through the shared action.
5. One entry in the homelab's channel list: `prerelease` or `stable`.

## Decisions (owner, 2026-10-17)

| # | Decision |
| --- | --- |
| D1 | Each project releases from its home forge; Ploeg stays on GitHub (Ploeg ADR-0062) |
| D2 | Unfold depends on a released Ploeg (a Renovate-bumped version plus the contract bundle), not the `apps/ploeg` submodule |
| D3 | The homelab is the prerelease channel; customer clusters take the stable channel |
| D4 | Every releasable Ploeg merge to `development` cuts a candidate |

## Phases

| Phase | Lands | Done when |
| --- | --- | --- |
| P0 | ADR-0069 here; superseding records in Ploeg (ADR-0063/0064), Unfold (ADR-0019) and the shared config | records accepted |
| P1 | channel preset; Ploeg, Unfold and runner images on the prerelease channel; CI runner pinned by tag + digest; workflow callers on tags | the next Ploeg and Unfold releases reach the homelab through automerge |
| P2 | forge adapter in the shared config; Ploeg on semantic-release with the GitHub wrapper, proven on a fixture repo first | a Ploeg merge produces a published `-rc.N` with no hand step |
| P3 | Ploeg publishes the contract bundle; Unfold drops the submodule for a released dependency | a Ploeg release reaches an Unfold release through automerge |
| P4 | post-deploy check with revert and deploy events | a broken rc is reverted automatically; a good one is recorded as deployed |
| P5 | GitLab and Bitbucket adapters | each after its conformance run |

Implementation runs in a separate work stream; its first slice is the homelab branch
`fix/renovate-ploeg-unfold-release`.

## Risks

- **More tags.** Every releasable Ploeg merge is a candidate; ADR-0028 already treats candidates as
  disposable.
- **A bad candidate lands without a person.** CI in each repository, the homelab's `e2e /` checks and
  the verify layer stand in its way.
- **Release tokens per forge.** Each adapter needs a write token on its own forge, scoped to one
  repository, stored in OpenBao and delivered through the existing bridge (ADR-0055).
