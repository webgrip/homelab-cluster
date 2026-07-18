---
name: network-policy
description: Author NetworkPolicy / CiliumNetworkPolicy for the zero-trust cluster — opt-in default-deny, the cnpg-netpol + gateway-egress components, and Cilium's identity-based egress.
when_to_use: Use when adding/editing a NetworkPolicy or CiliumNetworkPolicy, making a namespace zero-trust, fixing a ClusterIsNotReady or server-side-OIDC egress deadlock, or wiring the cnpg-netpol/gateway-egress components.
allowed-tools: Bash(./scripts/run-flux-local-test.sh*), Bash(./scripts/check-gateway-egress.sh*), Bash(./scripts/posture-counts.sh*)
---

# Network policy (zero-trust, Cilium-enforced)

## Zero-trust is opt-in per namespace
Label the namespace `kyverno.io/default-network-policies: "true"` → Kyverno `namespace-defaults-generate`
generates `default-deny` + `allow-dns` NetworkPolicies (+ ResourceQuota/LimitRange). From then on every
flow is denied until you add an allow. Generator:
`kubernetes/apps/kyverno/policies/app/namespace-defaults-generate.yaml` (see the `kyverno-policy` skill).

## ⚠️ Cilium egress is identity-based, NOT CIDR/port
Cilium enforces egress on the **post-DNAT backend identity + targetPort**, not the Service VIP/CIDR or
port. So CIDR/port rules do **not** govern Service/gateway traffic — a `0.0.0.0/0 except pod-CIDR` rule
looks permissive but silently drops gateway hairpins + kube-apiserver calls. Govern Service/gateway flows
by **identity** (`namespaceSelector`/`toEntities`), port-less.
([ADR-0005](docs/techdocs/docs/adr/adr-0005-cilium-gateway-egress-for-oidc.md)).

## The two reusable components (don't hand-roll these)
- **`components/gateway-egress`** — `allow-gateway-egress`: egress to `namespaceSelector: network`, **no
  port filter** (port-less is mandatory, per the rule above). Required for any zero-trust app doing
  **server-side OIDC** (token exchange / discovery). `scripts/check-gateway-egress.sh` **fails CI** if a
  zero-trust ns references OIDC discovery (`well-known/openid-configuration`) but omits this component.
- **`components/cnpg-netpol`** — `allow-cnpg-operator` (cnpg-system → pods `cnpg.io/podRole: instance` on
  **:8000 status + :5432**) + a CiliumNetworkPolicy for cnpg apiserver egress.

## ⚠️ cnpg-netpol MUST live in the non-gated DB-layer ks
Add `components/cnpg-netpol` to the `<app>-db` ks (the one that only `dependsOn` cloudnative-pg) — **never**
the app ks. Default-deny blocks cnpg-system from polling the instance :8000 → `ClusterIsNotReady` → the DB
never goes Ready → the app ks gate (`dependsOn` db-Ready) never fires → **deadlock**. The allow must sit on
the non-gated layer so the DB can come up first.

## ⚠️ Ingress is a checklist too (not just egress)
Any new consumer of in-cluster Forgejo (`forgejo-http:3000` — a provisioner, Renovate, a CI tool)
needs an explicit **ingress** allow in `kubernetes/apps/forgejo/networkpolicy.yaml`
(`namespaceSelector` on `kubernetes.io/metadata.name: <ns>`). The renovate provisioner failed
silently for 3 days when the zero-trust sweep only covered egress (2026-07-15→18 incident).
Related: never write `ipBlock 10.43.0.1/32` apiserver rules — inert under Cilium (identity, not
CIDR; the rule above). Existing ones are NOTE'd out in several namespaces — don't copy them.

## Add per-app policies
Copy `kubernetes/apps/authentik/app/networkpolicy.yaml` (or `kubernetes/apps/harbor/harbor/app/networkpolicy.yaml`):
an `allow-ingress` + `allow-egress` pair — intra-namespace, gateway, LAN, observability scraping,
cnpg-system operator ingress; egress to in-cluster + LAN + internet (except pod CIDRs). Wire it in the app
`kustomization.yaml`.

## Validate
`./scripts/run-flux-local-test.sh` + `./scripts/check-gateway-egress.sh` (the OIDC-egress guard) + `just
kyverno-chainsaw` (network-guardrails suite). Coverage snapshot: `./scripts/posture-counts.sh`.
