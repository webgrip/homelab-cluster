# RFC: Gating the verify policies — three waves the promotion machinery cannot gate

> Status: **Proposed** · Date: 2026-08-04 · Spawned by the [Kyverno estate audit](rfc-kyverno-audit-enforce-hardening.md#audit-2026-08-04)

> **2026-10-09:** `image-verify-audit` and `image-attestations-audit` were deleted, so waves 6,
> 13 and 14 no longer exist ([why](../general/supply-chain-pipeline.md#retired-the-ghcr-verification-policies)).
> What this RFC still governs is `image-verify-harbor-audit` and `image-cve-budget-audit`.

> **TL;DR.** [ADR-0032](../adr/adr-0032-kyverno-enforce-promotion-policy.md) gates every
> Audit→Enforce promotion on two pieces of evidence: a clean PolicyReport, and (since 2026-08-03)
> an offline `kyverno apply` sweep. **Neither works for a `verifyImages` policy.** They set
> `background: false`, so they produce almost no PolicyReport data — **8 results across all four
> of them**, against 960 for a single Audit policy — and the CLI cannot evaluate them offline at
> all, because signature verification needs registry access. That is waves **6, 13 and 14**: the
> only enforcement decisions in the estate that would currently be made *blind*. This RFC builds
> the missing evidence source. It also records an inverted failure posture found in the same
> audit: two of the four verify policies run `failurePolicy: Fail`, the exact configuration
> [ADR-0033](../adr/adr-0033-approved-registries-stays-audit.md) rejected for the other two.

## Why

Verified state, 2026-08-04:

| Policy | action | `failurePolicy` | timeout | scope | PolicyReport results |
| --- | --- | --- | --- | --- | --- |
| `image-verify-harbor-audit` | Audit | `Ignore` | 30s | `harbor.webgrip.dev/webgrip/*` | 5 |
| `image-cve-budget-audit` | Audit | `Ignore` | 30s | `harbor.webgrip.dev/webgrip/*` | 1 |
| `image-verify-audit` | Audit | **`Fail`** | 30s | `ghcr.io/webgrip/*`, `ghcr.io/kyverno/*` | 2 |
| `image-attestations-audit` | Audit | **`Fail`** | 30s | `ghcr.io/webgrip/*` | **0 — absent** |

For scale: the sweep corpus is 456 pods, and `workload-advanced-hardening-audit` has 960
PolicyReport results. Eight results across four policies is not "clean" — it is **no data**. The
handful that exist are the residue of pods that happened to be admitted while the policy was live.

Two problems follow, and one worth recording:

1. **Both gates are inoperative, in different ways.** `background: false` is *correct* for these
   policies — `verifyImages` needs admission context, and background-scanning them would hammer
   the registry — but it means the background scanner never populates reports, so "clean
   PolicyReport" is trivially and meaninglessly true. And the offline sweep, which rescued waves
   3, 7, 10 and 12 from exactly this class of false confidence, evaluates *nothing* for
   `verifyImages`: the CLI has no registry credentials and no network contract. The audit could
   only mark all three waves **UNSWEPT**, never clean.
2. **The prerequisite these waves actually have is an inventory question, not a report question.**
   `image-cve-budget-audit` states it in its own description: promote *"once every running webgrip
   image has been released through the wired gate — images published before that have no such
   attestation and would be refused."* That is answerable — enumerate the running first-party
   images and check each for the required signature/attestation — but nothing in the repo answers
   it today, and no PolicyReport ever will.
3. **The failure posture is inverted between the two pairs.** ADR-0033 kept `image-verify-harbor`
   in Audit specifically because `failurePolicy: Fail` would make Harbor and OpenBao a
   cluster-wide admission SPOF. The two Harbor-scoped policies duly run `Ignore`. The two
   **ghcr-scoped** policies run **`Fail`** — meaning a slow or unreachable `ghcr.io`, or a Kyverno
   webhook hiccup, *denies admission* for matching pods, with a 30-second timeout, while the
   policy is nominally in Audit. `failurePolicy` governs webhook **unavailability**, not the
   policy verdict, so "Audit" does not protect you here.

   **This is currently dormant, not live:** no running pod uses a `ghcr.io/webgrip/*` image (all
   first-party workloads pull from Harbor) and Kyverno pulls its own images from
   `reg.kyverno.io`, not `ghcr.io/kyverno/*`. So the rules match nothing today. It is a landmine,
   not a fire — but `ghcr.io/kyverno/*` gating admission of Kyverno's own pods is a cold-start
   hazard that should not be one dependency change away.

## Proposal

1. **Build the evidence source these waves need: a verification inventory sweep.** A CronJob in
   `security` that enumerates every distinct image running in the cluster, filters to the
   first-party references each verify policy matches, and runs the *same* verification the policy
   would — `cosign verify` / `verify-attestation` against the `cosign-webgrip-pub` ConfigMap, with
   the Harbor pull robot's credentials — then publishes pass/fail per image. Output goes to
   metrics (so it can be alerted and dashboarded like everything else) rather than to a
   PolicyReport, because it is not an admission decision.

   This is the missing third gate. It answers the real question — *would promoting this policy
   refuse anything currently running?* — for the one policy family where neither existing gate
   can. It reuses infrastructure that already exists (the pull robot, the pubkey ConfigMap, the
   `provisioner-job` pattern) and it is read-only.
2. **Gate waves 6, 13 and 14 on that sweep reading zero unverified images for the policy's own
   scope, sustained across at least one release cycle** — not one green run. A single clean pass
   proves the images in the cluster right now are signed; a sustained clean run proves the
   *pipeline* is producing them, which is what promotion actually depends on.
3. **Promote in the order the audit's blast radii imply**, narrowest first: wave 6
   (`verify-kyverno-images-keyless`, third-party, tiny scope) → wave 13
   (`verify-webgrip-images`) → wave 14 (`image-attestations`). Each keeps the
   verification-infrastructure namespaces carved out, so verification never gates the components
   that produce verification.
4. **Correct the failure posture as its own commit, before any promotion.** Bring
   `image-verify-audit` and `image-attestations-audit` to `failurePolicy: Ignore` to match
   ADR-0033's reasoning and their Harbor-scoped siblings, or record explicitly why `ghcr.io`
   warrants the opposite. Either is defensible; the current split appears to be drift rather than
   a decision, and it should stop being ambiguous while it is still dormant.
5. **Extend the audit's UNSWEPT accounting into the harness.** `check-kyverno-test-coverage.sh`
   should know that a `verifyImages` policy cannot be covered by a CLI fail-case, and require the
   inventory sweep instead — so this class can never again look covered because the check did not
   apply to it. This is the same hole the harness already closed once for its hardcoded allowlist.

## Risks

- **The sweep is a second implementation of the verification logic**, and can drift from the
  policy it gates. Mitigate by pinning it to the same Kyverno CLI image the tests use and driving
  it from the policies themselves where possible, rather than re-encoding the trust config.
- **Registry rate limits and cold caches.** Verifying every distinct image on a schedule costs
  registry calls. Scope it to first-party references only (a handful today) and cache by digest.
- **It could become a false comfort of its own.** The sweep proves signatures exist for images
  *currently running*. It says nothing about an image that will be deployed tomorrow — which is
  precisely why step 2 requires a sustained clean run across a release cycle, and why the
  promotion still needs an admission-cycle watch after the flip.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | An inventory sweep is the third promotion gate, for policies the other two cannot evaluate (new) |
| candidate | — | `failurePolicy` posture for verify policies: uniform `Ignore`, or a recorded exception (new) |
| candidate | — | Verify-wave order and the verification-infrastructure carve-out (new) |

## Out of scope

- The trust anchor itself (OpenBao Transit) and the DT-vs-GUAC question — those belong to
  [RFC: image signing & verification](rfc-image-signing-verification.md), which this RFC
  supplies the missing gate for.
- The CVE-budget *predicate* and its OpenVEX handling — already designed and documented in
  `image-cve-budget-audit`; this RFC does not revisit it.
- `require-approved-registries` — stays Audit, decided in
  [ADR-0033](../adr/adr-0033-approved-registries-stays-audit.md).
- Migrating these policies to `ImageValidatingPolicy` — [CEL migration RFC](rfc-kyverno-cel-migration.md),
  Wave D, sequenced after this settles.

## References

- [ADR-0032 — Kyverno enforce promotion policy](../adr/adr-0032-kyverno-enforce-promotion-policy.md)
  (the two gates that do not apply here) ·
  [ADR-0033](../adr/adr-0033-approved-registries-stays-audit.md) (the `failurePolicy: Fail` SPOF
  reasoning this RFC applies consistently)
- [RFC: Kyverno audit→enforce hardening](rfc-kyverno-audit-enforce-hardening.md#audit-2026-08-04)
  — the audit that marked these waves UNSWEPT
- [RFC: Image signing & verification](rfc-image-signing-verification.md) — the enforce path that
  had "no owner"; this is its gate
