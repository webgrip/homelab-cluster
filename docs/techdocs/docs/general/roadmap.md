# Homelab Cluster Improvement Roadmap

> **Living backlog, kept topped up at 100 open items.** As items ship, move them to the Done log
> and refill so the open count stays ~100. Maintained by the `roadmap-topup` skill.
> Re-inventoried **2026-06-21** (post node-taxonomy/storage migration; live MCP/Prometheus + posture checks).
> Tags: `[Priority · Impact · Effort]` — Priority P0–P3, Impact H/M/L, Effort S/M/L.

## Where we stand (live, 2026-06-21)

- **Flux:** all Kustomizations/HelmReleases Ready at `7f8da29`. Suspended on purpose:
  `observability/pyroscope` (etcd I/O — but see #69, the rationale just changed).
- **etcd protection — ACHIEVED.** The node-taxonomy/storage migration moved **all ~84 Longhorn
  replicas and every app pod off the 3 soyo control-planes** (42 replicas on fringe, 42 on worker-1,
  **0 on any soyo**). The soyos now run control-plane + DaemonSets only. WFFC was eliminated (every
  Longhorn StorageClass is `Immediate` — the node-locking `gitops` WFFC SC was deleted).
- **Memory:** control planes dropped from 80–83% to **65–73%** (soyo-1 73 / soyo-2 67 / soyo-3 65),
  fringe 48%, worker-1 45%. The etcd *disk* threat is gone; the residual soyo RAM is now
  control-plane + BestEffort-DaemonSet overhead (see #42), not app load. Restore drills stay **off**
  until CP RAM < ~70% (soyo-1 still just above).
- **Hardening posture (verified):** **2 PodDisruptionBudgets** (coredns, cloudflare-tunnel) · **17
  NetworkPolicies across 11 app namespaces** + **1 CiliumNetworkPolicy** (CNPG→apiserver), but
  **13 platform namespaces still unprotected**, no Hubble, no default-deny · 4 ResourceQuotas (app ns)
  · **11 of 17 Kyverno policies still `Audit`** · 0 Envoy `SecurityPolicy`, Envoy TLS floor still 1.2 ·
  all ~11 CNPG clusters single-instance (backups tiered + WAL-compressed) · Garage S3 (10.0.0.110) a
  hard SPOF · **no off-node etcd snapshot backup**.
- **Backup/DR status:** CNPG barman→Garage (current) and OpenBao raft snapshots→Garage (nightly) work.
  A **Longhorn external backup target (Garage) is now `Available`** with a `gitops-backup` RecurringJob;
  forgejo-data + gitea-mirror are labeled — but **no Longhorn backup has actually run yet** (first
  schedule 02:00; unverified — #58). RWX PVCs are blocked cluster-wide by Kyverno `disallow-rwx-pvcs`.
- **Active owner workstreams:** Forgejo migration (Renovate dual-run + Flux source, ADR 0011–0019)
  and Harbor pull-through proxy-cache (ADR 0016–0018). Sequence around their gates.

## ✅ Done log (recent)

- **Node-taxonomy + storage migration (2026-06-16→21, ADR-0025/0026/0027/0028):** the big one.
  Introduced the capability label scheme (`node.webgrip.io/pool|cpu|ram`, `storage.webgrip.io/longhorn`)
  and moved **every app + all Longhorn replicas off the 3 soyo etcd nodes** — pinned ~40 apps and all
  6 CNPG DBs to the worker pool; flipped every Longhorn SC WFFC→Immediate (killing the PV node-lock that
  excluded worker-1); deleted the over-engineered soyo-replica `gitops` SC. Solved the hard cases:
  authentik (RWX blocked by Kyverno → pinned via `cpu=high`/fringe), harbor registry+jobservice (broke
  the goharbor RollingUpdate Multi-Attach deadlock by hand), DT api-server (→StatefulSet), envoy
  (controller+proxies, no ingress blip). Retired the legacy `nodegroup`/`workload-tier` labels + the
  fringe `dedicated` taint. Shipped the Longhorn Garage backup target (BackupTarget CR — 1.11 ignores
  defaultSettings) + `gitops-backup` RecurringJob, and the `openbao-restore` runbook (surfacing that the
  unseal-key lives only in-cluster). Progresses #47/#58; supersedes the old etcd-SSD-contention framing.
- **CNPG netpol regression fix (2026-06-15):** W7 zero-trust policies had cut cnpg-system off from the
  CNPG instances and the instances off from kube-apiserver → `ClusterIsNotReady`. Fixed by moving
  cnpg-system ingress into the DB-layer ks (deadlock-proof) + the first CiliumNetworkPolicy. Progresses #15.
- **Headway batch (2026-06-14):** digest-pinned 9 unpinned images (#29); PDBs for CoreDNS + cloudflared
  (#44, the reschedulable ones). Surfaced #74: Flux alerting is dead (metric source missing).
- **Owner W6/W7 + Harbor + CNPG (2026-06-13/14):** per-namespace count-only ResourceQuotas (W6);
  zero-trust NetworkPolicies across 11 app namespaces (W7); Harbor proxy-cache + HR stall fix; CNPG
  backup tiering (WAL zstd, per-tier retention).

## ▶ Do next (top of the stack)

`#53` key escrow (owner) · `#52` etcd off-node backup · `#58` verify+restore-test Longhorn backup ·
`#42` DaemonSet right-sizing · `#34` apply-node label drop (finish migration) · `#13` platform-ns
NetworkPolicies · `#17` Prom/Alertmanager auth · `#45` admission-webhook HA · `#78` SHA-pin Actions.

---

## The 100

### Security — promote Kyverno audit → enforce (11 policies live in `Audit`)
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

### Node / Talos / storage
32. Kubernetes API audit logging → Loki — `[P2 · High · M]`
33. Add KubePrism (local API LB for kubelet→apiserver) — `[P2 · Med · S]`
34. **Finish the taxonomy migration: `task talos:apply-node MODE=no-reboot` per node** to strip the
    now-unused `nodegroup`/`workload-tier` labels (removed from the patches, still live on nodes) +
    remove the dead `register-with-taints`/cold-tier comments. Label-only, etcd-safe — `[P2 · Low · S]`
35. **Activate the `longhorn-cold` HDD tier on fringe** (ADR-0027 Phase C): wipe the leftover NTFS
    filesystem on the 1 TB HDD, add it as a Talos disk, tag it cold — offloads bulk volumes off the
    SSDs — `[P3 · Med · M]`
36. Decide secure-boot + LUKS/TPM disk encryption in an ADR (+ document the deleted Talos admission/PSA-fallback decision) — `[P3 · Med · L]`

### Secrets endgame
37. Ship dynamic Postgres credentials (ADR-0010) for one app (freshrss) — `[P2 · High · L]`
38. Roll dynamic DB creds to remaining CNPG apps; retire static DB ExternalSecrets — `[P3 · High · L]`
39. Migrate the last SOPS app secret (zomboid) → ESO — `[P2 · Med · M]`
40. Audit Reloader (`reloader.stakater.com/auto`) coverage + tune ESO `refreshInterval` per-secret — `[P2 · Med · S]`
41. Secret-rotation cadence doc for the SOPS floor (age key, talsecret, deploy key) + CI guard that
    fails when a new `*.sops.yaml` appears outside the allowed floor — `[P2 · Med · S]`

### Reliability — HA, resources, PDBs, replicas
42. **Right-size the BestEffort platform/DaemonSet pods** (cert-manager, cnpg-operator, flux-operator,
    ARC, renovate-operator, ESO, trivy-operator, guac; **longhorn-manager + alloy + spegel on the
    control-planes**) — now the dominant soyo RAM load (65–73%) and the first thing evicted under
    pressure; also unblocks `workload-hardening` Enforce — `[P1 · High · M]`
43. topologySpreadConstraints on the multi-replica apps that lack them (authentik server, mimir
    gateway) so both replicas don't co-schedule — `[P2 · Med · S]`
44. Remaining PodDisruptionBudgets: cilium-operator, k8s-gateway (after #45) — cert-manager/ESO
    webhooks handled by #45; envoy/authentik stay deferred (worker-pinned) — `[P1 · High · M]`
45. Admission-webhook HA: cert-manager + external-secrets webhooks are single-replica (`replicaCount:1`)
    on the cluster's pod-creation/cert-issuance critical path → 2 replicas + PDB + soft spread — `[P1 · High · M]`
46. k8s-gateway → 2 replicas + PDB + Flux `healthChecks` (internal-DNS SPOF, 1 replica today) — `[P1 · High · M]`
47. **Authentik node-level HA: media → Garage S3** (`AUTHENTIK_STORAGE__MEDIA__S3`), then unpin from
    `cpu=high`/fringe → `pool=worker`. Interim `cpu=high` single-node pin shipped (RWX was Kyverno-blocked);
    S3 is the only remaining path to spread the SSO across both workers — `[P2 · Med · M]`
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
56. Verify the OpenBao raft snapshot actually restores (test into kind) — runbook exists, drill doesn't — `[P2 · High · M]`
57. Offsite backup for non-DB PVCs (volsync / Longhorn S3): forgejo, authentik media, n8n, worlds — `[P2 · High · L]`
58. **Verify the new Longhorn `gitops-backup` actually completes + restore-test a volume from Garage**
    (the BackupTarget + RecurringJob shipped 06-21 and the target is `Available`, but 0 backups have
    run; trigger one now rather than waiting for 02:00, then prove restore) — `[P1 · High · S]`
59. Full DR drill of the hibernated `cnpg-disaster-recovery`; write the runbook from it — `[P2 · High · M]`
60. "Total cluster loss → restored" end-to-end runbook + periodic bootstrap-from-scratch rebuild test — `[P2 · High · M]`
61. RCA + re-enable Beyla, or remove it (undated suspension) — `[P2 · Low · S]`

### Reliability — Garage SPOF
62. Document Garage RPO/RTO + a Garage-down recovery runbook (Garage-down also fails CNPG WAL archiving
    → DBs CrashLoop — a known incident) — `[P2 · High · S]`
63. Evaluate a 2nd Garage node / replicated MinIO so 11 DBs + all Longhorn/OpenBao backups don't share
    one box — `[P2 · High · L]`

### Reliability — Flux structure & capacity
64. **GitHub fallback Flux `GitRepository` before the Forgejo source cutover** — when Flux's source
    flips to in-cluster Forgejo (ADR-0014), a forgejo/both-worker outage would strand reconciliation;
    keep a GitHub mirror as a fallback source so resilience is decoupled from forgejo uptime — `[P2 · High · M]`
65. Add `healthChecks` + `wait: true` to platform-tier Kustomizations — `[P2 · Med · M]`
66. Audit `dependsOn` graph + `postBuild.substituteFrom` coverage (~24 ks lack dependsOn;
    coredns/k8s-gateway notably) — `[P2 · Med · M]`
67. Mimir Kafka single-broker durability: PVC auto-expand or StatefulSet replacement — `[P2 · Med · M]`
68. Extend ResourceQuotas to platform namespaces (W6 covered app ns only) — `[P3 · Low · S]`

### Observability — alert/SLO coverage
69. **Re-evaluate Pyroscope return** — it was suspended for etcd-SSD I/O contention, but the migration
    moved all Longhorn I/O off the soyo SSDs, so the original blocker is largely gone; test re-enabling
    (fringe-pinned) and watch etcd fsync before/after — `[P3 · Low · M]`
70. Alert-coverage bundle: cert-expiry beyond cert-manager (OpenBao TLS), cloudflared tunnel-down
    (2 replicas but no failure alert), Mimir/Kafka memory-saturation-before-OOM — `[P2 · Med · S]`
71. Per-app Sloth SLOs (Forgejo, Authentik, ingress) + burn-rate alerts — `[P2 · Med · M]`
72. GitOps-health dashboard (e2e status, commit-vs-reconciled, drift, suspended count) — `[P2 · Med · M]`
73. Verify Claude Code telemetry metric names + enable pending settings.json wiring — `[P2 · Low · S]`
74. **Flux alerting is dead** — this Flux version's controllers expose `gotk_reconcile_duration` but NOT
    `gotk_reconcile_condition`/`gotk_suspend_status`, so the 3 owner Flux alerts + the suspended-ks alert
    never fire. Fix: add a kube-state-metrics CustomResourceState config for the Flux CRDs (generates
    `gotk_resource_info{ready,suspended,…}`) + RBAC, then rewrite the 4 alerts to it — `[P1 · High · M]`
75. Tune `spec.driftDetection.ignore` on HRs that warn on benign drift — `[P1 · Med · S]`

### CI / shift-left
76. Add zizmor (Actions security lint) to e2e CI — `[P1 · Med · S]`
77. mkdocs/TechDocs build in CI + markdownlint + link-checker (catch broken links/nav across 78 MD) — `[P1 · Low · S]`
78. Pin all GitHub Actions to commit SHAs (`actions/checkout@v4`, `claude-code-action@v1`, …) — `[P1 · Med · S]`
79. Grafana dashboard JSON validation in CI (~45 dashboards) — `[P2 · Med · S]`
80. CI workflow hardening: `timeout-minutes` on every job (none have it today) + least-privilege
    `permissions:` blocks + runner pip/mise caching — `[P2 · Med · S]`
81. Unit tests for `.claude/hooks/` (guard-secrets/destructive/skills, validate-manifest) — they're
    security-critical and untested; a regression silently disables a guard — `[P2 · Med · M]`
82. shellcheck on `scripts/` in CI + lefthook (~900 LOC unchecked) — `[P2 · Med · S]`
83. Kyverno test-coverage gate: fail if a policy ships without tests; expand chainsaw admission tests
    for all Enforce policies + CLI tests for the audit policies — `[P2 · Med · M]`
84. kustomize-build smoke test for `bootstrap/` + `talos/` in CI — `[P2 · Low · S]`
85. claude-review.yml + renovate-dry-run: also run on push to main (trunk-based; config edits bypass them today) — `[P2 · Med · S]`
86. Renovate `postUpgradeTasks` run `flux-local test` so bumps self-validate — `[P2 · High · M]`
87. Enforce lefthook install (or add a `.pre-commit-config.yaml` fallback) — `[P2 · Med · S]`
88. CI: validate every PrometheusRule/ServiceMonitor carries `release: kube-prometheus-stack` — `[P2 · Med · S]`
89. Renovate config drives Forgejo dual-run; verify both registries pull-through post-cutover — `[P2 · Med · S]`

### Repo hygiene / DX / automation
90. Backstage catalog: model all ~28 namespaces, or auto-generate from the Flux tree — `[P2 · Med · L]`
91. `add-app` skill: scaffold NetworkPolicy + alerts + restore-test + Backstage + auth by default — `[P2 · High · M]`
92. Standardize `app.kubernetes.io/*` labels via a Kyverno mutate policy — `[P2 · Med · M]`
93. Wire or delete `twitch-exporter` (orphaned — not in observability kustomization) — `[P2 · Low · S]`
94. Nightly scheduled cluster-health digest (delta summary) — `[P2 · Med · S]`
95. Schedule weekly `triage-renovate` to label/comment PR risk — `[P3 · Low · S]`
96. Auto-generate a dependency/topology diagram from `dependsOn` + an ADR/RFC status index page — `[P3 · Low · M]`

### Docs / horizon
97. Runbooks for shipped W6/W7 + migration features: zero-trust NetworkPolicy model, ResourceQuotas,
    Harbor proxy-cache, Forgejo source, the capability-label taxonomy (ADR-0025/0028) — `[P2 · Med · M]`
98. Second SSD per soyo node for fully-dedicated etcd storage — lower urgency now Longhorn I/O is off
    the soyo SSDs, but still isolates etcd from OS/image I/O — `[P3 · Med · L]`
99. **Add a 3rd worker node** — two workers means no real node-level HA headroom; a third lets replicas
    keep 3-way redundancy and apps tolerate a worker loss without landing back on soyos. Also decide
    OpenBao 3-node Raft — `[P2 · High · L]`
100. Backup-coverage matrix doc: every stateful app × {CNPG | Longhorn-S3 | OpenBao-snapshot | none},
     so gaps (authentik media, n8n, worlds) are visible at a glance — `[P3 · Med · S]`

---

## Sequencing notes

- **#34 apply-node finishes the migration** — label-only, etcd-safe, do it whenever; nothing breaks
  until then (the live labels are just unused).
- **#58 is the highest-value DR proof** — the Longhorn backup machinery is wired but unproven; a single
  triggered backup + restore closes the last untested DR claim cheaply.
- **#11 Hubble gates #12** (don't author cluster-wide default-deny blind). #13/#14/#15 land now (W7 pattern).
- **#42 DaemonSet right-sizing is the cheap correctness win** — BestEffort system pods are first evicted
  at high CP memory; it also unblocks #5 Enforce. The migration relaxed but didn't remove soyo RAM pressure.
- **#45 (webhook HA) before #44** — the cert-manager/ESO webhooks are the admission-path SPOF.
- **#47 needs S3 (#57-adjacent)** — authentik can't be node-HA until its media leaves the RWO volume.
- **#52 etcd backup is the missing leg** of DR — CNPG/PVC backups exist, etcd doesn't.
- **#64 GitHub fallback source** must land **before** the Forgejo Flux-source cutover (ADR-0014), not after.
- **#37 unblocks #38** (dynamic creds: one app before the fleet). **#55 restore-drill re-enable** gated on
  CP RAM (<~70%), not etcd — soyo-1 (73%) is the holdout.
- Keep new work clear of the **Forgejo migration** (ADR 0011–0019) and **Harbor proxy-cache** gates.
