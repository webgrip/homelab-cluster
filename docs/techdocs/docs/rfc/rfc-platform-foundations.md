# RFC: Platform foundations — record the pre-ADR-era decisions

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** The three most load-bearing decisions in the cluster — Talos Linux as the node OS,
> Flux (via flux-operator) with the three-layer Kustomization topology, and Cilium as the CNI in
> its specific datapath configuration — predate the ADR practice (started 2026-06-12) and exist
> only as running configuration. This RFC backfills them as **retroactive ADRs**, the same move
> [ADR-0006](../adr/adr-0006-default-deny-network-policies.md) made for default-deny. No behaviour
> changes; the deliverable is records.

## Why

Later ADRs constantly *lean on* these decisions without a record to point at: ADR-0004 configures
WireGuard "compatible with the existing native-routing + kubeProxyReplacement datapath" — decided
nowhere. ADR-0024 injects registry mirrors "at the Talos/containerd layer" — Talos itself is
decided nowhere. ADR-0011 repoints the `FluxInstance` `sync.url` — the FluxInstance/flux-operator
arrangement is decided nowhere. Each of these was a genuine choice with genuine alternatives
(k3s/NixOS vs Talos; ArgoCD vs Flux; the umbrella `flux2` chart vs flux-operator; Calico/flannel
vs Cilium), and the reasoning is currently only in the owner's head. The cost shows up two ways:
alternatives get re-litigated from scratch ("should we run Hubble UI?" touches the Cilium decision),
and constraints that follow from these choices (Talos's `hostLegacyRouting` requirement, the
immutable rootfs that shapes trivy-operator config) read as arbitrary without the parent record.

What exists today (verified in-tree, 2026-07-02):

- **Talos** — 5 bare-metal amd64 nodes, machine config GitOps-managed under `talos/`
  (talhelper: `talconfig.yaml` + patches), API VIP `10.0.0.25`, etcd sealed with `secretbox`,
  immutable rootfs. Operations via `task talos:*`.
- **Flux** — flux-operator + a `FluxInstance` (sync: GitHub `homelab-cluster`, `main`); one root
  Kustomization `cluster-apps` (`kubernetes/flux/cluster/ks.yaml`, 1h interval, prune, SOPS
  decryption) that applies HelmRelease defaults by patch; per-app `ks.yaml` wiring (`dependsOn`,
  `targetNamespace`, `postBuild.substituteFrom`) over `<app>/app/` resources — the three-layer
  topology every skill and doc assumes.
- **Cilium** — `kubeProxyReplacement: true`, `routingMode: native` (`10.42.0.0/16`,
  `autoDirectNodeRoutes`), DSR + maglev, `bpf.hostLegacyRouting: true` (Talos requirement),
  WireGuard (ADR-0004), Hubble metrics-only (no relay/UI), `gatewayAPI.enabled: false`
  (Envoy Gateway owns Gateway API), L2 announcements + a single `CiliumLoadBalancerIPPool`
  (`10.0.0.0/24`) providing every LoadBalancer VIP — no BGP.

## Proposal

Write three retroactive ADRs, one per foundation, each recording the decision as originally made
plus a dated status log of how it has evolved:

1. **Adopt Talos Linux as the node OS.** Context: immutable, API-driven, no SSH/shell, machine
   config as GitOps artifact; the trade-offs it forces (no node-local debugging, out-of-tree
   kernel modules effectively unavailable — which ADR-0007 later hit with DRBD; `hostLegacyRouting`
   for Cilium). Alternatives: k3s on Debian/NixOS, kubeadm. Consequences include the Talos-specific
   operational surface (`talosctl`, upgrade path, maintenance mode).
2. **Adopt Flux with the flux-operator/FluxInstance shape and the three-layer Kustomization
   topology.** Records why flux-operator over `flux bootstrap`/umbrella chart (CRD-managed
   lifecycle, the `sync.url` as a single cutover point — load-bearing for ADR-0011/0015), the
   root→ks→app layering, HelmRelease-defaults-by-patch, and SOPS decryption at the root (now the
   minimal floor per the [external-secrets plan](external-secrets-plan.md)). Alternatives: ArgoCD,
   plain flux2 chart.
3. **Adopt Cilium as the CNI, in this datapath configuration.** Records kube-proxy replacement +
   native routing + DSR/maglev as a package, L2/LB-IPAM for VIPs (vs MetalLB/BGP), Hubble
   metrics-only, and `gatewayAPI: false` (the split with Envoy Gateway). This becomes the parent
   record for the post-DNAT identity-enforcement lesson (ADR-0005/0039) and WireGuard (ADR-0004).

House rules for retroactive records: the ADR body describes the decision **as of its original
date** (best-effort from git history); everything since goes in the Status log. Status:
**Accepted** on landing — these are ratifications of reality, not proposals.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Adopt Talos Linux as the node OS (retroactive) |
| candidate | — | Flux via flux-operator + three-layer Kustomization topology (retroactive) |
| candidate | — | Cilium CNI: kube-proxy replacement, native routing, DSR, L2/LB-IPAM (retroactive) |

## Out of scope

- The ingress edge (gateways, tunnel, DNS) — its own [RFC](rfc-ingress-dns-edge.md).
- Hardware/node topology — owned by the [layered-hardware RFC](rfc-layered-hardware-architecture.md)
  and the [node-taxonomy RFC](rfc-node-taxonomy-and-storage-placement.md).
- Changing any of these decisions. If a re-evaluation is ever wanted (e.g. Cilium BGP instead of
  L2), it starts from the ADR these records create, as a superseding ADR.

## References

- [Talos cluster doc](../general/talos-cluster.md) · [flux runbook](../runbooks/flux.md) ·
  [cilium runbook](../runbooks/cilium.md)
- [ADR-0006](../adr/adr-0006-default-deny-network-policies.md) — the retroactive-recording precedent
