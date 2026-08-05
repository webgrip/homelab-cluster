# RFC: Third-party images — the 95% of the fleet with no provenance

> Status: **Proposed** · Date: 2026-08-05 · Sibling of [image signing & verification](rfc-image-signing-verification.md) (first-party) and [verify-policy gating](rfc-verify-policy-gating.md)

> **TL;DR.** The first-party supply chain is genuinely strong: OpenBao Transit signing, CycloneDX
> SBOM attestation, an OpenVEX-aware CVE-budget verdict, three Kyverno verify policies. It covers
> **7 of 151 distinct images**. The other **144 are third-party**, and for them we have digest
> pinning (with 17 namespaces excluded — **74 image references are unpinned**), a registry-drift
> audit that is deliberately never enforced (ADR-0033), and trivy-operator scanning that produces
> **117 critical and 2,165 high findings** which gate nothing at all. The single biggest structural
> problem is that **114 of the 144 bypass Harbor entirely** — they pull straight from `docker.io`,
> `ghcr.io`, `quay.io`, `registry.k8s.io`, `reg.kyverno.io`. You cannot gate a path you do not
> control, so routing comes first and everything else is sequenced behind it.

## Why

Verified inventory, 2026-08-05 (from the 455-pod audit corpus):

| Fact | Value |
| --- | --- |
| Distinct images running | 151 |
| First-party (`webgrip/*`) | **7** |
| Third-party | **144** |
| Pulled through Harbor (proxy or first-party) | ~30 |
| Pulled **direct from upstream** | **~114** |
| Image refs without a digest | **74 of 152** |
| trivy-operator VulnerabilityReports | 36 |
| Critical / High / Medium findings | **117 / 2,165 / 2,716** |
| SBOMReports | 247 |
| Admission gates keyed on any of the above | **0** |

Three specific things this makes true:

1. **The scan data is decorative.** trivy-operator has been running, producing reports and SBOMs,
   and nothing consumes them for a decision. The worst offender is `guacsec/guac:v1.0.1` at 227
   critical+high — the supply-chain analysis tool is the least secure thing in the cluster.
   `alpine/k8s:1.36.2` at 208 is second, and it is what the CNPG backup-drill CronJobs run.
2. **Digest pinning is enforced where it is easy and absent where it matters.** The 17-namespace
   `NotIn` exclusion on `require-image-digest` covers exactly the infrastructure namespaces —
   `longhorn-system`, `cnpg-system`, `kube-system`, `security`, `observability` — which is where
   the unpinned tags live (`docker.io/longhornio/csi-*`, `docker.io/grafana/*`,
   `docker.io/dependencytrack/*`). Those are the images with node-level privilege.
3. **Registry sovereignty is an audit signal by decision, and the decision is being outvoted by
   reality.** ADR-0033 keeps `require-approved-registries` in Audit as a drift signal. It reports
   41. That is not drift any more; it is the steady state, because most charts default to upstream
   registries and nothing rewrites them.

## What the field actually does

Four patterns, from the research; they are complements, not alternatives:

- **Route everything through one registry.** A pull-through cache (Harbor here) is the precondition
  for scanning, signing, retention, and being able to keep running when an upstream registry rate-limits
  or disappears. We built this and use it for ~20% of images.
- **Verify signatures where they exist, and only there.** Sigstore adoption upstream is real but
  uneven — Kyverno, Flux and Cilium publish keyless signatures; a great many images publish
  nothing. The workable posture is **tiered**: verify what is verifiable, require digest pinning
  everywhere else. A uniform "all images must be signed" rule is unshippable against this fleet.
- **Turn scan results into an admission decision.** The established pattern is Kyverno reading
  trivy-operator's `VulnerabilityReport` CRs and denying on threshold — the same shape as our
  existing first-party `cve-budget` gate, but sourced from in-cluster scans instead of a
  build-time attestation.
- **Reduce the surface instead of cataloguing it.** Hardened minimal bases
  ([Chainguard](https://images.chainguard.dev/), Docker Hardened Images) for things we build, and
  [Copacetic](https://github.com/project-copacetic/copacetic) (CNCF sandbox) to patch OS packages
  directly into third-party images we cannot replace and cannot wait for upstream to fix.

## Proposal

Four phases, strictly ordered. Each is independently useful and independently revertible.

### Phase 1 — Routing (prerequisite for everything else)

Bring the ~114 direct-pull images through the Harbor proxy cache. Mechanically this is rewriting
chart `image.registry`/`repository` values to `harbor.webgrip.dev/<proxy>/…`, which is the same
edit `require-approved-registries` has been reporting for months — the rule was right, it just had
no execution plan behind it.

Do it in dependency order, most-privileged last: application namespaces → observability →
`cnpg-system`/`longhorn-system` → `kube-system`. **Harbor becomes a hard pull dependency for
anything routed through it**, so this trades resilience-against-Harbor-outage for control; that
trade must be recorded, and it argues for doing `kube-system` and the storage layer late or never.
Note the existing precedent: Spegel already mirrors pulls peer-to-peer, which softens a Harbor
outage considerably.

Exit criterion: `require-approved-registries` FAIL count drops from 41 toward the deliberate
residue, and ADR-0033 gets revisited — not to enforce it, but to say what the remaining exceptions
are and why.

### Phase 2 — Tiered verification

1. **Inventory what is actually signed.** A one-off sweep running `cosign verify` /
   `cosign verify-attestation` against all 144 third-party images, recording signature presence,
   the signing identity, and whether an SBOM or provenance attestation exists. This is the missing
   fact base; everything below depends on it, and it reuses the inventory-sweep machinery proposed
   in [verify-policy gating](rfc-verify-policy-gating.md).
2. **Extend `image-verify-audit` per verified publisher.** It already does exactly this for
   `ghcr.io/kyverno/*` (keyless). Each publisher confirmed signed in step 1 becomes one more rule
   with its own Fulcio identity/issuer, Audit first, promoted individually.
3. **Close the digest hole.** Narrow the 17-namespace exclusion on `require-image-digest`
   namespace by namespace as each is routed and pinned. Renovate already keeps digests fresh, so
   the maintenance cost is near zero — the exclusion exists for historical reasons, not current ones.

### Phase 3 — Make the scan data load-bearing

Add a Kyverno rule that reads trivy-operator `VulnerabilityReport` CRs via an `apiCall` context
and denies on a critical-count threshold, mirroring the first-party `cve-budget` shape. **Audit
first, and expect it to stay Audit for a long time** — with 117 criticals live, enforcing it on day
one would deny most of the cluster.

The honest sequencing is: this rule is a *reporting* mechanism until the count is driven down by
Phase 4, and only then a gate. Two caveats worth writing into the rule from the start:

- It must be **VEX-aware**, or it will be ignored within a week. The first-party gate already
  applies reviewed OpenVEX statements; third-party findings need the same treatment or the number
  never moves for good reasons (unreachable code paths, non-applicable OS packages).
- `apiCall` rules surface as `error`, never `fail`, in an offline sweep — so this rule needs the
  direct-`kubectl` check documented alongside it, per the audit gate note.

Also: **36 VulnerabilityReports against 151 distinct images is not full coverage.** Establish what
trivy-operator is and is not scanning before treating its output as an inventory.

### Phase 4 — Shrink the surface

- **Hardened bases for first-party builds.** Seven images; moving them to Wolfi/Chainguard-style
  minimal bases is small work with a large CVE delta, and it is entirely within our control.
- **Copacetic for the immovable third-party ones.** `guacsec/guac` at 227 and `alpine/k8s` at 208
  are the two that matter. Copa patches OS packages directly into an image using the Trivy report
  we already generate, producing a new layer without waiting for upstream — and the patched image
  lands in Harbor, where we sign it ourselves. That closes a real loop: **a third-party image we
  have patched and signed becomes a first-party artifact** and inherits the existing verification
  chain.
- **Replace rather than patch where an alternative exists** — `alpine/k8s` in the CNPG drills is a
  kitchen-sink image used for `kubectl` and `psql`; a minimal purpose-built image would drop most
  of its 208 findings and is a couple of hours of work.

## Risks

- **Phase 1 makes Harbor a pull-path dependency.** Mitigated by Spegel's P2P mirroring and by
  keeping the most critical namespaces on direct pulls until the rest is proven.
- **Phase 3 produces a very large number that nobody acts on.** This is the real failure mode —
  the same one that made 41 registry FAILs into background noise. Do not ship the rule without
  deciding who reads it and what the burn-down target is.
- **Phase 4 Copa-patched images diverge from upstream.** A patched image must be rebuilt on every
  upstream release or it silently rots. Automate it or do not do it.
- **Chainguard's catalogue is commercial** beyond the free tier; the free `latest` images are
  usable but not version-pinned, which conflicts with digest pinning. Evaluate the actual terms
  before committing, and treat Wolfi-built-in-house as the fallback.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Route third-party pulls through Harbor, with a recorded exception list (new) |
| candidate | — | Tiered verification: verify where publishers sign, digest-pin everywhere else (new) |
| candidate | — | Revisit ADR-0033 once routing is done — what stays unapproved, and why (amend) |
| candidate | — | Vulnerability threshold gate: source, VEX handling, and burn-down owner (new) |
| candidate | — | Patch-and-sign third-party images into first-party artifacts via Copacetic (new) |

## Out of scope

- First-party signing and its enforce waves — [image signing & verification](rfc-image-signing-verification.md)
  and [verify-policy gating](rfc-verify-policy-gating.md).
- The CVE-budget predicate itself — already designed, OpenVEX-aware, documented in
  `image-cve-budget-audit`.
- Runtime detection of what a compromised image does — [runtime detection & response](rfc-runtime-detection-response.md).
- Base-image choice for *third-party* software. We do not build it and cannot choose its base;
  that is what Phase 4's patch-or-replace covers.

## References

- [Copacetic](https://github.com/project-copacetic/copacetic) (CNCF sandbox) ·
  [Chainguard Images](https://images.chainguard.dev/) ·
  [Chainguard vs Docker Hardened Images](https://www.chainguard.dev/compare/chainguard-vs-docker)
- [Trivy Operator VulnerabilityReport CRD](https://aquasecurity.github.io/trivy-operator/v0.1.5/crds/vulnerability-report/)
  — the CR a threshold gate would read
- [Sigstore: verifying signatures](https://docs.sigstore.dev/cosign/verifying/verify/) —
  identity-based verification for publishers that sign
- [ADR-0033 — approved registries stays Audit](../adr/adr-0033-approved-registries-stays-audit.md)
  · [ADR-0024 — Harbor mirror](../adr/index.md)
