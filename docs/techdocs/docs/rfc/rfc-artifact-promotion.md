# RFC: Promote the artifact, not the branch

> Status: **Accepted** 2026-10-31 · Owner: Ryan · Refines
> [ADR-0078 One release recipe](../adr/adr-0078-one-release-recipe-four-kinds.md) and
> [its RFC](rfc-one-release-recipe.md) · Decision record:
> [ADR-0088](../adr/adr-0088-one-branch-every-merge-releases-and-environments-promote-the-artifact.md) ·
> Plan page: [Delivery Alignment Plan](https://claude.ai/artifact/Def3pc8o66YzZ9yNwdahHh).

## Why

ADR-0078 gave every repository whose bad release breaks more than itself a *staged* branch shape:
`development` cuts `-rc.N`, `main` cuts stables, and promotion is a fast-forward of `main` to
`development`. On 2026-10-30 the estate alignment was about to stage eight more repositories
(homelab-cluster #986). Looking at what the shape costs in the one repository that runs it end to
end, twente.dev:

| Part | Why it exists |
| --- | --- |
| a second protected branch | the shape itself |
| Renovate `baseBranchPatterns: ["development"]` | updates must land where releases are cut |
| a release-channel parser on `release: published` | `-rc` deploys to staging, stable to production |
| an "open or keep the promotion PR" job | a person promotes by merging it |
| a back-merge safety net | a commit on `main` alone breaks the next rc computation |
| a production deploy that **rebuilds** | the stable tag is a new commit run, not the rc's bytes |

About 170 lines of workflow per repository, copied, plus a failure mode that needs a person:
`main` and `development` diverging, which happened in Unfold, twente.dev and Erfbeeld before
2026-10-23. Every part exists to keep two branches in step. None of it makes production safer than
the rc it promotes; the stable even rebuilds, so production does not run the bytes staging ran.

The same review found the release step itself in three shapes that the four kinds do not describe:
one train per repository (most), several trains per repository (ai-skills with 30 skills,
frontend-toolkit, infrastructure, Erfbeeld, Unfold, each with its own tooling), and a version that
comes from upstream rather than from commits (talos-kata-extension, versioned after Kata).

## Proposal

### 1. One branch; every merge releases; environments promote the artifact

`main` is the only long-lived branch. A merge that `semantic-release` counts as a release cuts
`vX.Y.Z` (no `-rc`). The release builds the artifact once and puts it on **staging** with no
person involved. **Production** takes the artifact staging already ran, by an explicit promote:

| Kind | Release produces | Staging | Promote to production |
| --- | --- | --- | --- |
| site, Worker | a Workers version, `wrangler versions upload --tag vX.Y.Z` | the staging Worker deploys it | `wrangler versions deploy <id>`, optionally gradual (`<id>@10%` then `@100%`) |
| service | a signed image digest and a chart | staging follows the newest release (Renovate or Flux image automation, automerge) | a pull request that moves the production pin in the cluster repository |
| package, preset, reusable workflow | a tag and its registry artifact | one named **canary consumer** takes it at once (`minimumReleaseAge: 0`) | every other consumer takes it after the soak, through its own Renovate pull request |
| image set | signed digests | the canary consumer | the soak, as for packages |
| config | nothing; applied from `main` | – | – |

A rollback is a promote of the previous version. A hotfix while `main` holds work that must not
ship is a maintenance branch cut from the stable tag (`1.4.x`), which semantic-release releases
on its own range; it is the exception, not the shape.

### 2. Release layouts: single, trains, upstream

How a repository *versions* is a field of its own, next to its kind:

| Layout | Version from | Tag | Repositories |
| --- | --- | --- | --- |
| `single` | conventional commits | `vX.Y.Z` | most |
| `trains` | conventional commits scoped to one directory per train, changed trains only, all trains in **one job** | `<train>-vX.Y.Z` | ai-skills (`skills/*`), frontend-toolkit (`packages/*`), infrastructure (`ops/docker/*`), Erfbeeld, Unfold |
| `upstream` | a version file, tagged when its version is new | the file's version | talos-kata-extension (`build.env`) |

The shared `semantic-release` composite action in `webgrip/workflows` runs all three, in a normal
job, on the one toolchain image. A train can name a publish step (ai-skills publishes a `.skill`
package per release), so per-repository release scripts retire.

### 3. Previews

A preview is a live URL per pull request, for repositories whose change a person judges by looking:
sites (webgrip.nl, twente.dev, the product sites to come for fogbell and wellhead) and single-page
apps (Unfold, Erfbeeld, omnigraph-explorer). Sites use the Workers preview URL of
`wrangler versions upload`; apps use preview-host. Collectors (counterscale), bots (fogbell's
service), packages, image sets and config repositories get none.

## Migration

1. `webgrip/workflows`: release layouts in the composite; a `promote` action for Workers; Workers
   versions uploaded and tagged on release. `semantic-release-config`: default branches become
   `main` plus maintenance ranges.
2. Pilots: webgrip.nl (site, promote) and ai-skills (trains).
3. counterscale, seekframe, talos-kata-extension (`upstream`); then twente.dev, Erfbeeld and Unfold
   leave `development` after their last rc is promoted.
4. The repo-config model gains `release` (layout and trains) and drops `staged` from every
   repository that has moved; the inventory and the Delivery estate board read the layout.
5. A shared site recipe on `frontend-toolkit`'s astro-site-toolkit, then the fogbell and wellhead
   sites.

## Risks

* `main` carries work that is released but not yet in production. That is the point of staging;
  the promote names exactly which version production runs.
* A Workers version is kept by Cloudflare, not by us; promote fails loudly when the tagged version
  is gone, and the release can re-upload from the tag.
* Unfold's release train (Ploeg consumption, `ploeg-release` merges) is the most coupled consumer of
  `development`; it moves last, on its own plan.
