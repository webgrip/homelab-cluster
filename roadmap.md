# Homelab Cluster Improvement Roadmap

> **Living backlog, kept topped up at 100 open items.** As items ship, move them to the Done log
> and refill so the open count stays ~100. Maintained by the `roadmap-topup` skill.
> Re-inventoried **2026-06-14** (3 parallel deep audits + live MCP/Prometheus checks).
> Tags: `[Priority · Impact · Effort]` — Priority P0–P3, Impact H/M/L, Effort S/M/L.

## Where we stand (live, 2026-06-14)

- **Flux:** Ready except `n8n/n8n-db` (reconciling from the just-landed CNPG-tiering commit
  357d94c — verify it settles). Suspended on purpose: `observability/pyroscope` (etcd I/O).
- **etcd:** healthy (~198 MB, frag 1.33). **Memory:** control planes ~78–80% — still the binding
  constraint; restore drills stay **off**.
- **Hardening posture (verified):** 0 PodDisruptionBudgets · **15 NetworkPolicies across 11 app
  namespaces** (W7 zero-trust), but 0 CiliumNetworkPolicy, no default-deny, and **13 platform
  namespaces still unprotected** · Hubble disabled · 4 ResourceQuotas (W6, app ns) · **10 of 16
  Kyverno policies still `Audit`** · 0 Envoy `SecurityPolicy` · all ~11 CNPG clusters single-instance
  (backups now **tiered** + WAL-compressed) · Garage S3 (10.0.0.110) a hard SPOF.
- **Active owner workstreams:** Forgejo migration (Renovate dual-run ADR 0011–0013/0019; Flux source
  ADR 0014–0015) and Harbor pull-through proxy-cache (ADR 0016–0018). Sequence around their gates.

## ✅ Done log (recent)

- **Headway batch (2026-06-14):** digest-pinned 9 unpinned images (#29 — openbao/aws-cli/alpine-k8s/
  dind/forgejo-runner; harbor-proxy left to the owner); PDBs for CoreDNS + cloudflared (#44, the
  reschedulable ones; authentik/envoy deferred — fringe-pinned, a PDB would deadlock fringe drains).
  Also surfaced #77: the Flux alerting is dead (metric source missing, not just the PodMonitor).
- **Alerts batch (2026-06-14):** node-memory pressure (#71); OpenBao snapshot staleness (#54);
  **Flux PodMonitor** — but the controllers don't expose the condition/suspend metrics, so the Flux
  NotReady/Drift/Suspended alerts are still dark (see #77) — plus the suspended-Kustomization alert (#70).
- **Owner W6/W7 + Harbor + CNPG (2026-06-13/14):** per-namespace count-only ResourceQuotas (W6);
  zero-trust NetworkPolicies across 11 app namespaces (W7); Harbor pull-through proxy-cache + HR
  stall fix; CNPG backup tiering (DBs 1–5, WAL zstd compression, per-tier retention; guac+dtrack 30d→7d).
- **P1 batch (2026-06-13):** gitleaks history clean + config; Flux drift-detection `warn`; ESO docs →
  OpenBao (migration marked complete); cloudflared 2 replicas; priorityClassName cert-manager/ESO/CoreDNS;
  Authentik server 2 replicas.
- **P0 batch + owner W3–W5 (2026-06-12):** coredns split-DNS; CI yamllint + alert-validator on push;
  ESO/CNPG alerts; InvoiceNinja DB backup; etcd defrag; first-party pod hardening; Harbor OIDC GitOps.

## ▶ Do next (top of the stack)

`#53` key escrow · `#11` Hubble · `#13` platform-ns NetworkPolicies · `#17` Prom/Alertmanager auth ·
`#21` searxng root fix · `#29` digest-pin images · `#44` PDBs · `#78`/`#79` zizmor+mkdocs in CI.

---

## The 100

### Security — promote Kyverno audit → enforce (10 policies live in `Audit`)
1. Promote `require-probes` → Enforce (after a probe-coverage sweep) — `[P1 · Med · M]`
2. Promote `image-hygiene` (immutable tags, no `:latest`) → Enforce — `[P2 · Med · M]`
3. Promote `image-supply-chain` (digest + approved registries) → Enforce for platform ns — `[P2 · High · M]`
4. Promote `rbac-least-privilege` → Enforce after a clean PolicyReport week — `[P2 · High · M]`
5. Promote `workload-hardening` (runAsNonRoot/seccomp/PE) → Enforce, ns-by-ns — `[P2 · High · L]`
6. Promote `workload-advanced-hardening` (automountSAToken/privileged) → Enforce — `[P2 · High · M]`
7. Promote `namespace-tenancy` → Enforce — `[P2 · Med · M]`
8. Promote `secrets-observability-ops` → Enforce — `[P2 · Med · M]`
9. Promote `image-verify` (cosign keyless) → Enforce for `ghcr.io/webgrip/*` — `[P2 · High · M]`
10. Promote `image-attestations` (SLSA + CycloneDX) → Enforce — `[P3 · Med · M]`

### Security — network containment
11. Enable Hubble (gates the default-deny work) — `[P1 · Med · S]`
12. Default-deny `CiliumClusterwideNetworkPolicy` + per-ns allows from observed flows — `[P2 · High · L]`
13. NetworkPolicies for the 13 unprotected platform/game namespaces (cnpg-system, observability,
    security, network, kube-system, flux-system, longhorn-system, arc-systems, cert-manager, keda,
    renovate, minecraft, zomboid) — `[P1 · High · M]`
14. Crown-jewel netpol: restrict OpenBao ingress to ESO + unsealer only — `[P2 · High · M]`
15. Crown-jewel netpol: CNPG clusters (app + barman egress only) — `[P2 · High · M]`
16. Extract a reusable NetworkPolicy component/base (DRY the 11 hand-written zero-trust policies) — `[P2 · Med · S]`

### Security — auth & exposure
17. Prometheus + Alertmanager behind Authentik (Envoy `SecurityPolicy` OIDC) — `[P1 · High · M]`
18. Auth-matrix sweep: Longhorn UI, Policy Reporter, OpenBao UI, Backstage — `[P2 · High · M]`
19. Document-or-gate public envoy-external routes (invoiceninja, flux-ui, renovate, twitch) — `[P2 · Med · M]`
20. Add securityContext to the Envoy proxy pods (EnvoyProxy CRD) — `[P3 · Low · S]`

### Security — per-app pod hardening
21. searxng: fix `runAsNonRoot:false` + `readOnlyRootFilesystem:false` (explicit violation) — `[P1 · High · M]`
22. invoiceninja: add pod + container securityContext (fsGroup, seccomp, drop caps) — `[P1 · Med · M]`
23. sparkyfitness + zomboid: drop `runAsNonRoot:false` (the main `workload-hardening` violators) — `[P2 · Med · M]`
24. dependency-track SBOM-uploader CronJob: fix `runAsNonRoot:false` — `[P2 · Med · S]`
25. Observability stack securityContext: loki, tempo, mimir, blackbox, k6, sloth, alloy — `[P2 · Med · M]`
26. KEDA controller/metrics-server securityContext — `[P2 · Med · S]`
27. drawio + excalidraw + freshrss: pod securityContext (+ drawio `resources.requests`) — `[P2 · Low · S]`
28. arc-systems runners: harden + document the DinD/CI threat model — `[P2 · High · M]`

### Security — image supply chain
29. Digest-pin the ~9 unpinned images (openbao bootstrap/unsealer, aws-cli, alpine/k8s, forgejo
    runner+dind, harbor-proxy-config) — `[P1 · High · S]`
30. Renovate: digest-pin CronJob/runner images going forward — `[P2 · Med · S]`
31. Finish ADR-0008 rootless CI builds (BuildKit, kill DinD) — `[P2 · Med · M]`

### Security — node / Talos
32. Kubernetes API audit logging → Loki — `[P2 · High · M]`
33. Add KubePrism (local API LB for kubelet→apiserver) — `[P2 · Med · S]`
34. Decide secure-boot + LUKS/TPM disk encryption in an ADR — `[P3 · Med · L]`
35. Document the deleted Talos admission control / PSA-fallback decision — `[P3 · Low · S]`
36. Restrict etcd/controller-manager/scheduler metrics bind to host-internal — `[P3 · Low · S]`

### Secrets endgame
37. Ship dynamic Postgres credentials (ADR-0010) for one app (freshrss) — `[P2 · High · L]`
38. Roll dynamic DB creds to remaining CNPG apps; retire static DB ExternalSecrets — `[P3 · High · L]`
39. Migrate the last SOPS app secret (zomboid) → ESO — `[P2 · Med · M]`
40. Audit Reloader (`reloader.stakater.com/auto`) coverage across secret consumers — `[P2 · Med · M]`
41. Secret-rotation cadence doc for the SOPS floor (age key, talsecret, deploy key) — `[P2 · Med · S]`
42. Tune ESO `refreshInterval` per-secret (faster for rotatable, slower for at-rest) — `[P3 · Low · S]`
43. CI guard: fail when a new `*.sops.yaml` appears outside the allowed floor — `[P2 · Med · S]`

### Reliability — HA, PDBs, replicas
44. PodDisruptionBudgets for CoreDNS, envoy gateways, Authentik, CNPG, ESO, cilium-operator — `[P1 · High · M]`
45. k8s-gateway → 2 replicas + PDB (internal-DNS SPOF, 1 replica today) — `[P1 · High · M]`
46. Authentik node-level HA: media → Garage S3, then unpin from `fringe` — `[P2 · Med · M]`
47. priorityClassName on envoy-gateway (review cilium too) — `[P2 · Low · S]`
48. Selected CNPG clusters → 2 instances (authentik, harbor, forgejo) — `[P2 · High · M]`
49. HA review: metrics-server / reloader / alloy-gateway / mcp-grafana (all 1 replica) — `[P3 · Med · S]`
50. PriorityClasses for the remaining platform tier (k8s-gateway, reloader, metrics-server) — `[P2 · Med · S]`

### Reliability — backup & DR
51. Restore-test components for the 2 CNPG apps still missing them (authentik, grafana) — `[P1 · Med · M]`
52. Re-enable restore drills (staggered) once CP RAM < ~70% — `[P2 · Med · S]`
53. Off-site escrow of `age.key` + `talsecret` — verify a copy exists outside git — `[P0 · High · S]`
54. Verify the OpenBao raft snapshot actually restores (test into kind) — `[P2 · High · M]`
55. Offsite backup for non-DB PVCs (volsync / Longhorn S3): forgejo, authentik media, n8n, worlds — `[P2 · High · L]`
56. Configure a Longhorn external backup target + scheduled backups — `[P2 · Med · M]`
57. Full DR drill of the hibernated `cnpg-disaster-recovery`; write the runbook from it — `[P2 · High · M]`
58. "Total cluster loss → restored" end-to-end runbook — `[P2 · High · M]`
59. Periodic (quarterly) bootstrap-from-scratch rebuild test — `[P3 · Med · M]`
60. CI check: bootstrap helmfile chart versions match the HelmReleases — `[P2 · Med · M]`
61. RCA + re-enable Beyla, or remove it (undated suspension) — `[P2 · Low · S]`

### Reliability — Garage SPOF
62. Document Garage RPO/RTO + a Garage-down recovery runbook — `[P2 · High · S]`
63. Evaluate a 2nd Garage node / replicated MinIO so 11 DBs don't share one box — `[P3 · High · L]`

### Reliability — Flux structure & capacity
64. Add `healthChecks` + `wait: true` to platform-tier Kustomizations — `[P2 · Med · M]`
65. Audit `dependsOn` graph completeness (~24 ks lack it; coredns/k8s-gateway notably) — `[P2 · Med · M]`
66. Audit `postBuild.substituteFrom` coverage across ks.yaml — `[P2 · Low · S]`
67. Mimir Kafka single-broker durability: PVC auto-expand or StatefulSet replacement — `[P2 · Med · M]`
68. Extend ResourceQuotas to platform namespaces (W6 covered app ns only) — `[P3 · Low · S]`

### Observability — alert/SLO coverage
69. Cert-expiry alerts beyond cert-manager (OpenBao TLS, hand-rolled) — `[P2 · Med · S]`
70. cloudflared tunnel-connectivity alert (2 replicas, but no failure alert) — `[P2 · Med · S]`
71. Mimir/Kafka memory-saturation alert before OOM — `[P2 · Med · S]`
72. Pyroscope return on fringe-only after dedicated etcd SSD — `[P3 · Low · M]`
73. Per-app Sloth SLOs (Forgejo, Authentik, ingress) + burn-rate alerts — `[P2 · Med · M]`
74. GitOps-health dashboard (e2e status, commit-vs-reconciled, drift, suspended count) — `[P2 · Med · M]`
75. Verify Claude Code telemetry metric names + enable pending settings.json wiring — `[P2 · Low · S]`
76. Tune `spec.driftDetection.ignore` on HRs that warn on benign drift — `[P1 · Med · S]`
77. **Flux alerting is dead** — this Flux version's controllers expose `gotk_reconcile_duration`
    but NOT `gotk_reconcile_condition`/`gotk_suspend_status`, so the 3 owner Flux alerts + the
    suspended-ks alert never fire (the PodMonitor scrapes fine — `up{job=…flux-controllers}=4` —
    but the metric source is missing). Fix: add a kube-state-metrics CustomResourceState config for
    the Flux CRDs (generates `gotk_resource_info{ready,suspended,…}`) + RBAC, then rewrite the 4
    alerts to it. Needs post-reconcile verification (KSM restart) — `[P1 · High · M]`

### CI / shift-left
78. Add zizmor (Actions security lint) to e2e CI — `[P1 · Med · S]`
79. mkdocs/TechDocs build in CI (catch broken links/nav) — `[P1 · Low · S]`
80. Grafana dashboard JSON validation in CI (~45 dashboards) — `[P2 · Med · S]`
81. Kyverno test-coverage gate: fail if a policy ships without tests — `[P2 · Med · M]`
82. Expand chainsaw admission tests to all Enforce-mode policies — `[P2 · Med · M]`
83. CLI tests for the untested audit policies — `[P2 · Med · M]`
84. kustomize-build smoke test for `bootstrap/` + `talos/` in CI — `[P2 · Low · S]`
85. claude-review.yml: also run on push to main (trunk-based) — `[P2 · Med · S]`
86. renovate-dry-run on push to main (config edits bypass it today) — `[P2 · Low · S]`
87. Renovate `postUpgradeTasks` run `flux-local test` so bumps self-validate — `[P2 · High · M]`
88. Enforce lefthook install (or add a `.pre-commit-config.yaml` fallback) — `[P2 · Med · S]`
89. CI: validate every PrometheusRule/ServiceMonitor carries `release: kube-prometheus-stack` — `[P2 · Med · S]`

### Repo hygiene / DX / automation
90. Backstage catalog: model all ~28 namespaces, or auto-generate from the Flux tree — `[P2 · Med · L]`
91. `add-app` skill: scaffold NetworkPolicy + alerts + restore-test + Backstage + auth by default — `[P2 · High · M]`
92. Standardize `app.kubernetes.io/*` labels via a Kyverno mutate policy — `[P2 · Med · M]`
93. Wire or delete `twitch-exporter` (orphaned — not in observability kustomization) — `[P2 · Low · S]`
94. Nightly scheduled cluster-health digest (delta summary) — `[P2 · Med · S]`
95. Schedule weekly `triage-renovate` to label/comment PR risk — `[P3 · Low · S]`
96. Auto-generate a dependency/topology diagram from `dependsOn` — `[P3 · Low · M]`
97. ADR/RFC index page auto-listing status (proposed/accepted/superseded) — `[P3 · Low · S]`

### Docs / horizon
98. Runbooks for shipped W6/W7 features: zero-trust NetworkPolicy model, ResourceQuotas, Harbor
    proxy-cache, Forgejo source — `[P2 · Med · M]`
99. Second SSD per soyo node for dedicated etcd storage (unblocks Pyroscope) — `[P3 · High · L]`
100. Add a worker / document the fringe single-worker SPOF; decide OpenBao 3-node Raft — `[P3 · High · L]`

---

## Sequencing notes

- **#11 Hubble gates #12** (don't author cluster-wide default-deny blind). #13/#14/#15 are per-ns
  zero-trust policies that can land now without Hubble (the W7 pattern).
- **#17 is de-risked** by the Harbor fully-GitOps-OIDC pattern — highest-value auth item to pull forward.
- **#9 image-verify enforce** waits on first-party signing being universal (Forgejo-migration gated).
- **#72 Pyroscope** waits on **#99** (dedicated etcd SSD).
- **#37 unblocks #38** (dynamic creds: one app before the fleet).
- **#52 restore-drill re-enable** is gated on CP memory (<~70%), not etcd.
- Keep new work clear of the **Forgejo migration** (ADR 0011–0019) and **Harbor proxy-cache** gates.
