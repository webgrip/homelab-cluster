---
status: accepted
date: 2026-10-18
decision-makers: Ryan Grippeling
---

# Image admission refuses unsigned first-party images; the CVE budget follows on evidence

## Context and Problem Statement

Admission checked image provenance but blocked nothing. `image-verify-harbor-audit` verified the
cosign signature and the CycloneDX SBOM attestation of `harbor.${SECRET_DOMAIN}/webgrip/*` images in
Audit, `image-cve-budget-audit` checked a signed CVE-budget verdict in Audit, and Ploeg's images
(`harbor.${SECRET_DOMAIN}/ghcr/ploeg-hq/*`, proxied from GHCR) were checked by nothing. The
[Kyverno RFC](../rfc/rfc-kyverno-audit-enforce-hardening.md) listed the Harbor signature policy as
"stays Audit" and [the verify-gating RFC](../rfc/rfc-verify-policy-gating.md) found that neither
promotion gate of [ADR-0032](adr-0032-kyverno-enforce-promotion-policy.md) can see a `verifyImages`
policy. The question: which image checks can block admission now, and what has to be true before the
rest do?

What the cluster showed on 2026-10-18 (read-only `kubectl`, `cosign verify` with the published
`cosign-webgrip-pub` key, and the Kyverno CLI against Harbor):

* **Every first-party Harbor image that runs or is launched is signed.** Seven images: `ci-runner`,
  `agent-runner`, `omnigraph-explorer`, `omnigraph-explorer-review`, `unfold` (rc.91),
  `unfold-agent` (rc.82 and rc.91). The 12 `image-verify-harbor-audit` failures (Forgejo runners,
  `glide-cve-rescan`) are not signature failures: `ci-runner`'s SBOM attestation is 13–17 MB and
  Kyverno stops at its 8 MiB context limit (`context size limit exceeded`), and that failed result is
  cached as "unverified image" for later pods.
* **No image carries a passing CVE-budget verdict.** `unfold`, `unfold-agent` and
  `omnigraph-explorer` carry no `https://webgrip.dev/attestations/cve-budget/v1` attestation at all:
  the shared `cosign-sign-attest` composite in `webgrip/workflows` never attested the
  `cve-budget.json` that Unfold's cve-gate writes (its `webgrip/infrastructure` twin does).
  `ci-runner` and `agent-runner` carry one, with `mode: warn` and `verdict: fail` (`ci-runner`: 15
  critical against a budget of 8).
* **Ploeg releases are not signed.** `ghcr.io/ploeg-hq/ploegd` and `claude-runner` up to rc.31 have
  only BuildKit's unsigned in-index SBOM and provenance; Ploeg's release notes state signing is not
  configured.
* **Erfbeeld's images are unsigned** (`erfbeeld-backend`, `erfbeeld-web` 1.0.3). Erfbeeld is not
  wired into `kubernetes/apps/kustomization.yaml`, so nothing runs them today.

## Decision Drivers

* Block what is provably safe to block today; never refuse a running workload on the strength of an
  unrecorded assumption.
* A `verifyImages` policy needs a gate that actually evaluates signatures, not a PolicyReport count.
* An outage of Kyverno must not stop every Pod in the cluster (the SPOF reasoning of
  [ADR-0033](adr-0033-approved-registries-stays-audit.md)).
* Fix the producer of missing evidence rather than loosening the consumer.

## Considered Options

* Enforce the signature now in its own policy; keep SBOM and CVE-budget checks in Audit until their
  evidence exists; verify Ploeg keyless
* Flip `image-verify-harbor-audit` to Enforce as written (signature plus SBOM)
* Enforce signature, SBOM and CVE budget together
* Keep everything in Audit

## Decision Outcome

Chosen option: "Enforce the signature now in its own policy; keep SBOM and CVE-budget checks in
Audit until their evidence exists; verify Ploeg keyless", because it is the only option that blocks
something today without refusing a running workload.

1. **Signatures are enforced.**
   [`image-verify-harbor-enforce`](../../../../kubernetes/apps/kyverno/policies/app/image-verify-harbor-enforce.yaml)
   refuses a Pod (and, through autogen, a Deployment, StatefulSet or DaemonSet) whose
   `harbor.${SECRET_DOMAIN}/webgrip/*` image digest has no cosign signature from the OpenBao Transit
   key. It checks the signature only, so the SBOM size limit cannot refuse a signed image, and it
   caches verdicts per digest.
2. **`failurePolicy` stays `Ignore`.** When Kyverno itself is down or times out, Pods are admitted
   unchecked. With `Fail`, a Kyverno outage would stop every Pod creation in the cluster, including
   Kyverno's own recovery. The residual risk is accepted: an attacker would have to take Kyverno down
   first. A verification that runs and fails (no signature, wrong key, key ConfigMap missing) is a
   refusal.
3. **The SBOM attestation stays Audit.**
   [`image-verify-harbor-audit`](../../../../kubernetes/apps/kyverno/policies/app/image-verify-harbor-audit.yaml)
   now checks only the CycloneDX attestation. SBOM content is Dependency-Track's job
   ([ADR-0064](adr-0064-dependency-track-only-sbom-platform.md)); refusing admission over SBOM size
   buys nothing.
4. **The CVE budget stays Audit until four things hold**, checked in this order:
   1. the producer attests the verdict: [webgrip/workflows#77](https://forgejo.webgrip.dev/webgrip/workflows/pulls/77)
      adds the attestation to the shared composite, and each first-party release adopts that version;
   2. every first-party image that runs or is launched carries a verdict with `mode: enforce` and
      `verdict: pass`, which means `ci-runner` and `agent-runner` either meet or re-measure their
      budgets in `webgrip/infrastructure`;
   3. Kyverno can read the verdict: it loads every attestation of an image to pick one predicate, so
      `ci-runner`'s 13–17 MB SBOM breaks the CVE check too. Either the SBOM shrinks or Kyverno's
      context limit is raised, measured against admission-controller memory first;
   4. the image admission sweep (point 6), extended to the CVE predicate, reads zero refusals across
      one release cycle of every first-party image.
5. **Ploeg's images are verified keyless.** [ploeg-hq/ploeg#186](https://github.com/ploeg-hq/ploeg/pull/186)
   signs `ploegd`, `claude-runner` and the chart with keyless cosign from the release workflow.
   [`image-verify-ploeg-hq-audit`](../../../../kubernetes/apps/kyverno/policies/app/image-verify-ploeg-hq-audit.yaml)
   reports Ploeg images, through the Harbor proxy or from GHCR, that lack a signature with issuer
   `https://token.actions.githubusercontent.com` and subject
   `https://github.com/ploeg-hq/ploeg/.github/workflows/release.yml@refs/{heads/development,heads/main,tags/v0.x.y[-rc.N]}`.
   It moves to Enforce once a signed Ploeg release is the deployed pin and the sweep passes for every
   Ploeg image the cluster runs or launches.
6. **The promotion gate for `verifyImages` policies is an online engine run.**
   [`scripts/verify-image-admission.sh`](../../../../scripts/verify-image-admission.sh) `--live`
   collects every digest-pinned first-party image that runs, is templated in a controller, or is
   named by a HelmRelease value ending in `Image` (images the applications launch themselves), and
   runs the Kyverno engine with the enforcing policy against Harbor, the way admission will. It
   exits non-zero if any image would be refused.
   [`check-kyverno-test-coverage.sh`](../../../../scripts/check-kyverno-test-coverage.sh) now fails
   when an enforcing `verifyImages` policy is not run by that script, and the CLI suite keeps a skip
   case for third-party images and a fail case for an image whose signature cannot be proven.

### Consequences

* Good, because an image pushed to Harbor's `webgrip` project without the release pipeline's
  signature can no longer run, whoever holds the push robot.
* Good, because the gate that opened this promotion is repeatable and evaluates signatures, closing
  the "UNSWEPT" class the verify-gating RFC described.
* Good, because the missing CVE evidence is fixed where it is produced, not waived where it is read.
* Bad, because Harbor becomes an admission dependency for first-party Pods: if Harbor is unreachable
  while Kyverno is up, those Pods are refused. Harbor serving their layers is already required for a
  cold pull, so the new exposure is limited to nodes that still had the image cached.
* Bad, because re-enabling Erfbeeld now needs its release pipeline to sign first.
* Bad, because Kyverno 1.19 does not verify image volumes (`volumes[].image.reference`): a Pod with
  a signed container and an unsigned image volume is admitted (tested with the 1.18.2 and 1.19.1
  CLIs). Unfold mounts the unsigned `unfold-delivery-inputs` that way today. Signing that artifact
  is follow-up work; if a later Kyverno starts checking image volumes, that Pod would be refused
  until it is signed.
* Bad, because a Kyverno outage admits unsigned images (point 2).

### Confirmation

* `scripts/verify-image-admission.sh --live` exits 0. On 2026-10-18 it passed all 7 first-party
  images; run with the unsigned `erfbeeld-web:1.0.3` digest added, it reported `fail` for that image
  and exited 1.
* `mise exec -- just kyverno-test` is green, and changing the `first-party-unprovable` expectation
  in `tests/cli/image-verification` from `fail` to `pass` turns it red (191 passed, 2 failed).
* `scripts/check-kyverno-test-coverage.sh` is green, and renaming the policy path inside the sweep
  script makes it fail with the `verifyImages` message.
* After the merge, PolicyReports and admission reports show no `fail` result for
  `image-verify-harbor-enforce`, and the next Forgejo runner, Unfold and agent-runner Pods start.

## Pros and Cons of the Options

### Enforce the signature now in its own policy; SBOM and CVE in Audit; Ploeg keyless

* Good, because every image it can refuse was checked against it before the flip.
* Neutral, because it adds two policies where there was one.
* Bad, because the CVE budget still only reports.

### Flip `image-verify-harbor-audit` to Enforce as written

* Bad, because the SBOM size limit would refuse every Forgejo runner and `glide-cve-rescan` Pod:
  CI stops while every image involved is correctly signed.

### Enforce signature, SBOM and CVE budget together

* Bad, because no running first-party image has a passing verdict: it refuses Unfold, the runners
  and the agent runtime.

### Keep everything in Audit

* Bad, because a policy that only reports does not stop an unsigned image, and the evidence to block
  safely already exists for signatures.

## More Information

* Technical story: [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md);
  gate design from [RFC: verify-policy gating](../rfc/rfc-verify-policy-gating.md).
* Producer fixes: [webgrip/workflows#77](https://forgejo.webgrip.dev/webgrip/workflows/pulls/77)
  (CVE-budget attestation) and [ploeg-hq/ploeg#186](https://github.com/ploeg-hq/ploeg/pull/186)
  (keyless release signing).
* Partly reverses the "stays Audit" verdict for `image-verify-harbor` in the Kyverno RFC; keeps
  [ADR-0033](adr-0033-approved-registries-stays-audit.md)'s `failurePolicy` reasoning.
* Not decided here: moving these policies to `ImageValidatingPolicy` (the legacy `kyverno.io/v1`
  API is deprecated); that is wave D of the [CEL migration RFC](../rfc/rfc-kyverno-cel-migration.md).
* 2026-10-18: accepted by Ryan Grippeling.
