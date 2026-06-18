# Homelab Cluster Improvement Roadmap

> **Living backlog, kept topped up at 100 open items.** As items ship, move them to the Done log
> and refill so the open count stays ~100. Maintained by the `roadmap-topup` skill.
> Re-inventoried **2026-06-16** (3 parallel deep audits + live MCP/Prometheus checks).
> Tags: `[Priority · Impact · Effort]` — Priority P0–P3, Impact H/M/L, Effort S/M/L.

## Where we stand (live, 2026-06-16)

- **Flux:** all Kustomizations Ready at `ab9aff3` — the authentik/harbor/n8n DBs that flapped
  `InProgress` settled once the W7 CNPG→apiserver netpol regression was fixed (`ab9aff3`).
  Suspended on purpose: `observability/pyroscope` (pinned at older `1dd81ad`; etcd I/O).
- **Memory:** control planes **80–83%** (soyo-1 81.7 / soyo-2 83.2 / soyo-3 79.7), fringe 69.6% —
  still the binding constraint. Restore drills stay **off**. BestEffort system pods are the first
  thing the kubelet evicts here, which is why #44/#45 (resource limits/HA) moved up.
- **Hardening posture (verified):** **2 PodDisruptionBudgets** (coredns, cloudflare-tunnel) · **16
  NetworkPolicies across 11 app namespaces** + **1 CiliumNetworkPolicy** (CNPG→apiserver), but
  **13 platform namespaces still unprotected**, no Hubble, no default-deny · 4 ResourceQuotas (app
  ns) · **10 of 16 Kyverno policies still `Audit`** · 0 Envoy `SecurityPolicy`, Envoy TLS floor still
  1.2 · all ~11 CNPG clusters single-instance (backups tiered + WAL-compressed) · Garage S3
  (10.0.0.110) a hard SPOF · **no off-node etcd snapshot backup**.
- **Active owner workstreams:** Forgejo migration (Renovate dual-run + Flux source, ADR 0011–0019)
  and Harbor pull-through proxy-cache (ADR 0016–0018). Sequence around their gates.

## ✅ Done log (recent)

- **CNPG netpol regression fix (2026-06-15):** the W7 zero-trust policies had cut cnpg-system off from
  the CNPG instances and the instances off from kube-apiserver → clusters stuck `ClusterIsNotReady`/
  `InProgress`. Fixed by moving cnpg-system ingress into the DB-layer ks (deadlock-proof) and adding
  the first CiliumNetworkPolicy (CNPG egress to the `kube-apiserver` entity). Progresses #15.
- **Headway batch (2026-06-14):** digest-pinned 9 unpinned images (#29 — openbao/aws-cli/alpine-k8s/
  dind/forgejo-runner; harbor-proxy left to the owner); PDBs for CoreDNS + cloudflared (#44, the
  reschedulable ones; authentik/envoy deferred — fringe-pinned, a PDB would deadlock fringe drains).
  Also surfaced #77: the Flux alerting is dead (metric source missing, not just the PodMonitor).
- **Alerts batch (2026-06-14):** node-memory pressure; OpenBao snapshot staleness; **Flux PodMonitor**
  (scrapes fine — `up=4` — but the controllers don't expose the condition/suspend metrics, so the
  Flux NotReady/Drift/Suspended alerts are still dark — see #77) + the suspended-Kustomization alert.
- **Owner W6/W7 + Harbor + CNPG (2026-06-13/14):** per-namespace count-only ResourceQuotas (W6);
  zero-trust NetworkPolicies across 11 app namespaces (W7); Harbor pull-through proxy-cache + HR
  stall fix; CNPG backup tiering (DBs 1–5, WAL zstd compression, per-tier retention).
- **P1 batch (2026-06-13):** gitleaks history clean + config; Flux drift-detection `warn`; ESO docs →
  OpenBao (migration complete); cloudflared 2 replicas; priorityClassName cert-manager/ESO/CoreDNS;
  Authentik server 2 replicas.

## ▶ Do next (top of the stack)

`#53` key escrow (owner) · `#51` etcd off-node backup · `#44` resource-limits/PDBs · `#45` admission
-webhook HA · `#13` platform-ns NetworkPolicies · `#17` Prom/Alertmanager auth · `#21` searxng root ·
`#78` SHA-pin Actions.

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
    renovate, minecraft, zomboid) — also covers alloy-agent's `hostNetwork` syslog listener — `[P1 · High · M]`
14. Crown-jewel netpol: restrict OpenBao ingress to ESO + unsealer only — `[P2 · High · M]`
15. Crown-jewel netpol: CNPG clusters (app + barman egress only) — extends the CNPG→apiserver
    CiliumNetworkPolicy already shipped — `[P2 · High · M]`
16. Extract a reusable NetworkPolicy component/base (DRY the 11 hand-written zero-trust policies) — `[P2 · Med · S]`

### Security — auth & exposure
17. Prometheus + Alertmanager behind Authentik (Envoy `SecurityPolicy` OIDC) — `[P1 · High · M]`
18. Auth-matrix sweep: Longhorn UI, Policy Reporter, OpenBao UI, Backstage (all LAN-exposed, no auth) — `[P2 · High · M]`
19. Document-or-gate public envoy-external routes (invoiceninja, flux-ui, renovate, twitch) — `[P2 · Med · M]`
20. Envoy hardening: proxy-pod `securityContext` (EnvoyProxy CRD) + raise ClientTrafficPolicy TLS
    floor `minVersion: "1.2"` → `"1.3"` (`envoy.yaml:155`) — `[P2 · Med · S]`

### Security — per-app pod hardening
21. searxng: fix `runAsNonRoot:false` + `readOnlyRootFilesystem:false` (explicit violation) — `[P1 · High · M]`
22. invoiceninja: pod + container securityContext — the `copy-app` init runs `runAsUser:0` and the
    FPM/scheduler containers lack `runAsNonRoot`/cap-drops (`invoiceninja-deployment.yaml`) — `[P1 · Med · M]`
23. sparkyfitness + zomboid: drop `runAsNonRoot:false` (the main `workload-hardening` violators) — `[P2 · Med · M]`
24. dependency-track SBOM-uploader CronJob: fix `runAsNonRoot:false` — `[P2 · Med · S]`
25. Observability stack securityContext: loki, tempo, mimir, blackbox, k6, sloth, alloy — `[P2 · Med · M]`
26. KEDA controller/metrics-server securityContext — `[P2 · Med · S]`
27. drawio + excalidraw + freshrss: pod securityContext (+ drawio `resources.requests`) — `[P2 · Low · S]`
28. arc-systems runners: add `seccompProfile: RuntimeDefault` + harden/document the DinD/CI threat model — `[P2 · High · M]`
29. external-secrets: add container securityContext (drop caps, `readOnlyRootFilesystem`, no PE) to
    operator/webhook/cert-controller — `[P2 · Med · S]`

### Security — image supply chain
30. Finish digest-pinning (harbor-proxy-config, owner) + Renovate `digestPin` for CronJob/runner
    images going forward — `[P2 · Med · S]`
31. Finish ADR-0008 rootless CI builds (BuildKit, kill DinD) — `[P2 · Med · M]`

### Security — node / Talos
32. Kubernetes API audit logging → Loki — `[P2 · High · M]`
33. Add KubePrism (local API LB for kubelet→apiserver) — `[P2 · Med · S]`
34. Decide secure-boot + LUKS/TPM disk encryption in an ADR — `[P3 · Med · L]`
35. Document the deleted Talos admission control / PSA-fallback decision — `[P3 · Low · S]`

### Secrets endgame
36. Ship dynamic Postgres credentials (ADR-0010) for one app (freshrss) — `[P2 · High · L]`
37. Roll dynamic DB creds to remaining CNPG apps; retire static DB ExternalSecrets — `[P3 · High · L]`
38. Migrate the last SOPS app secret (zomboid) → ESO — `[P2 · Med · M]`
39. Audit Reloader (`reloader.stakater.com/auto`) coverage + tune ESO `refreshInterval` per-secret — `[P2 · Med · S]`
40. Secret-rotation cadence doc for the SOPS floor (age key, talsecret, deploy key) — `[P2 · Med · S]`
41. CI guard: fail when a new `*.sops.yaml` appears outside the allowed floor — `[P2 · Med · S]`

### Reliability — HA, resources, PDBs, replicas
42. Resource requests/limits on the BestEffort platform HelmReleases (cert-manager, cnpg-operator,
    flux-operator, ARC, renovate-operator, ESO, trivy-operator, guac) — first to be OOM-evicted at
    80%+ CP memory; also unblocks `workload-hardening` Enforce — `[P1 · High · M]`
43. topologySpreadConstraints on the multi-replica apps that lack them (authentik server, mimir
    gateway) so both replicas don't co-schedule — `[P2 · Med · S]`
44. Remaining PodDisruptionBudgets: cilium-operator, k8s-gateway (after #45) — cert-manager/ESO
    webhooks handled by #45; envoy/authentik stay deferred (fringe-pinned) — `[P1 · High · M]`
45. Admission-webhook HA: cert-manager + external-secrets webhooks are single-replica (`replicaCount:1`)
    on the cluster's pod-creation/cert-issuance critical path → 2 replicas + PDB + soft spread — `[P1 · High · M]`
46. k8s-gateway → 2 replicas + PDB + Flux `healthChecks` (internal-DNS SPOF, 1 replica today) — `[P1 · High · M]`
47. Authentik node-level HA: media → Garage S3, then unpin from `fringe` — `[P2 · Med · M]`
48. HelmRelease resilience: add `install/upgrade.remediation.retries` + explicit `timeout` to the
    platform HRs that lack them (ESO, trust-manager, cert-manager, reloader, metrics-server) — `[P2 · Med · S]`
49. Selected CNPG clusters → 2 instances (authentik, harbor, forgejo) — `[P2 · High · M]`
50. HA review: single-replica metrics-server / reloader / alloy-gateway / mcp-grafana / loki / tempo
    (loki+tempo on fringe = observability blind on node loss) — `[P3 · Med · S]`
51. PriorityClasses for envoy-gateway + the remaining platform tier (k8s-gateway, reloader, metrics-server) — `[P2 · Med · S]`

### Reliability — backup & DR
52. **etcd off-node snapshot backup → Garage S3** (no automated etcd backup exists; logical
    corruption/total-loss is currently unrecoverable) — `[P1 · High · M]`
53. Off-site escrow of `age.key` + `talsecret` — verify a copy exists outside git — `[P0 · High · S]`
54. Restore-test components for the 2 CNPG apps still missing them (authentik, grafana) — `[P1 · Med · M]`
55. Re-enable restore drills (staggered) once CP RAM < ~70% — `[P2 · Med · S]`
56. Verify the OpenBao raft snapshot actually restores (test into kind) — `[P2 · High · M]`
57. Offsite backup for non-DB PVCs (volsync / Longhorn S3): forgejo, authentik media, n8n, worlds — `[P2 · High · L]`
58. Configure a Longhorn external backup target + scheduled backups — `[P2 · Med · M]`
59. Full DR drill of the hibernated `cnpg-disaster-recovery`; write the runbook from it — `[P2 · High · M]`
60. "Total cluster loss → restored" end-to-end runbook + periodic bootstrap-from-scratch rebuild test — `[P2 · High · M]`
61. RCA + re-enable Beyla, or remove it (undated suspension) — `[P2 · Low · S]`

### Reliability — Garage SPOF
62. Document Garage RPO/RTO + a Garage-down recovery runbook — `[P2 · High · S]`
63. Evaluate a 2nd Garage node / replicated MinIO so 11 DBs don't share one box — `[P3 · High · L]`

### Reliability — Flux structure & capacity
64. Add `healthChecks` + `wait: true` to platform-tier Kustomizations — `[P2 · Med · M]`
65. Audit `dependsOn` graph + `postBuild.substituteFrom` coverage (~24 ks lack dependsOn;
    coredns/k8s-gateway notably) — `[P2 · Med · M]`
66. Mimir Kafka single-broker durability: PVC auto-expand or StatefulSet replacement — `[P2 · Med · M]`
67. Extend ResourceQuotas to platform namespaces (W6 covered app ns only) — `[P3 · Low · S]`

### Observability — alert/SLO coverage
68. Alert-coverage bundle: cert-expiry beyond cert-manager (OpenBao TLS), cloudflared tunnel-down
    (2 replicas but no failure alert), Mimir/Kafka memory-saturation-before-OOM — `[P2 · Med · S]`
69. Pyroscope return on fringe-only after dedicated etcd SSD — `[P3 · Low · M]`
70. Per-app Sloth SLOs (Forgejo, Authentik, ingress) + burn-rate alerts — `[P2 · Med · M]`
71. GitOps-health dashboard (e2e status, commit-vs-reconciled, drift, suspended count) — `[P2 · Med · M]`
72. Verify Claude Code telemetry metric names + enable pending settings.json wiring — `[P2 · Low · S]`
73. Tune `spec.driftDetection.ignore` on HRs that warn on benign drift — `[P1 · Med · S]`
74. **Flux alerting is dead** — this Flux version's controllers expose `gotk_reconcile_duration`
    but NOT `gotk_reconcile_condition`/`gotk_suspend_status`, so the 3 owner Flux alerts + the
    suspended-ks alert never fire (the PodMonitor scrapes fine — `up{job=…flux-controllers}=4` —
    but the metric source is missing). Fix: add a kube-state-metrics CustomResourceState config for
    the Flux CRDs (generates `gotk_resource_info{ready,suspended,…}`) + RBAC, then rewrite the 4
    alerts to it. Needs post-reconcile verification (KSM restart) — `[P1 · High · M]`

### CI / shift-left
75. Add zizmor (Actions security lint) to e2e CI — `[P1 · Med · S]`
76. mkdocs/TechDocs build in CI + markdownlint + link-checker (catch broken links/nav across 77 MD) — `[P1 · Low · S]`
77. Grafana dashboard JSON validation in CI (~45 dashboards) — `[P2 · Med · S]`
78. Pin all GitHub Actions to commit SHAs (`actions/checkout@v4`, `claude-code-action@v1`, …) — `[P1 · Med · S]`
79. CI workflow hardening: `timeout-minutes` on every job (none have it today) + least-privilege
    `permissions:` blocks + runner pip/mise caching — `[P2 · Med · S]`
80. Unit tests for `.claude/hooks/` (guard-secrets/destructive/skills, validate-manifest) — they're
    security-critical and untested; a regression silently disables a guard — `[P2 · Med · M]`
81. shellcheck on `scripts/` in CI + lefthook (~900 LOC unchecked) — `[P2 · Med · S]`
82. Kyverno test-coverage gate: fail if a policy ships without tests — `[P2 · Med · M]`
83. Expand policy test coverage: chainsaw admission tests for all Enforce policies + CLI tests for the audit policies — `[P2 · Med · M]`
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
- **#42 resource-limits is the cheap correctness win** right now — BestEffort system pods (cert-manager,
  cnpg-operator, ESO, ARC…) are the first evicted at 80%+ CP memory; it also unblocks #5 Enforce.
- **#45 (webhook HA) before #44** — the cert-manager/ESO webhooks are the admission-path SPOF; PDBs
  without a 2nd replica just block drains.
- **#17 is de-risked** by the Harbor fully-GitOps-OIDC pattern — highest-value auth item to pull forward.
- **#52 etcd backup is the missing leg** of DR — CNPG/PVC backups exist, etcd doesn't.
- **#69 Pyroscope** waits on **#99** (dedicated etcd SSD). **#36 unblocks #37** (dynamic creds: one
  app before the fleet). **#55 restore-drill re-enable** is gated on CP memory (<~70%), not etcd.
- Keep new work clear of the **Forgejo migration** (ADR 0011–0019) and **Harbor proxy-cache** gates.
</content>
</invoke>
