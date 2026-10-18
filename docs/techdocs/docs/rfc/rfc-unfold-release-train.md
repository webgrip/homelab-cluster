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

### P4 verify

P4 lands in two slices. The first detects and notifies; the second reverts.

**Slice 1: detection (landed).** The rules are in
`kubernetes/apps/observability/victoria-metrics/app/rules/prometheusrule-delivery-verify.yaml`, with
vmalert-tool unit tests in `scripts/vmalert-tests/` (run `./scripts/test-vmalert-rules.sh`). Each
alert has a case that must fire and a case that must not.

| Series or alert | Meaning | Source |
| --- | --- | --- |
| `delivery:release_revision:current{release, revision}` | the chart version Flux is applying for `ploeg` or `unfold` | flux-operator `flux_resource_info` |
| `delivery:release_deployed:info{release, revision}` | that version is applied and Ready; when a revision first shows up here is when it went live (use it as a Grafana annotation) | same, `ready="True"` |
| `delivery:release_running_image:info{release, image_id}` | the image digest the Deployment pods actually run | kube-state-metrics `kube_pod_container_info` |
| `delivery:release_candidate:fresh{release, revision}` | the revision was not there an hour ago | `flux_resource_info` offset 1h |
| `delivery:release_unhealthy:signal{release, signal}` | `release_not_ready`, `replicas_unavailable`, `container_restarting` (two or more restarts in 15m), `route_probe_failing` (Unfold only; Ploeg has no route probe) | Flux, kube-state-metrics, blackbox |
| `DeliveryCandidateUnhealthy` | a fresh revision has had an unhealthy signal for 15m; carries `release`, `revision`, `signal` | the two above |
| `DeliveryVerifySignalMissing` | the layer has gone blind for a release | absent for 30m |

Both alerts are `severity: warning` and reach ntfy through the warning route in
`vmalertmanager-config`. A broken candidate pages about 16 to 20 minutes after Flux applies it. The
15-minute hold comes from the data: over the seven days before 2026-10-18, the longest stretch where
a healthy Unfold rollout looked unready was 11 minutes. A revision older than an hour is no longer a
candidate. From then on the steady-state alerts (`FluxHelmReleaseNotReady`, `SyntheticRouteDown`,
`AppContainerCrashLooping`) cover it, and they also fire during the first hour, next to this one.

**Slice 2: revert (design, not built).**

- *What reverts.* The Renovate commit on `main` that moved the pins: the OCIRepository `tag` and
  `digest`, and the image `tag` and `digest` in `helmrelease.yaml` (kept in lockstep by
  `scripts/check_release_lockstep.py`). The revert is a `git revert` of that commit, and Flux
  applies it. Helm rollback, `flux suspend` and `kubectl` patches are out, because git would still
  name the bad version and Flux would put it back on the next reconcile.
- *Trigger.* An Alertmanager route for `alertname="DeliveryCandidateUnhealthy"` sends to a webhook
  receiver in the cluster. The receiver finds the commit that introduced `revision` in the pin
  files and reverts it.
- *Guards.* Revert only when that commit is Renovate's and is still the latest change to those
  files. Revert each revision once. Never revert past a forward-only database migration: Ploeg
  would first have to expose its schema version so the receiver can refuse. If Ploeg and Unfold
  moved together, revert the pair.
- *Keeping it reverted.* Renovate proposes the same version again after a revert. The bad version
  has to land in a list that Renovate reads (an `allowedVersions` exclusion in the channel preset),
  or the next rc has to supersede it. The owner chooses which.
- *Deploy event.* On success, the first sample of `delivery:release_deployed:info` for a revision is
  the record. Slice 2 can also write it as a Ploeg deploy event (Ploeg ADR-0047).
- *Credential a person must provide.* `main` is protected (ADR-0050): only `ryangr0` may push, and
  only `ryangr0` and `renovate` may merge, after the five `e2e /` checks. So the receiver needs a
  Forgejo token that may open and merge a revert PR on `homelab-cluster`, scoped to that one
  repository. It is stored in OpenBao KV and delivered by an ExternalSecret (ADR-0055). The owner
  picks the identity: reuse `renovate` (already on the merge whitelist, but it mixes two writers
  under one name) or add a dedicated bot (which runs against the no-new-bot-accounts decision). A
  revert PR also waits for the e2e checks, which adds their run time to the rollback.

### P1b events, not schedules

Proposed 2026-10-18. The owner rejected the hourly Renovate schedule as the way a release moves
along the chain. On 2026-10-18 Ploeg `v0.2.0-rc.27` published itself at 07:08 and then waited for
the `33 * * * *` run of RenovateJob `webgrip-forgejo`; every hop pays that wait twice, once to
open the bump and once to merge it, because Renovate merges only while a run is active.

Checked against the deployed renovate-operator 5.2.0, Renovate 44.165.2 and Forgejo 15.0.9:

- `POST /webhook/v1/schedule?job=<job>&namespace=renovate&project=<org%2Frepo>` schedules any
  project the job already discovered, at priority 1, authenticated by a bearer token or an HMAC
  of the body. The secret may hold several comma-separated tokens. `webgrip/unfold` and
  `webgrip/homelab-cluster` are both projects of `webgrip-forgejo`.
- A trigger for a project that is running is dropped and still answered 200, so each trigger
  repeats once after 20 minutes. The schedule stays as the backstop.
- With `platformAutomerge`, Renovate asks Forgejo to merge when checks succeed as it opens the
  PR, and Forgejo merges on the last required status. Forgejo gates only on the branch's
  required contexts.

| Hop | Trigger | Latency |
| --- | --- | --- |
| Ploeg bundle published → Unfold bump | last step of Ploeg's `contract-bundle.yml` POSTs `/schedule` for `webgrip/unfold` over a public route limited to that path, job and project | minutes |
| Unfold bump → merged | `platformAutomerge` on Unfold's Ploeg group | on the last required check |
| Unfold release distributed → homelab bump | a job after Unfold's distribute step POSTs `/schedule` for `webgrip/homelab-cluster` over the LAN route | the running executor, then one run |
| Homelab bump → merged | `platformAutomerge` on the `ploeg-unfold-release` group | on the last required check |

Prerequisites, in order, because a missing required context would let a red PR merge:

1. Homelab `main` requires all five `e2e /` contexts; on 2026-10-18 it required four, without
   `e2e / Omnigraph and brain tests`.
2. Unfold `development` requires `ploeg-docs`, the check that holds a Ploeg bump whose vocabulary
   clashes with Unfold's; on 2026-10-18 it did not.
3. Two new trigger tokens in OpenBao `renovate/webhook-auth` (`ploeg_github`, `forgejo_ci`),
   joined into the operator's secret by its ExternalSecret; the PushSecret that writes back to
   `token` goes, or the list would grow on every sync. Ploeg holds its token as the repository
   secret `RENOVATE_TRIGGER_TOKEN` and the URL as the variable `RENOVATE_TRIGGER_URL`, so a fork
   without them skips the step.

The public route is new exposure: it can only schedule one Renovate run for `webgrip/unfold`.
Whether Envoy matches the encoded project query before or after decoding is tested both ways
before it is relied on: another project gets 404 from the route, `webgrip/unfold` gets 200.
Upstream, the operator could remember a trigger that arrives while a project runs, which would
remove the repeat.

Implementation runs in a separate work stream; its first slice is the homelab branch
`fix/renovate-ploeg-unfold-release`.

## Risks

- **More tags.** Every releasable Ploeg merge is a candidate; ADR-0028 already treats candidates as
  disposable.
- **A bad candidate lands without a person.** CI in each repository, the homelab's `e2e /` checks and
  the verify layer stand in its way.
- **Release tokens per forge.** Each adapter needs a write token on its own forge, scoped to one
  repository, stored in OpenBao and delivered through the existing bridge (ADR-0055).
