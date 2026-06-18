# RFC: Security Hardening — Closing the Loops

> Status: **Proposed.** This RFC frames the cluster's security-hardening program. The thesis is that
> "state of the art" here is **not new tooling** — it's *finishing the loops the cluster has already
> built*. The individual choices are recorded as [ADR-0007](../adr/adr-0007-cilium-wireguard-encryption.md)
> … [ADR-0009](../adr/adr-0009-secret-rotation-model.md) (with dynamic credentials split into its own
> [RFC](rfc-dynamic-database-credentials.md)). It flips to **Accepted** as each loop closes.

## Why

The homelab already runs an unusually complete security stack: Kyverno admission control, Falco and
Tetragon runtime detection, Trivy scanning, a cosign/SLSA/SBOM supply-chain pipeline, ESO + OpenBao
for secrets, Talos (immutable OS, etcd `secretbox` at rest), Authentik SSO with an MFA group, and
Cilium (eBPF, kube-proxy-replacement). The apparatus is there. What's missing is **closure** — in
several places the mechanism is built but left in the safe, observe-only, or long-lived position:

- Image-verification policies are **`image-verify-audit` / `image-attestations-audit`** — they
  *watch*, they don't *block*.
- Pod-to-pod traffic was **cleartext on the wire** (etcd-at-rest was encrypted; in-flight wasn't).
- CI builds images in a **privileged** Docker-in-Docker container — the one privileged workload, in
  the one place that runs repo-controlled code.
- Database credentials are **static and long-lived** (now in OpenBao, but still values that exist).
- Network policy is **sparse** — 6 `NetworkPolicy`, 0 `CiliumNetworkPolicy` across ~25 namespaces;
  no default-deny baseline to contain lateral movement.

"Running on the edge" is interpreted here as **least-privilege + defense-in-depth + short-lived
credentials + enforce-not-observe, applied consistently** — not chasing the newest CRD. Novelty has
a cost the cluster has already paid this month (a Longhorn OOM cascade, a leader-election restart
loop); the high-leverage moves are flips, not green-field builds.

## Scope

**In scope (this RFC's ADRs):**

| # | Decision | Choice | Status |
|---|----------|--------|--------|
| [ADR-0007](../adr/adr-0007-cilium-wireguard-encryption.md) | Wire encryption | Cilium **WireGuard** pod-to-pod, `nodeEncryption: false` | **Accepted** (shipped) |
| [ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md) | CI build isolation | **Rootless BuildKit**, drop privileged DinD | **Proposed** (after runner proof) |
| [ADR-0009](../adr/adr-0009-secret-rotation-model.md) | Rotation model | OpenBao write → ESO refresh → Reloader restart | **Accepted** |

**Linked, sequenced elsewhere:**

- **Dynamic database credentials** — short-lived, auto-revoked Postgres creds via OpenBao's database
  engine. Big enough for its own [RFC](rfc-dynamic-database-credentials.md).
- **Supply-chain enforce** — promote the Kyverno image policies from `audit` → `enforce`. *Gated on*
  [Harbor](rfc-harbor-registry.md) existing **and** the GitHub-OIDC → Authentik signing re-anchor
  (see the [Forge migration](../blogs/2026-06-12-bringing-the-forge-home.md)); tracked there, not
  duplicated here.

**Out of scope for now (candidate future ADRs):**

- **Default-deny networking** — a baseline `CiliumClusterwideNetworkPolicy` deny + per-namespace
  allows, authored from observed flows. Prerequisite: **enable Hubble** (currently
  `hubble.enabled: false`) to see the flows before locking them down.
- **Disk encryption at rest** — Talos **LUKS2 + TPM**-sealed STATE/EPHEMERAL partitions. etcd is
  already `secretbox`-encrypted; this protects PVC/image data against physical disk theft. Needs a
  careful rolling Talos apply.
- **Detect → respond** — Falco/Tetragon already detect; add **Falco Talon** / Falcosidekick to
  auto-kill or quarantine on high-severity runtime events, closing detection to containment.
- **Workload identity (SPIFFE/SPIRE or Cilium mutual auth)** — cryptographic service identity +
  mTLS, so services authenticate by identity not network position. Highest effort; revisit after the
  basics and only if L7 identity policy is actually needed.

## Posture map

Where the cluster is today vs. the edge, ranked by leverage-per-effort:

| Area | Today | Edge | Effort | Where |
|------|-------|------|--------|-------|
| Wire encryption | cleartext pod traffic | WireGuard | low | **done** — ADR-0007 |
| Rotation | manual, undocumented | vault-write + Reloader | low | **done** — ADR-0009 |
| CI builds | privileged DinD | rootless BuildKit | low–med | ADR-0008 (queued) |
| DB creds | static long-lived | short-lived dynamic | med | [dynamic RFC](rfc-dynamic-database-credentials.md) |
| Supply chain | **audit** | **enforce** | med | Forge + Harbor track |
| Network | 6 policies, no default-deny | default-deny + L7 | med | future ADR (needs Hubble) |
| Disk at rest | etcd only | + LUKS/TPM | med | future ADR |
| Detect→respond | detect only | auto-contain | med | future ADR |
| Workload identity | none | SPIFFE/mTLS | high | future RFC |

## Sequencing & risks

1. **WireGuard** (done) — isolated, revertible; the one residual risk is the DSR + `hostLegacyRouting`
   interaction, verified by watching the cilium rollout and cross-node connectivity post-merge.
2. **Rotation model** (done) — documentation + the Reloader-annotation checklist; no blast radius.
3. **Rootless builds** — *after* the runner is proven on a real job, so we harden a working thing.
4. **Dynamic DB creds** — pilot on one non-critical database first; connection-churn and the
   privileged bootstrap role are the real risks (its RFC covers them).
5. **Enforce mode** — last and most consequential; only after CI demonstrably produces signatures +
   attestations through the new (Authentik/Harbor) trust anchor, or admission starts rejecting good
   images.

The cross-cutting risk is **over-rotation of stability**: each item is individually reversible, but
landing several CNI/CI/admission changes in a short window compounds blast radius. They ship
**one isolated, revertible commit at a time**, each verified before the next.

## References

- ADRs [0007](../adr/adr-0007-cilium-wireguard-encryption.md),
  [0008](../adr/adr-0008-rootless-ci-image-builds.md), [0009](../adr/adr-0009-secret-rotation-model.md)
- [RFC: Dynamic Database Credentials](rfc-dynamic-database-credentials.md) ·
  [RFC: Harbor Registry](rfc-harbor-registry.md)
- [Supply Chain Pipeline](../general/supply-chain-pipeline.md) · [Authentik](../general/authentik.md) ·
  [The Long Goodbye to SOPS](../blogs/2026-06-12-the-long-goodbye-to-sops.md) ·
  [Bringing the Forge Home](../blogs/2026-06-12-bringing-the-forge-home.md)
