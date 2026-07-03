# Transparent pod-to-pod encryption via Cilium WireGuard

* Status: accepted
* Date: 2026-06-12

Technical Story: [RFC: Security Hardening](../rfc/rfc-security-hardening.md)

## Context and Problem Statement

Secrets at rest are already encrypted: Talos seals etcd with a `secretbox` provider, and Longhorn
volumes carry the cluster's data. But **traffic between pods crossed the LAN in cleartext.** A
compromised node, a span port, or anything with a foothold on the physical network could read
east-west service traffic — database queries, OIDC tokens in flight, S3 credentials moving between
an app and Garage. The cluster runs Cilium in **native routing** mode with `kubeProxyReplacement`,
DSR load-balancing, and `bpf.hostLegacyRouting: true` (a Talos requirement), so any encryption had
to be compatible with that datapath rather than assume a tunnel/overlay.

## Considered Options

* Cilium WireGuard transparent encryption (`nodeEncryption: false`)
* IPsec
* `nodeEncryption: true`
* Service-mesh mTLS (Istio/Linkerd)
* Do nothing

## Decision Outcome

Chosen option: "Cilium WireGuard transparent encryption (`nodeEncryption: false`)", because
east-west *pod* traffic (the actual exposure) is what we encrypt, WireGuard delivers it as a
datapath property compatible with the existing native-routing setup, and Cilium manages the
per-node WireGuard keys itself, so there is no key material to store, rotate, or put in OpenBao.

Enable Cilium's built-in **WireGuard** transparent encryption for pod-to-pod traffic, in the
cilium HelmRelease (`kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`):

```yaml
encryption:
  enabled: true
  type: wireguard
  nodeEncryption: false
```

`nodeEncryption` stays **off** deliberately — encrypting host-network and node-port traffic
interacts badly with health checks and the existing DSR path.

### Positive Consequences

* All Cilium-managed pod-to-pod traffic is encrypted on the wire with no application or sidecar
  changes — it's a datapath property, invisible to workloads.

### Negative Consequences

* Enabling it **rolls every `cilium` agent** (`rollOutCiliumPods: true`), so there is a brief
  cross-node connectivity window during the rollout. Done as an isolated commit so a problem is a
  one-line `git revert`.
* ~60–80 bytes of WireGuard overhead per packet (MTU headroom; native routing has slack).
* **Not covered:** host-network pods, node-port ingress, and traffic to external endpoints — those
  ride outside the pod overlay and need `nodeEncryption` (rejected here) or gateway-level TLS
  (which the envoy gateways already terminate for north-south).

## Pros and Cons of the Options

### Cilium WireGuard transparent encryption (`nodeEncryption: false`)

* Good, because encryption is a datapath property — no application or sidecar changes, invisible
  to workloads.
* Good, because Cilium manages the per-node WireGuard keys itself — no key material to store,
  rotate, or put in OpenBao.
* Bad, because host-network pods, node-port ingress, and traffic to external endpoints stay
  uncovered.

### IPsec

Cilium's other transport encryption.

* Good, because stronger cipher agility.
* Bad, because heavier — kernel `xfrm` state, key rotation to manage.
* Bad, because more brittle on this kube-proxy-replacement + DSR setup.

### `nodeEncryption: true`

* Good, because it covers host traffic too.
* Bad, because it risks breaking kubelet/health-check and DSR node-port flows — not worth the
  blast radius for the marginal extra coverage.

### Service-mesh mTLS (Istio/Linkerd)

* Bad, because an entire control plane and sidecar tax for what WireGuard delivers at the
  datapath; revisit only if L7 identity-based policy is needed (SPIFFE/SPIRE in the
  [hardening RFC](../rfc/rfc-security-hardening.md)).

### Do nothing

* Bad, because "trusted LAN" is exactly the assumption a defense-in-depth posture removes.

## Links

* 2026-06-12 — accepted; rolled out as an isolated, revertible commit (the post-rollout check —
  agents Ready, cross-node pod connectivity — was the one thing static validation couldn't prove)
* 2026-07-03 — renumbered from ADR-0007 (pre-re-baseline numbering) in the layered re-ordering of the ADR set (see [index](index.md))
