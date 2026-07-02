# ADR-0039: Opt-in per-namespace default-deny NetworkPolicies (zero-trust)

> Status: **Accepted** · Date: 2026-07-01 · Part of [RFC: Security Hardening](../rfc/rfc-security-hardening.md) · Supersedes in scope [ADR-0021](adr-0021-cilium-gateway-egress-for-oidc.md)

## Context

The cluster's security posture is *enforce-not-observe* least-privilege, but the network plane's
default was implicit allow: any pod could reach any other pod and any off-cluster endpoint.
Closing that loop means a **zero-trust** stance — every flow denied until an explicit allow
exists. The mechanism was shipped across ~9 app namespaces during W7 (2026-06-14) but never
written up; this record captures the decision retroactively.

Two footguns, both discovered in production during the W7 rollout, shaped how it had to be built:

- **The CNPG operator ClusterIsNotReady deadlock.** A `default-deny` in a namespace running a
  CloudNativePG database drops the operator (in `cnpg-system`) when it polls the instance pods on
  `:8000` (status/liveness). The Cluster then never reports Ready (`Instance Status Extraction
  Error: HTTP communication issue`), and any Flux Kustomization that `dependsOn` that DB stalls.
  Worse, putting the `cnpg-system` allow in the **app-layer** Kustomization deadlocks: that layer
  `dependsOn` the DB being Ready, but the DB can't go Ready until the allow exists —
  chicken-and-egg.

- **Cilium enforces egress on the post-DNAT backend identity, not the VIP/CIDR/port.** When a pod
  connects to a Service ClusterIP or LoadBalancer VIP, Cilium translates the destination to a
  **backend pod** and enforces policy against that backend's **identity and targetPort** *before*
  egress rules run. So a `0.0.0.0/0 except 10.42.0.0/16` egress rule looks permissive but silently
  drops in-cluster Service/gateway traffic (the backend lives in the pod CIDR), and a `port: 443`
  allow misses the real backend port (envoy-internal's `443 → 10443`). The kube-apiserver is
  likewise matched by a **reserved Cilium identity**, so even `ipBlock: 0.0.0.0/0` doesn't cover
  it. This surfaced as Harbor OIDC login returning 500 (`dial tcp 10.0.0.27:443: i/o timeout`) —
  first recorded in [ADR-0021](adr-0021-cilium-gateway-egress-for-oidc.md); this ADR is now the
  canonical home of the lesson.

## Decision

1. **Zero-trust is opt-in per namespace, not cluster-wide.** Labelling a namespace
   `kyverno.io/default-network-policies: "true"` makes the in-repo `namespace-defaults-generate`
   ClusterPolicy
   ([`kubernetes/apps/kyverno/policies/app/namespace-defaults-generate.yaml`](../../../../kubernetes/apps/kyverno/policies/app/namespace-defaults-generate.yaml))
   generate a `default-deny` (ingress+egress) and an `allow-dns` NetworkPolicy for that namespace.
   From then on every flow is denied until a per-app `networkpolicy.yaml` re-opens it selectively.
   Namespaces without the label are untouched.

2. **Two reusable components carry the Cilium-specific allows so no app hand-rolls them:**

   - [`kubernetes/components/cnpg-netpol`](../../../../kubernetes/components/cnpg-netpol/networkpolicy.yaml)
     — an `allow-cnpg-operator` NetworkPolicy (ingress from `cnpg-system` to
     `cnpg.io/podRole: instance` pods on `:8000` + `:5432`) **plus** an `allow-cnpg-apiserver`
     [CiliumNetworkPolicy](../../../../kubernetes/components/cnpg-netpol/ciliumnetworkpolicy.yaml)
     (`egress: toEntities: [kube-apiserver]`, because the API server is an identity, not a CIDR).
     This component **must** be included in the non-gated **DB-layer** Kustomization (the
     `<app>-db` ks that only `dependsOn` cloudnative-pg), never the app layer, so it applies
     before the cluster health-gate and cannot deadlock. Wired in e.g.
     [`harbor/harbor/app/database/kustomization.yaml`](../../../../kubernetes/apps/harbor/harbor/app/database/kustomization.yaml).

   - [`kubernetes/components/gateway-egress`](../../../../kubernetes/components/gateway-egress/networkpolicy.yaml)
     — a single `allow-gateway-egress` NetworkPolicy permitting egress to namespace `network` via
     an **identity (`namespaceSelector`) rule with no port filter**. Port-less and identity-based
     is mandatory: a CIDR clause drops it and a port clause misses the `443 → 10443` translation.
     Included by every zero-trust app that does **server-side OIDC** discovery through a gateway
     VIP (harbor, backstage). This is the decision of
     [ADR-0021](adr-0021-cilium-gateway-egress-for-oidc.md); ADR-0039 subsumes it as the
     gateway-egress half of the same opt-in default-deny model.

3. **Per-app policies follow the identity-first rule.** In-cluster and gateway/apiserver flows are
   expressed by `namespaceSelector`/`toEntities`; the `ipBlock` CIDR clauses
   (`0.0.0.0/0 except 10.42.0.0/16` + `10.43.0.0/16`, and LAN `10.0.0.0/8`) are effective only for
   real off-cluster endpoints — Garage S3 WAL at `10.0.0.110:3900`, Trivy CVE feeds, proxy-cache
   upstreams, the internet. See
   [`harbor/harbor/app/networkpolicy.yaml`](../../../../kubernetes/apps/harbor/harbor/app/networkpolicy.yaml)
   as the reference shape.

4. **CI guards make the two footguns build-time errors, not login-time surprises.**
   [`scripts/check-gateway-egress.sh`](../../../../scripts/check-gateway-egress.sh) fails the
   build if a zero-trust app references an OIDC discovery URL but omits
   `components/gateway-egress`; the flux-local test and the Kyverno chainsaw/CLI suites exercise
   the generator; posture coverage is snapshotted via `scripts/posture-counts.sh`.

## Alternatives considered

- **Cluster-wide default-deny (applied to all namespaces).** Rejected: it would break
  infrastructure namespaces (observability scraping, cnpg-system, security tooling) wholesale and
  force every allow to land at once. The opt-in label lets namespaces be hardened one at a time
  behind a clean rollback (remove the label) — how W7 actually landed without a fleet-wide outage.
- **Express Service/gateway/apiserver egress with CIDR + port rules** (e.g. `ipBlock` to the
  gateway VIP on `443`, `ipBlock: 10.43.0.0/16` for the API server). Rejected: per the post-DNAT
  enforcement above, such rules silently do not govern in-cluster Service traffic — proven by the
  Harbor OIDC 500 and the CNPG apiserver timeout. In-cluster flows must use identity selectors,
  port-less.
- **Put the `cnpg-system` allow in the app-layer Kustomization.** Rejected: it deadlocks apps with
  a separate gated `<app>-db` ks (harbor, n8n, authentik) — the chicken-and-egg above. The allow
  must live on the non-gated DB layer.
- **Hubble-driven policy discovery / observe-first.** Not needed: the required allows were
  derivable from the app topology (intra-namespace mesh, gateway, LAN, cnpg-system, apiserver),
  and the two components generalise them, so W7 shipped without standing up Hubble.

## Consequences

- **Every zero-trust namespace commits to explicit allows.** Turning on the label without adding
  the per-app policy + the relevant components denies all traffic. A CNPG namespace *must* include
  `components/cnpg-netpol` in its DB layer; a server-side-OIDC app *must* include
  `components/gateway-egress`. The CI guard blocks the OIDC omission; the CNPG omission is caught
  by the DB never going Ready.
- **Verification is two-signal for CNPG apps:** both `ContinuousArchiving=True` (egress/WAL path)
  **and** the Cluster `Ready=True` (ingress/status path) — declaring victory on the first alone is
  what let the W7 status-path gap ship silently.
- Rollout is incremental and reversible — a namespace can be onboarded (or its label removed) one
  at a time, and each per-app policy is a small, reviewable, least-privilege grant.
- Off-cluster egress is still broad (`0.0.0.0/0` for internet-needing apps); tightening those
  CIDRs to specific endpoints is future work, not part of this decision.

## Status log

- 2026-06-14 — Mechanism shipped across the W7 zero-trust namespaces (generator policy + the two
  components), without an ADR.
- 2026-06-30 — n8n's non-functional OIDC config removed (d15b8e22), shrinking the server-side-OIDC
  set to harbor + backstage; n8n keeps `components/gateway-egress` for its authentik ETL calls.
- 2026-07-01 — Recorded retroactively as Proposed.
- 2026-07-02 — Accepted (ratified, 7051e70d).
