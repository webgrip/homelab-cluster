# ADR-0007: Transparent pod-to-pod encryption via Cilium WireGuard

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Security Hardening](../rfc/rfc-security-hardening.md)

## Context

Secrets at rest are already encrypted: Talos seals etcd with a `secretbox` provider, and Longhorn
volumes carry the cluster's data. But **traffic between pods crossed the LAN in cleartext.** A
compromised node, a span port, or anything with a foothold on the physical network could read
east-west service traffic — database queries, OIDC tokens in flight, S3 credentials moving between
an app and Garage. The cluster runs Cilium in **native routing** mode with `kubeProxyReplacement`,
DSR load-balancing, and `bpf.hostLegacyRouting: true` (a Talos requirement), so any encryption had
to be compatible with that datapath rather than assume a tunnel/overlay.

## Decision

Enable Cilium's built-in **WireGuard** transparent encryption for pod-to-pod traffic:

```yaml
encryption:
  enabled: true
  type: wireguard
  nodeEncryption: false
```

`nodeEncryption` stays **off** deliberately — encrypting host-network and node-port traffic
interacts badly with health checks and the existing DSR path. East-west *pod* traffic (the actual
exposure) is what we encrypt; Cilium manages the per-node WireGuard keys itself, so there is no key
material to store, rotate, or put in OpenBao.

## Consequences

- All Cilium-managed pod-to-pod traffic is encrypted on the wire with no application or sidecar
  changes — it's a datapath property, invisible to workloads.
- Enabling it **rolls every `cilium` agent** (`rollOutCiliumPods: true`), so there is a brief
  cross-node connectivity window during the rollout. Acceptable for a homelab; done as an isolated,
  revertible commit so a problem is a one-line `git revert`.
- ~60–80 bytes of WireGuard overhead per packet (MTU headroom; native routing has slack).
- **Not covered:** host-network pods, node-port ingress, and traffic to external endpoints — those
  ride outside the pod overlay and need `nodeEncryption` (rejected here) or gateway-level TLS (which
  the envoy gateways already terminate for north-south).
- Verify after rollout that agents return `Ready` and cross-node pod connectivity holds — the
  DSR + `hostLegacyRouting` interaction is the one thing static validation can't prove.

## Alternatives considered

- **IPsec** — Cilium's other transport encryption. Stronger cipher agility but heavier (kernel
  `xfrm` state, key rotation to manage) and more brittle on this kube-proxy-replacement + DSR setup.
  WireGuard is simpler and self-manages keys.
- **`nodeEncryption: true`** — encrypts host traffic too, but risks breaking kubelet/health-check
  and DSR node-port flows. Not worth the blast radius for the marginal extra coverage.
- **Service-mesh mTLS (Istio/Linkerd)** — application-identity encryption, but an entire new control
  plane and sidecar tax for what WireGuard delivers at the datapath. Revisit only if we need L7
  identity-based policy (see SPIFFE/SPIRE in the [hardening RFC](../rfc/rfc-security-hardening.md)).
- **Do nothing** — leave the LAN trusted. Rejected; "trusted LAN" is exactly the assumption a
  defense-in-depth posture is supposed to remove.
