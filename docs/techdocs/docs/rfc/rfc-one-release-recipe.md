# RFC: One release recipe, four kinds of project

> Status: **Proposed** 2026-10-23 · Owner: Ryan · Builds on
> [ADR-0069 One delivery contract](../adr/adr-0069-one-delivery-contract.md) and
> [its RFC](rfc-unfold-release-train.md) · Plan page:
> [Release supply chain](https://claude.ai/artifact/RNeXfn8qdVH8XhutYXHta8), round 5.

## Why

ADR-0069 says what a release must achieve. It does not say how each repository gets there, and on
2026-10-23 the estate did it in many ways. A read-only survey of 32 repositories (every active repo
on Forgejo `webgrip`, `ploeg-hq/ploeg` on GitHub, and every first-party pin in this repository)
found:

- Five ways to cut a version: the shared semantic-release config (15 repos), hand-written local
  semantic-release configs (6 legacy repos), a Python script (`ai-skills`), hand tags (Ploeg
  stables, `workflows` v1.0.0, the `unfold-delivery-inputs` image), and nothing at all (8 repos,
  among them `webgrip.nl` and `counterscale`, which deploy unversioned commits).
- Four versions of `@webgrip/semantic-release-config` in use (1.2.3, 1.3.0, 1.3.3, 1.4.0). The
  version rides inside a toolchain image whose tag the `webgrip/workflows` defaults pin by hand, so
  only Ploeg runs 1.4.0, the version with the forge adapter ADR-0069 requires.
- Three ways to install the release tooling (toolchain image, a workspace lockfile, a git clone of
  the config). Ploeg's clone makes its GitHub release depend on this homelab: its release candidate
  failed on 2026-10-23 05:05 because Forgejo answered 503.
- Five branch models (main; development + main; main + `next`; main + `release/*`; `master`).
  `development` and `main` have diverged in Unfold, twente.dev and Erfbeeld.
- Seven tag styles (`v1.2.3`, `1.2.3`, both at once, `<pkg>-v1.2.3`, `@webgrip/<pkg>-v1.2.3`,
  `unfold-v…`, floating `v1`), and two prerelease identifiers (`-rc.N`, `-development.N`).
- Six trigger styles: push cuts and publishes in one run; push cuts and `release: published`
  publishes; tag push publishes; manual dispatch; unversioned deploy on push; a nightly redeploy
  outside any release.
- Six registries: Harbor `webgrip/`, GHCR `ploeg-hq/` and `webgrip/`, the Forgejo package registry,
  Docker Hub and npmjs.org. `common-charts` publishes to Harbor while every chart that uses it
  reads `oci://ghcr.io/webgrip/common-charts`, which holds only 1.0.13.
- Two signing roots (the OpenBao Transit key, GitHub keyless), unsigned Erfbeeld images that
  admission now refuses (ADR-0073), and unsigned Unfold, Erfbeeld and common-charts charts.
- 29 internal `@main` references inside `webgrip/workflows`, so a caller pinned to `v2.8.2` still
  runs whatever `main` holds in the nested workflows.

Nine repositories have release paths that no longer run (legacy `.github/workflows` on
self-hosted runners that were removed): `freshrss-`, `searxng-`, `invoiceninja-` and
`backstage-application`, `ledgerflow`, `monitoring-platform`, `traefik-local-development`,
`whisperx-application`, `twitch_exporter`.

Each difference is small. Together they mean that knowing how one project releases tells you
nothing about the next, which is the mental load this RFC removes.

## The tool: semantic-release, hardened

Compared on 2026-10-23 against release-please, knope, changesets, cocogitto, git-cliff, goreleaser,
Release Drafter, JReleaser and others (sources in the session research note, summarised here):

| Tool | Fits | Does not fit |
| --- | --- | --- |
| **semantic-release** 25.x | branch-based rc and stable channels match `development`/`main`; official GitHub and GitLab plugins; the shared config and our own Forgejo plugin already run in 15 repos; no release PR, so code review stays the only human step | Forgejo and Bitbucket plugins are community or own-built; `semantic-release-monorepo` has had no release since 2024-02; `@semantic-release/git` release commits caused the tag-on-wrong-commit failures (homelab `8e57505`, Ploeg forbids it) |
| release-please (Google) | release PRs with a readable changelog; good monorepo manifest | GitHub API only, the request for other forges has been open since 2021 and the one Gitea port is unmaintained; weak prerelease support; the release PR is a second human step, or automerged it is push-to-release with extra latency |
| knope 0.23 | one binary, conventional commits plus change files, Gitea releases, monorepo | pre-1.0, one maintainer, no GitLab or Bitbucket, re-seeding every monorepo tag format |
| git-cliff | healthy, forge-neutral changelog and next-version calculation | creates no tags or releases; we would write and own the release logic |
| goreleaser | right tool to build and sign Go binaries | not a versioner; runs after a tag |

Decision proposed: **semantic-release stays**, with these hardening rules in the shared config:

1. **Tags only.** No release commit in any repository. The version is written into `Chart.yaml`,
   `package.json` or the VS Code manifest at package time, from the tag. This removes the
   tag-on-wrong-commit class and the push races with concurrent agents.
2. **One way to get the tooling:** the `semantic-release` toolchain image, pinned by tag and digest,
   moved by Renovate like any other pin. It is published to Harbor and copied to GHCR, so a GitHub
   release never depends on the homelab being up.
3. **Monorepo trains** come from the shared config (`paths` per package, tag format
   `<name>-v<version>`), replacing the unmaintained `semantic-release-monorepo`. To be proven on
   `infrastructure` first.
4. **The release job fails on a non-conventional commit** in its range instead of silently not
   releasing, because PR-title checks never see trunk pushes.
5. One concurrency group per branch, so two merges never cut two versions of the same thing.

## Four kinds of project

Every repository is one of four kinds. The kind decides its branches, what it publishes and how
it reaches a consumer; everything else is the same for all of them.

| Kind | What it ships | Branches | Published to | Reaches its consumer by | Repos today |
| --- | --- | --- | --- | --- | --- |
| **Service** | image(s) plus one chart | staged: `development` cuts `-rc.N`, `main` cuts stables | Harbor `webgrip/` (private) or GHCR (open source, read through Harbor's `ghcr` proxy) | Renovate in each cluster repo, prerelease or stable channel per cluster, tag and digest, merge on green, verify after deploy | unfold, ploeg, erfbeeld, omnigraph-explorer, seekframe |
| **Image set** | many images, one train each | trunk: `main` cuts stables | Harbor `webgrip/` | Renovate, tag and digest, merge on green | infrastructure |
| **Package** | something other code uses: npm package, Renovate preset, Helm library chart, reusable workflow or action, skill | trunk: `main` cuts stables | the registry that kind of package lives in: Forgejo npm, OCI chart on Harbor, a git tag for presets and workflows | Renovate in every consumer; no pin is ever bumped by hand | semantic-release-config, renovate-config, frontend-toolkit, common-charts, workflows, action-typescript-template, telemetry-service, ai-skills |
| **Site** | a static site or Worker | staged: `-rc.N` deploys to staging, stables deploy to production | Cloudflare | the release itself: the deploy job runs on `release: published` | twente.dev, webgrip.nl, counterscale, unfold `apps/site` |

Repositories that are **applied, not released** (OpenTofu or Flux trees: homelab-cluster,
cloudflare, unfold-cluster) keep trunk `main` and apply from it. They have no versions because
nothing consumes them by version.

### The same in every kind

- **Versions** come from conventional commits through `@webgrip/semantic-release-config`.
  Tag format `v<version>`; `<name>-v<version>` per train in a repository with more than one.
  Prereleases are `-rc.N`. While a project is `0.x`, a breaking change raises the minor version.
- **Staged promotion is one act:** `main` fast-forwards to a commit of `development`. Nothing is
  ever committed to `main` directly, so the two branches cannot diverge again. Branch protection
  enforces it. For a service this is the deliberate human gate before production; it is the only
  human step besides code review.
- **One trigger shape:** a push cuts the version and the Forgejo or GitHub release; the
  `release: published` event builds, publishes, signs and deploys. The same workflow name and
  inputs exist on both forges.
- **Build once, by digest.** What the rc built is what the stable ships: promotion re-tags the
  candidate's digest, it never rebuilds.
- **Registries are an input.** The publish step takes `registry` (default
  `harbor.webgrip.dev/webgrip`). Open-source projects pass GHCR; nothing else changes.
- **Signed and with an SBOM, images and charts both.** On Forgejo the OpenBao Transit key signs; on
  GitHub, where OpenBao is unreachable, keyless signing stays. Two trust roots, one per forge, each
  with its own admission policy.
- **References are pinned.** A reusable workflow refers to its own nested workflows at the same
  tag, never `@main`. Callers pin `@<sha> # vX.Y.Z` and Renovate moves them.

### What changes per forge

Only the adapter: `forge: 'forgejo' | 'github'` in the shared config (both exist since 1.4.0), the
reusable release workflow published on that forge, and the Renovate job that reads it. GitLab and
Bitbucket stay P5 of the delivery plan: built when their first project arrives, with a conformance
run on a fixture repository.

## Owner decisions

| # | Question | Options | Recommendation |
| --- | --- | --- | --- |
| R1 | Release tool | A semantic-release, hardened · B knope pilot · C release-please | **A**: release-please cannot run on Forgejo; knope is promising but young, revisit at 1.0 |
| R2 | The four kinds and their branch shapes | A as above · B everything staged · C everything trunk | **A**: a package or image set has no staging consumer, so `development` there is overhead |
| R3 | Promotion | A fast-forward only, enforced · B merge commits plus a back-merge job | **A**: one rule, and divergence becomes impossible instead of repaired |
| R4 | Nine dead release paths | A archive the repos · B delete the `.github/workflows` and keep the repos · C revive the ones you still want | A for the ones you no longer use, C per repo otherwise; list below |
| R5 | `webgrip.nl` and `counterscale` versioning | A become Sites with rc/stable · B stay unversioned deploys | **A**: one recipe; staging previews already exist |

Owner answers, 2026-10-23:

- **R1: A**, semantic-release hardened, with a knope pilot alongside to compare on real repos
  ([VIK-2314](https://vikunja.webgrip.dev/tasks/2314)).
- **R2: open.** The owner sees value in release candidates for shared workflows and images. Proposed
  refinement: the branch shape follows **blast radius**, not kind. A repository is staged when a bad
  release breaks more than itself: services, sites, and the estate-wide packages and images
  (`workflows`, `renovate-config`, `semantic-release-config`, `infrastructure`, whose `ci-runner`
  and `agent-runner` run every CI job and agent Run). Each staged package or image needs one canary
  consumer on its `-rc` channel. Leaf packages (`frontend-toolkit`, `common-charts`,
  `telemetry-service`, templates, `ai-skills`) stay trunk.
- **R3: A**, fast-forward only, with one escape hatch for the case where it is not possible: when
  production needs a fix while `development` holds work that must not ship yet, the fix goes on a
  maintenance branch cut from the stable tag (`0.4.x`, a semantic-release maintenance range), which
  releases `0.4.1`; the same fix also lands on `development`. `main` still only fast-forwards.
- **R4: A**, archived through the repo-config model (`archived: true`, homelab `5ef7a5b9`) for the
  eight Forgejo repositories; `twitch_exporter` leads on GitHub and waits for GitHub repository
  settings to be modelled too.
- **R5: A.**

Dead release paths for R4: freshrss-application, searxng-application, invoiceninja-application,
backstage-application, ledgerflow, monitoring-platform, traefik-local-development,
whisperx-application, twitch_exporter.

## Fixes that do not wait for these decisions

These are defects against ADR-0069 as already accepted. Each is a board ticket under
[VIK-2070](https://vikunja.webgrip.dev/tasks/2070).

- `common-charts` consumers read GHCR, which stopped receiving releases at 1.0.13; point them at
  Harbor ([VIK-2309](https://vikunja.webgrip.dev/tasks/2309)).
- Ploeg's GitHub release clones the config from Forgejo (503 on 2026-10-23); it needs a copy that
  does not depend on the homelab ([VIK-2310](https://vikunja.webgrip.dev/tasks/2310)).
- No toolchain image ships config 1.4.0, and the `webgrip/workflows` defaults lag the published
  images; ship 1.4.0 and let Renovate move the defaults
  ([VIK-2311](https://vikunja.webgrip.dev/tasks/2311)).
- The `/omnigraph/i` Renovate rule meant for the omnigraph CLI also blocks automerge of
  `omnigraph-explorer` ([VIK-2312](https://vikunja.webgrip.dev/tasks/2312)).
- `webgrip/workflows` refers to its own nested workflows `@main` 29 times
  ([VIK-2313](https://vikunja.webgrip.dev/tasks/2313)).
- Image inputs are installed without lockfiles in six Dockerfiles
  ([VIK-2308](https://vikunja.webgrip.dev/tasks/2308)).

## Rollout, once decided

1. Shared config: tags-only, commit-lint failure, monorepo trains, `registry` input. Released as
   2.0.0, proven on `infrastructure` (image set) and Unfold (service).
2. Toolchain image with config 2.0.0 on Harbor and GHCR; workflows defaults on Renovate.
3. Per kind, one pull request per repository, in the order service, image set, package, site.
   Each repository is done when its next merge releases with no hand step and the consumer picks it
   up through Renovate.
4. Archive or revive the R4 list.

## Reproducibility

- Repository survey, 2026-10-23: bare blobless clones of each repository's leading forge, facts read
  from default-branch HEAD and, for runs, the anonymous Forgejo tasks API and `gh run list`. Private
  Forgejo repositories were found by name over SSH; any private repository not named in this RFC was
  not surveyed.
- Tool comparison, 2026-10-23: release and activity data from each project's GitHub API and primary
  documentation.
