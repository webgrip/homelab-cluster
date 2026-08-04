# RFC: Workload identity — put a name on the workload, not just the node

> Status: **Proposed** · Date: 2026-08-04 · Spawned by the [Kyverno estate audit](rfc-kyverno-audit-enforce-hardening.md#audit-2026-08-04)

> **TL;DR.** Cilium WireGuard ([ADR-0004](../adr/adr-0004-cilium-wireguard-encryption.md))
> encrypts traffic **node to node**. Every pod on a node shares that tunnel, so the encryption
> proves where a packet came from, never *what* sent it. Cilium's SPIFFE-based **mutual
> authentication is not enabled** (`mesh-auth-mutual-enabled` is unset), and there is no SPIRE.
> Adding per-workload cryptographic identity would let network policy and service-to-service auth
> key on *this workload* rather than *a pod wearing these labels on this node*. It is also the
> **most expensive and least urgent** item to come out of the security audit: it needs a SPIRE
> server (Postgres-backed for HA) on a single-worker cluster, and the gap it closes is largely
> theoretical while admission control already governs who may create pods with which labels and
> ServiceAccounts. This RFC exists to record the gap and name the trigger that would make it
> worth paying for — not to argue for doing it now.

## Why

Verified state, 2026-08-04:

- **Cilium WireGuard: on** (`enable-wireguard=true`), Hubble on, L7 proxy on.
- **Cilium mutual auth: off** — `mesh-auth-mutual-enabled` is unset in `cilium-config`.
- **No SPIRE**, no SPIFFE CSI driver.
- **107 NetworkPolicies** across the estate, default-deny opt-in
  ([ADR-0006](../adr/adr-0006-default-deny-network-policies.md)).
- **cert-manager and trust-manager are deployed** — which is most of the prerequisite for the
  cert-manager-flavoured variant of this.

The honest shape of the gap:

1. **Encryption ≠ identity.** WireGuard gives confidentiality on the wire between nodes. It does
   not authenticate the *workload* at either end. Two pods on the same node are
   indistinguishable to it.
2. **Cilium identities are label-derived.** Network policy resolves to identities computed from
   pod labels. That is a strong control *given* that pod creation is governed — and here it is,
   heavily: `pod-security-baseline-enforce`, `rbac-least-privilege-enforce` and the tenancy
   policies all constrain what can be created and by whom. So the practical exposure is smaller
   than the theoretical one, and this should be stated plainly rather than dramatised.
3. **Where it would actually matter is the CI path.** The workloads with the broadest waivers —
   privileged DinD, buildkitd, the runners — are the ones where "a pod wearing these labels" is
   the weakest assumption in the cluster, because those pods run third-party code by design. If
   anything justifies per-workload identity here, it is that, and it overlaps with the
   [attack-path RFC](rfc-attack-path-analysis.md)'s subject matter.

## Proposal

Do **not** start this now. Record the two viable paths, the trigger, and the sequencing.

**Path A — Cilium mutual authentication (SPIFFE/SPIRE).** Enable Cilium's mutual auth, which
brings a SPIRE server and per-node agents, and gate `CiliumNetworkPolicy` rules on authenticated
workload identity. Fits the existing datapath; one vendor; policy stays where policy already is.
Cost: SPIRE server + agents + a datastore, on a cluster with one worker node.

**Path B — `cert-manager/csi-driver-spiffe`.** A CSI driver mounts short-lived X.509 SVIDs into
pods as ephemeral volumes, issued by cert-manager against a SPIFFE trust domain; applications do
mTLS themselves. Cheaper to stand up (cert-manager and trust-manager already run here) and it
gives *application-level* identity rather than network-level. Cost: every consuming app must
actually speak mTLS, which most of ours do not.

**Sequencing and trigger.** This RFC is explicitly ranked **last** among the audit's outputs,
behind the [CEL migration](rfc-kyverno-cel-migration.md) (dated deadline),
[verify-policy gating](rfc-verify-policy-gating.md), [runtime
detection](rfc-runtime-detection-response.md), and [attack-path
analysis](rfc-attack-path-analysis.md). Reconsider when **any** of these becomes true:

- The attack-path analysis finds a real path that turns on label-spoofing or SA-token reuse — i.e.
  the theoretical gap becomes a demonstrated one.
- A second worker node lands, making the SPIRE footprint proportionate.
- An application arrives that needs mTLS between services for its own reasons (at which point
  Path B is nearly free).
- [Request authorization at the gateway](rfc-request-authorization-envoy.md) ships and the
  north-south authorization story makes the east-west absence conspicuous.

Until one of those holds, the recorded decision should be **"gap acknowledged, not closed"** —
which is a decision, and better than an unremarked absence.

## Risks

- **Footprint on a single-worker cluster.** SPIRE server + per-node agents + datastore is real
  memory on hardware where the runtime-security agents were removed for exactly this kind of
  pressure. That precedent should weigh heavily.
- **mTLS debugging cost.** Identity failures present as opaque connection resets. On a
  single-operator cluster, that is a meaningful operational tax for a control whose benefit is
  currently theoretical.
- **Doing it badly is worse than not doing it.** A half-enabled mutual-auth posture — some
  policies authenticated, most not — provides the appearance of workload identity without the
  property. If this is adopted, it should be adopted for a defined scope and stated as such.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Acknowledge the workload-identity gap and defer, with named re-evaluation triggers (new) |
| candidate | — | If adopted: Cilium mutual auth (Path A) vs cert-manager csi-driver-spiffe (Path B) (new) |

## Out of scope

- Node-to-node encryption — decided ([ADR-0004](../adr/adr-0004-cilium-wireguard-encryption.md)).
- Network policy authoring — [ADR-0006](../adr/adr-0006-default-deny-network-policies.md).
- Human identity and SSO — [identity RFC](rfc-identity-sso.md); this is workload-to-workload.
- North-south request authorization — [own RFC](rfc-request-authorization-envoy.md).
- Secret delivery. ESO + OpenBao already own that and are unaffected.

## References

- [cert-manager csi-driver-spiffe](https://cert-manager.io/docs/usage/csi-driver-spiffe/) — Path B
- [SPIFFE/SPIRE](https://spiffe.io/) — the identity standard both paths implement
- [ADR-0004 — Cilium WireGuard encryption](../adr/adr-0004-cilium-wireguard-encryption.md) — what
  is already in place, and what it does not claim to do
