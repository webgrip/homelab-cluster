# Homelab Cluster Improvement Roadmap

> **Living backlog, kept topped up at 100 open items.** As items ship, move them to the Done
> log and promote/refill so the open count stays ~100. Re-inventoried **2026-06-13** against live
> cluster state + git history (3 parallel deep audits + live MCP/Prometheus checks).
> Tags per item: `[Priority · Impact · Effort]` — Priority P0–P3, Impact H/M/L, Effort S/M/L.

## Where we stand (live, 2026-06-13)

- **Flux:** all Kustomizations/HelmReleases Ready. Suspended on purpose: `observability/pyroscope`
  (etcd I/O), `observability/beyla` (stability), `drawio` (unused).
- **etcd:** healthy — ~198 MB, fragmentation 1.33 (< 1.5). The defrag/load-shedding worked.
- **Memory:** control planes soyo-1/2/3 at ~78–80% used; fringe-workstation ~64%. Still the
  binding constraint — restore drills stay **off** until CP RAM frees.
- **Hardening posture (verified):** 0 PodDisruptionBudgets · 6 NetworkPolicies, 0 CiliumNetworkPolicy
  (no default-deny) · Hubble disabled · 10 of 16 Kyverno policies still `Audit` · 0 Envoy
  `SecurityPolicy` · all ~10 CNPG clusters single-instance · Garage S3 (10.0.0.110) a hard SPOF.
- **Active owner workstream:** Forgejo migration — Renovate dual-run (ADR 0011–0013) and Flux
  GitOps source → Forgejo (ADR 0014–0015). Sequence new work around its phase gates.

## ✅ Done log (recent)

- **P0 batch (2026-06-12):** coredns split-DNS; zomboid/cnpg-dr hygiene; CI yamllint + alert-validator
  on push; ~30 alert-annotation fixes + Harbor metric-name bug; ESO not-ready alerts; InvoiceNinja
  DB backup; etcd defrag (resolved). flux-local fixed to run locally.
- **P1 batch (2026-06-13):** gitleaks history scan clean + `.gitleaks.toml`; Flux drift-detection
  `warn`; ESO docs Infisical→OpenBao; cloudflared 2 replicas; priorityClassName on
  cert-manager/ESO/CoreDNS (Longhorn already `longhorn-critical`+Guaranteed); Authentik server
  2 replicas (pod-level).
- **Owner hardening sprint (W3–W5):** pod+container hardening of first-party workloads (authentik,
  forgejo, harbor per-component resources, grafana-operator→OCI); Harbor OIDC fully GitOps + RS256;
  Kyverno tenancy labels + third-party exceptions + admission-controller node-spread; resource
  right-sizing + ~40k histogram-series pruned; Longhorn CPU/LimitRange fixes.

## ▶ Do next (top of the stack)

`#1` key escrow · `#11` Hubble · `#17` Prometheus/Alertmanager auth · `#21` PDBs ·
`#28` searxng root fix · `#41` digest-pin images · `#46` mkdocs+zizmor in CI · `#61` restore-test components.

---

## The 100

### Security — promote Kyverno audit → enforce (10 policies live in `Audit`)
1. Promote `require-probes` → Enforce (after probe-coverage sweep) — `[P1 · Med · M]`
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
11. Enable Hubble (gates all network policy work) — `[P1 · Med · S]`
12. Default-deny `CiliumClusterwideNetworkPolicy` + per-ns allows from observed flows — `[P2 · High · L]`
13. Label namespaces for the existing Kyverno default-network-policy generator (opt-in rollout) — `[P1 · High · S]`
14. Crown-jewel netpol: restrict OpenBao ingress to ESO + unsealer only — `[P2 · High · M]`
15. Crown-jewel netpol: CNPG clusters (app + barman egress only) — `[P2 · High · M]`
16. Grafana Hubble flow dashboards once Hubble is on — `[P3 · Low · S]`

### Security — auth & exposure
17. Prometheus + Alertmanager behind Authentik (Envoy `SecurityPolicy` OIDC) — `[P1 · High · M]`
18. Auth-matrix sweep: Longhorn UI, Policy Reporter, OpenBao UI, Backstage — `[P2 · High · M]`
19. Document-or-gate public envoy-external routes (invoiceninja, flux-ui, renovate, twitch) — `[P2 · Med · M]`
20. Add securityContext to the Envoy proxy pods (EnvoyProxy CRD) — `[P3 · Low · S]`

### Security — per-app pod hardening
21. searxng: fix `runAsNonRoot:false` + `readOnlyRootFilesystem:false` (explicit violation) — `[P1 · High · M]`
22. invoiceninja: add pod + container securityContext (fsGroup, seccomp, drop caps) — `[P1 · Med · M]`
23. Observability stack securityContext: loki, tempo, mimir, blackbox, k6, sloth, alloy — `[P2 · Med · M]`
24. KEDA controller/metrics-server securityContext — `[P2 · Med · S]`
25. drawio + excalidraw: securityContext + drawio `resources.requests` — `[P2 · Low · S]`
26. freshrss: explicit runAsUser/fsGroup/seccomp — `[P2 · Med · S]`
27. minecraft + zomboid: best-effort hardening (seccomp, drop caps) — `[P3 · Med · M]`
28. arc-systems runners: harden + document the DinD/CI threat model — `[P2 · High · M]`

### Security — image supply chain
29. Digest-pin the 9 unpinned images (openbao, aws-cli, alpine/k8s, forgejo runner, dind) — `[P1 · High · S]`
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
49. metrics-server / reloader / alloy-gateway HA review — `[P3 · Med · S]`
50. PriorityClasses for the remaining platform tier (k8s-gateway, reloader, metrics-server) — `[P2 · Med · S]`

### Reliability — backup & DR
51. Restore-test components for authentik, grafana, guac, dependency-track (author, keep suspended) — `[P1 · Med · M]`
52. Re-enable restore drills (staggered) once CP RAM < ~70% — `[P2 · Med · S]`
53. Off-site escrow of `age.key` + `talsecret` — verify a copy exists outside git — `[P0 · High · S]`
54. OpenBao raft-snapshot staleness alert — `[P0 · Med · S]`
55. Verify OpenBao raft snapshot actually restores (test into kind) — `[P2 · High · M]`
56. Offsite backup for non-DB PVCs (volsync / Longhorn S3): forgejo, authentik media, n8n, worlds — `[P2 · High · L]`
57. Configure Longhorn external backup target + scheduled backups — `[P2 · Med · M]`
58. Full DR drill of the hibernated `cnpg-disaster-recovery`; write the runbook from it — `[P2 · High · M]`
59. "Total cluster loss → restored" end-to-end runbook — `[P2 · High · M]`
60. Periodic (quarterly) bootstrap-from-scratch rebuild test — `[P3 · Med · M]`
61. CI check: bootstrap helmfile chart versions match the HelmReleases — `[P2 · Med · M]`

### Reliability — Garage SPOF
62. Document Garage RPO/RTO + a Garage-down recovery runbook — `[P2 · High · S]`
63. Evaluate a 2nd Garage node / replicated MinIO so 10 DBs don't share one box — `[P3 · High · L]`

### Reliability — Flux structure
64. Add `healthChecks` + `wait: true` to platform-tier Kustomizations — `[P2 · Med · M]`
65. Audit `dependsOn` graph (ESO-before-consumers, CNPG-operator-before-clusters) — `[P2 · Med · M]`
66. Audit `postBuild.substituteFrom` coverage (the ~11 ks.yaml without it) — `[P2 · Low · S]`
67. Tune `spec.driftDetection.ignore` on HRs that warn on benign drift — `[P1 · Med · S]`

### Observability — alert coverage
68. Cert-expiry alerts beyond cert-manager (OpenBao TLS, hand-rolled) — `[P2 · Med · S]`
69. cloudflared tunnel-connectivity alert — `[P2 · Med · S]`
70. `KustomizationSuspended > N days` alert (pyroscope/beyla/drawio rot invisibly) — `[P0 · Med · S]`
71. Node memory allocatable-vs-requested > 85% alert — `[P0 · Med · S]`
72. Mimir/Kafka memory-saturation alert before OOM — `[P2 · Med · S]`
73. Re-enable or remove Beyla (decide + date the suspension) — `[P2 · Low · S]`
74. Pyroscope return on fringe-only after dedicated etcd SSD — `[P3 · Low · M]`
75. Sloth SLOs for Forgejo, Authentik, ingress + burn-rate alerts — `[P2 · Med · M]`
76. GitOps-health dashboard (e2e status, commit-vs-reconciled, drift, suspended count) — `[P2 · Med · M]`
77. Verify Claude Code telemetry metric names + enable pending settings.json wiring — `[P2 · Low · S]`

### CI / shift-left
78. Add zizmor (Actions security lint) to e2e CI — `[P1 · Med · S]`
79. mkdocs/TechDocs build in CI (catch broken links/nav) — `[P1 · Low · S]`
80. Grafana dashboard JSON validation in CI — `[P2 · Med · M]`
81. Kyverno test-coverage gate: fail if a policy ships without tests — `[P2 · Med · M]`
82. Expand chainsaw admission tests to all Enforce-mode policies — `[P2 · Med · M]`
83. CLI tests for the untested audit policies — `[P2 · Med · M]`
84. kustomize-build smoke test for `bootstrap/` + `talos/` in CI — `[P2 · Low · S]`
85. claude-review.yml: also run on push to main (trunk-based) — `[P2 · Med · S]`
86. renovate-dry-run on push to main (config edits bypass it today) — `[P2 · Low · S]`
87. Renovate `postUpgradeTasks` run `flux-local test` so chart bumps self-validate — `[P2 · High · M]`
88. Enforce lefthook install (or add a `.pre-commit-config.yaml` fallback) — `[P2 · Med · S]`
89. CI: validate every PrometheusRule/ServiceMonitor carries `release: kube-prometheus-stack` — `[P2 · Med · S]`

### Repo hygiene / DX / automation
90. Backstage catalog: model all ~28 namespaces, or auto-generate from the Flux tree — `[P2 · Med · L]`
91. `add-app` skill: scaffold alerts + restore-test + Backstage entry + auth by default — `[P2 · High · M]`
92. Standardize `app.kubernetes.io/*` labels via a Kyverno mutate policy — `[P2 · Med · M]`
93. Wire or delete `twitch-exporter` (orphaned in Renovate ignore) — `[P2 · Low · S]`
94. Nightly scheduled cluster-health digest (delta summary) — `[P2 · Med · S]`
95. Schedule weekly `triage-renovate` to label/comment PR risk — `[P3 · Low · S]`
96. Auto-generate a dependency/topology diagram from `dependsOn` — `[P3 · Low · M]`
97. ADR/RFC index page auto-listing status (proposed/accepted/superseded) — `[P3 · Low · S]`

### Docs / knowledge / horizon
98. Forgejo-as-Flux-source runbook (mirror repoint, webhook re-register, failover) — `[P2 · Med · M]`
99. Second SSD per soyo node for dedicated etcd storage (unblocks Pyroscope) — `[P3 · High · L]`
100. Add a worker / document the fringe-workstation single-worker SPOF; OpenBao 3-node decision — `[P3 · High · L]`

---

## Sequencing notes

- **#11 Hubble gates #12–#15** (don't author default-deny blind).
- **#17 is de-risked** by the Harbor fully-GitOps-OIDC pattern — highest-value auth item to pull forward.
- **#52 restore-drill re-enable is gated on CP memory**, not etcd anymore. Watch soyo-* memory.
- **#9 image-verify enforce** waits on first-party signing being universal.
- **#74 Pyroscope** waits on **#99** (dedicated etcd SSD).
- **#37 unblocks #38** (dynamic creds: one app before the fleet).
- Keep new work clear of the **Forgejo migration** (ADR 0011–0015) phase gates.
