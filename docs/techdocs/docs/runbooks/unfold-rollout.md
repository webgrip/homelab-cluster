# Know whether an Unfold rollout went well

The homelab runs every Unfold release candidate without a pull request: Flux follows the newest
signed `0.x.y-rc.N` chart on GHCR and upgrades the `unfold` HelmRelease, which carries Ploeg
([RFC: One delivery contract, P1c](../rfc/rfc-unfold-release-train.md#p1c-the-homelab-follows-the-candidate-channel)).
This page says where each rollout reports itself, what to do when one goes wrong, and how to hold a
candidate back.

## How a candidate reaches the homelab

1. The Unfold release workflow publishes the chart `ghcr.io/unfold-hq/charts/unfold:<version>` after
   its images, with their digests written into the chart's `values.yaml`, and signs it keyless with
   GitHub Actions OIDC.
2. Every two minutes the OCIRepository
   [`flux-system/unfold`](../../../../kubernetes/apps/ploeg/unfold/release/ocirepository.yaml) lists
   the chart tags on `ghcr.io` anonymously (the chart package is public), keeps
   the newest `0.x.y-rc.N`, and verifies its signature: the issuer must be
   `https://token.actions.githubusercontent.com` and the subject the `on_release_published.yml`
   workflow of `unfold-hq/unfold` at the tag `unfold-v<version>`. An unsigned chart, a chart signed by
   any other workflow, or a per-architecture tag is never stored.
3. The HelmRelease [`ploeg/unfold`](../../../../kubernetes/apps/ploeg/unfold/app/helmrelease.yaml)
   upgrades to the stored chart. Its Unfold and workspace images come from the chart by digest; the
   HelmRelease sets only the Harbor proxy repository. Helm waits for every workload to turn Ready,
   then runs the chart's Helm tests (`spec.test.enable`). A failed upgrade or a failed test rolls back
   to the previous release, up to three times; after that the HelmRelease stalls with
   `RetriesExceeded` until a person acts.

[`scripts/check_release_train.py`](../../../../scripts/check_release_train.py) (run in `e2e / Lint &
static validation`, with mutation cases in
[`scripts/test-release-train.sh`](../../../../scripts/test-release-train.sh)) keeps this shape:
no image pins in the HelmRelease, no exact chart pin, a filter that refuses per-architecture tags,
and anchored signature identities.

## Where a rollout reports itself

| Signal | What it says | Where it lands |
| --- | --- | --- |
| Flux events (Alert `flux-system/unfold-rollout`, Provider `vmalertmanager`) | a new chart was stored; the upgrade succeeded, failed or rolled back; a chart failed verification | Alertmanager. Failures (Flux severity `error`) go to the ntfy topic `alerts-critical` at urgent priority, everything else to `alerts-warning`. Neither sends a "resolved" message |
| Grafana annotations | the same events on dashboards | Provider `flux-system/grafana-annotations` |
| `UnfoldBehindLatestRelease` (critical) | Flux holds a newer signed chart than the HelmRelease has been Ready on, for 30 minutes | ntfy `alerts-critical`; rule in [delivery-verify](../../../../kubernetes/apps/observability/victoria-metrics/app/rules/prometheusrule-delivery-verify.yaml) |
| `UnfoldReleaseSourceNotReady` (warning) | Flux cannot list or verify the channel for 15 minutes, so no newer chart can arrive | ntfy `alerts-warning` |
| `FluxHelmReleaseNotReady` (warning) | the HelmRelease is not Ready for 15 minutes, `Stalled` included | ntfy `alerts-warning` |
| `UnfoldSmokeFailing` (warning) | `/healthz` does not report the Ploeg contract `compatible`, or `/api/auth/methods` (what the sign-in page reads) offers no OIDC sign-in, for 15 minutes | ntfy `alerts-warning`; probes `blackbox-unfold-ploeg-contract` and `blackbox-unfold-sign-in` |
| `DeliveryCandidateUnhealthy` (warning) | a revision less than an hour old has an unhealthy signal for 15 minutes, now including `smoke_failing` | ntfy `alerts-warning` |

A rollout went well when, within about fifteen minutes of the release tag, `alerts-warning` shows
`FluxHelmReleaseUpgradesucceeded` for the new version and nothing from the table above fires.

## Check by hand

```sh
flux -n flux-system get source oci unfold
flux -n ploeg get helmrelease unfold
kubectl -n ploeg get helmrelease unfold -o jsonpath='{.status.history[0].chartVersion} {.status.history[0].status}{"\n"}'
curl -s "https://unfold.<domain>/healthz"
```

The chart version in the source, the HelmRelease history and the `version` field of `/healthz` name
the same release when the rollout is done, and `/healthz` reports `"ploegContract":{"state":"compatible"`.
In Grafana, `delivery:release_newest_candidate:info` and `delivery:release_deployed_version:info`
name the stored and the running version.

## When a rollout failed

1. Read why: `kubectl -n ploeg describe helmrelease unfold`, then the events and the logs of the
   workload that did not turn Ready (`kubectl -n ploeg logs deploy/unfold --previous`).
2. Helm has already rolled back. If the next candidate fixes it, nothing else is needed: Flux takes
   it within two minutes of its publication.
3. To skip the bad candidate and let the next one through, add an exclusion to `spec.ref.semver` in
   [`ocirepository.yaml`](../../../../kubernetes/apps/ploeg/unfold/release/ocirepository.yaml), for
   example `">=0.0.0-0 <1.0.0-0, !=0.4.0-rc.137"`, and merge it (RFC D12).
4. To freeze the homelab on a known-good version, replace `semver` and `semverFilter` with that
   version's `tag` and `digest`. `check_release_train.py` fails on an exact pin on purpose, so a
   freeze is a visible, reviewed exception that a person reverts.
5. To retry the same candidate after fixing something outside the chart (a secret, a database):
   `flux -n ploeg reconcile helmrelease unfold --force`.

## When the channel itself is broken

`UnfoldReleaseSourceNotReady` means Flux runs the last chart it verified and sees nothing newer.

- `VerificationError`: check the signature with the same identity Flux uses:

  ```sh
  cosign verify ghcr.io/unfold-hq/charts/unfold:<version> \
    --certificate-oidc-issuer-regexp '^https://token\.actions\.githubusercontent\.com$' \
    --certificate-identity-regexp '^https://github\.com/unfold-hq/unfold/\.github/workflows/on_release_published\.yml@refs/tags/unfold-v0\.\d+\.\d+-rc\.\d+$'
  ```

  A release that signed nothing, or signed from another workflow, stays refused until the release is
  fixed in `unfold-hq/unfold`.
- An authentication or `DENIED` error: Flux reads `ghcr.io/unfold-hq/charts/unfold` without
  credentials, so the package must stay public on GitHub. Check it with
  `crane ls ghcr.io/unfold-hq/charts/unfold` from a machine with no registry login.

## The Helm test

`spec.test.enable` is on, with `ignoreFailures: false`, so a failing chart test rolls the upgrade
back. The Unfold chart has no test hook yet; a `templates/tests/smoke.yaml` is being added in
`unfold-hq/unfold`. Until a chart release carries it, Helm reports no tests, `spec.test.enable` is a
no-op, and the smoke probes above are the only post-rollout check: they alert but do not roll back.
