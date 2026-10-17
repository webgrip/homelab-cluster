# RFC: One release train from a merged Ploeg PR to the homelab

> Status: **Proposed** · Date: 2026-10-17 · Owner: Ryan · Spans `ploeg-hq/ploeg`,
> `webgrip/unfold` and this repository. Each decision below lands as an ADR in the repository it
> governs; T1 supersedes the candidate clauses of Ploeg ADR-0063 and ADR-0064.

## Why

A one-line Ploeg fix reaches the homelab through six steps, and four of them need a person or an
agent to write a pull request or a tag by hand:

| # | Step | Who today | What went wrong between 2026-10-04 and 2026-10-17 |
| --- | --- | --- | --- |
| 1 | Ploeg feature PR | person reviews and merges | stacked PRs merged into their parent branches instead of `development` (ploeg-hq/ploeg#65, #66) |
| 2 | Ploeg "prepare rc.N" PR: CHANGELOG and `Chart.yaml` | agent writes, person merges | forgotten until a release failed |
| 3 | Tag `v0.2.0-rc.N` | person | `v0.2.0-rc.22` was cut on `1081c60`, before ploeg-hq/ploeg#145 bumped the chart; the release refused it and nothing published |
| 4 | Unfold pin bump of the `apps/ploeg` submodule | agent writes, person merges | Renovate cannot do it: `apps/ploeg/**` is in Unfold's `ignorePaths`, and the bump also regenerates `docs/reference/decisions.md` |
| 5 | Unfold release | automatic, semantic-release on `development` | blocked overnight by a Ploeg test that failed only inside the submodule |
| 6 | Homelab: Ploeg chart and image, Unfold chart and two images | agent writes by hand | Renovate is configured for these pins, yet none of the last 25 commits under `kubernetes/apps/ploeg` came from it; Ploeg and Unfold also move separately, so the homelab can run a pair Unfold never tested together |

Steps 2 and 3 are manual on purpose: Ploeg ADR-0063 forbids calculating a release from commit
messages, and ADR-0064 keeps tags "explicit and reviewed". Those rules protect stable releases.
Everything this train carries is a `0.x.y-rc.N` candidate, which ADR-0028 already treats as
disposable.

## Target

```text
Ploeg PR merged
  -> CI cuts Ploeg vX.Y.Z-rc.N on the commit it verified            (T1)
  -> Ploeg release opens the Unfold pin PR; it merges itself on green (T2)
  -> Unfold CI cuts its rc and publishes release-manifest.json       (T3)
  -> homelab bot opens ONE PR for the certified pair; merges on e2e  (T4)
  -> Flux deploys -> post-deploy check -> pass: done / fail: revert + page (T5)
```

The only human step is reviewing the code PR. Each later step is a bot pull request that merges
itself only after a check that can fail has passed. Expected wall-clock time is about 45 minutes,
with nobody involved.

## Decisions

| # | Question | Proposal | Rejected |
| --- | --- | --- | --- |
| T1 | Who cuts a Ploeg candidate | CI, on every push to `development` that passed `verify`: the next rc number comes from the latest tag, the release job writes the `Chart.yaml` version and the CHANGELOG section, and tags the exact commit CI verified. A stable `v0.x.y` stays an explicit tag on `main` (ADR-0063 unchanged for stable) | the prepare PR (step 2) and the hand tag (step 3); version calculation from conventional commits (ADR-0063's objection stands, only the rc counter moves) |
| T2 | How Unfold follows Ploeg | Ploeg's release job opens the pin PR on Unfold itself: submodule to the release commit, `.gitmodules` branch, regenerated decision register. It uses a Forgejo token scoped to `webgrip/unfold`, and Unfold automerges the PR when its full CI is green | Renovate on the submodule: it cannot regenerate the docs the pin needs, and its schedule adds hours |
| T3 | What the homelab deploys | The pair Unfold certified. Each Unfold release publishes `release-manifest.json` as a release asset: the Unfold version, the Ploeg version it pinned, and every chart and image digest of both | bumping Ploeg and Unfold independently: an untested pair, two PRs, two rollouts |
| T4 | Who writes the homelab bump | A small job in this repository, triggered by Unfold's release webhook with an hourly fallback. It reads the manifest, rewrites the pinned tags and digests, runs `./scripts/run-flux-local-test.sh`, opens the PR, and automerges it when the `e2e /` checks pass. The Ploeg and Unfold Renovate rules are switched off for these pins, so there is one writer | Renovate automerge: its soak and dashboard gates have already frozen these pins silently; Flux image automation: it writes `main` directly, outside the e2e gate |
| T5 | What deployed means | When Flux reports both HelmReleases Ready, a verification Job checks `/readyz` of ploegd and Unfold and that both run the manifest's digests. On failure it reverts the bump commit and pages. On success it posts to Ploeg's deploy endpoint (Ploeg ADR-0047), so a Run card shows where a change runs | trusting HelmRelease Ready: a running pod is not a working pair |
| T6 | How a bad candidate stops | Each stage refuses to start on a red predecessor. A `release-train: hold` file in this repository pauses T4 without touching the rest | per-repo freezes nobody remembers to lift |

## What changes where

- **ploeg-hq/ploeg:** the release workflow gains "cut on development" (T1) and "propose the Unfold
  pin" (T2), plus a new ADR superseding the candidate clauses of ADR-0063 and ADR-0064.
  `scripts/release.sh validate` keeps refusing a tag whose chart version differs; with T1 that
  holds by construction.
- **webgrip/unfold:** an automerge rule for the pin PR, `release-manifest.json` published by the
  release job (T3), and an ADR refining ADR-0018 and ADR-0019.
- **homelab-cluster:** a `train-bump` workflow and script (T4), the verification Job and its alert
  (T5), the hold switch (T6), and the Ploeg/Unfold pin rules in `.renovaterc.json5` disabled.

## Rollout

| Stage | Lands | Proven by |
| --- | --- | --- |
| 1 | T3: the manifest on the next Unfold release | the asset exists and every digest equals the registry's |
| 2 | T4 in dry run: opens PRs, never automerges | three bot PRs in a row identical to what a person would write |
| 3 | T1 and T2 | a merged Ploeg PR reaches an Unfold release with no human step |
| 4 | T4 automerge and T5 | one train that deploys, and one deliberately broken candidate that is reverted and pages |

## Risks

- **More tags.** Every Ploeg merge becomes a candidate. Candidates are cheap, and ADR-0028 already
  treats them as disposable.
- **A bad pair reaches the homelab sooner.** Unfold's integration gate, the `e2e /` checks, the T5
  check with automatic revert, and the hold switch stand in its way.
- **Bot tokens.** T2 and T4 need write access to `webgrip/unfold` and this repository. Both tokens
  live in OpenBao and reach CI through the existing bridge (ADR-0055), each scoped to one
  repository.
