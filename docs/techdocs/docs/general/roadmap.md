# Homelab Cluster Improvement Roadmap

> **Living backlog, kept topped up at 100 open items.** As items ship, move them to the Done log
> and refill so the open count stays ~100. Maintained by the `roadmap-topup` skill.
> Re-inventoried **2026-07-02** (post decision-landscape audit; live MCP/PromQL + posture checks +
> 3-way deep repo audit). Tags: `[Priority · Impact · Effort]` — Priority P0–P3, Impact H/M/L,
> Effort S/M/L.

## Where we stand (live, 2026-07-02)

- **Flux:** one NOT-READY: `kepler/kepler` (Helm upgrade timeout on the DaemonSet — #67). Suspended
  by design: `observability/pyroscope` (ADR-0037; sole gate = owner etcd defrag). Commented out of
  kustomizations (zombie state): **tempo, beyla, k6-operator, k6-canaries** (observability), **drawio**
  (RAM), **zomboid** (last SOPS secret) — #68/#40.
- **Nodes:** control-plane RAM **80 / 71 / 64 %** (worst soyo regressed from 73 % on 06-21 — #38);
  workers 52 / 41 %. etcd healthy: WAL-fsync p99 **3.9 ms**, DB ~1.2 GiB total (defrag still pending).
- **Hardening posture (verified):** **2 PodDisruptionBudgets** · **17 NetworkPolicies across 11
  namespaces** + 2 CiliumNetworkPolicies (platform ns — incl. `security`, `forgejo`, `observability`,
  `network` — still open-network) · 4 count-only ResourceQuotas, **zero compute quotas** · **0 Envoy
  SecurityPolicy**, TLS floor 1.2 · Kyverno **11 Audit / 6 Enforce** · all 11 CNPG DBs single-instance ·
  Garage S3 single host behind every backup · **no alert reaches a human** (VMAlertmanager routes to
  `"null"`, Grafana has no contact points) · Falco + Tetragon uninstalled · ARC runners 0/0.
- **Decision debt is now mapped:** the 2026-07-02 [decision-landscape audit](../adr/landscape.md)
  registered 11 gaps, each with a Proposed RFC (alert delivery, backup/DR, Garage, runtime detection,
  foundations, ingress/DNS, identity, Postgres layer, observability pipeline, image signing, ARC).
  Many items below are those RFCs' implementation legs.
- **Active owner workstreams (in flight at re-inventory):** the freshrss PgBouncer dynamic-creds
  iteration (ADR-0016 — sidecar SIGHUP-reload shape in the working tree), the MADR ADR conversion
  (`adr-writer` skill), and a docs link-checker landing in e2e CI. The Flux-source cutover
  (ADR-0011/0015) remains the big gate.

## ✅ Done log (recent)

- **Decision-landscape audit (2026-07-02, `aa58de83`):** coverage map of all 39 ADRs + 16 RFC-tier
  docs (`adr/landscape.md`), 11 gap RFCs written and registered. ADR corpus normalized with
  corrected statuses (`57b1d15c`); 7 dead runbooks pruned; general docs refreshed; nav rebuilt;
  vestigial `release: kube-prometheus-stack` guard-hook check retired.
- **VictoriaMetrics swap (2026-07-01→02, ADR-0034, PR #360):** kube-prometheus-stack →
  modular vm-operator + VMSingle/VMAgent/VMAlert/VMAlertmanager + standalone KSM/node-exporter;
  CoreDNS scrape + vmagent deadlock + CRD-race fixed; VMSingle right-sized + backend-health
  dashboard; Watchdog/KubeNodeNotReady/KubeJobFailed house rules restored; umbrella-chart
  re-evaluation done — stayed modular. Mimir + Kafka removed (all Mimir roadmap items obsolete).
- **Default-deny ratified (2026-07-01, ADR-0006 `7051e70d`):** opt-in per-namespace generator +
  `cnpg-netpol`/`gateway-egress` components + CI guard — recorded and Accepted (mechanism had
  shipped W7). Supersedes the old Hubble-first cluster-wide plan.
- **Dynamic DB creds (ADR-0016, 2026-07-01→02):** database engine + `vault_admin` + `openbao-db`
  store + PgBouncer pipeline built; freshrss pilot cut over, then reverted ×2 (PG16 ADMIN OPTION +
  sidecar startup) — infra stands, pilot iteration continuing (#41).
- **Harbor proxy Phase-1 cutover (2026-06-23, ADR-0023/17/18):** mirror on all 5 nodes, fallback
  drill passed, six upstreams, non-bootstrap OCI charts through the proxy. CI perf decisions
  (ADR-0028/36) accepted 06-25.
- **Authentik login repair (2026-06-30→07-02):** inline single-page password flow fixed (KeyOf
  forward-ref bug); dead n8n/authentik OIDC half-config removed. Renovate presets re-homed to
  Forgejo (`local>webgrip/renovate-config:forgejo`, prCreation:immediate).
- **Node-taxonomy + storage migration (2026-06-16→21, ADR-0001…0029):** every app + all Longhorn
  replicas off the soyos; capability labels; Longhorn Garage backup target + gitops-backup
  RecurringJob; openbao-restore runbook. (Detail in git history / the ADRs.)

## ▶ Do next (top of the stack)

`#64` alert channel (end the null-receiver era) · `#39` OpenBao unseal-key escrow · `#53` age.key/talsecret
escrow verify · `#67` kepler fix-or-retire (the one NOT-READY) · `#38` soyo RAM regression · `#43`
webhook HA · `#55` prove the Longhorn backup · `#8` security-ns default-deny · `#84` Forgejo CI parity
(gates the cutover).

---

## The 100

### Security — Kyverno audit→enforce (11 policies still Audit; ADR-0032 waves)

1. Promote `require-probes` → Enforce (cleanest next wave; app probes already conformant) — `[P1 · M · S]`
2. Promote `namespace-tenancy` → Enforce — `[P2 · M · S]`
3. Promote `rbac-least-privilege` → Enforce (zero in-tree violations found) — `[P2 · M · S]`
4. Pin real tags on drawio/plantuml/excalidraw (`latest@sha256` pseudo-tags) → unblocks
   `image-hygiene` promotion — `[P2 · L · S]`
5. Promote `workload-hardening` → Enforce, ns-by-ns, after the pod-hardening sweep (#21–26) — `[P2 · H · M]`
6. Promote `image-verify-harbor` (first-party signatures) → Enforce — the first verify wave, with
   verification-infra namespaces carved out ([RFC](../rfc/rfc-image-signing-verification.md)) — `[P2 · H · M]`
7. Burn down the `storage-cnpg-governance` test-coverage debt + add pass-cases to the enforce suites — `[P2 · M · M]`

### Security — network containment (ADR-0006 rollout beyond app namespaces)

8. Default-deny the `security` namespace — OpenBao/ESO/cosign crown jewels currently sit on a flat
   network — `[P1 · H · M]`
9. Default-deny the `forgejo` namespace (git server + privileged DinD CI runners) — `[P1 · H · M]`
10. Default-deny `observability` + `network` namespaces — `[P2 · M · M]`
11. Default-deny the remaining platform/game namespaces (cnpg-system, cert-manager, keda, renovate,
    kepler, longhorn-system, kube-system, flux-system, minecraft) — `[P2 · M · L]`
12. OpenBao ingress NetworkPolicy: ESO + unsealer + gateway only — `[P1 · H · M]`
13. dependency-track + guac DB layers adopt the `cnpg-netpol` component (Postgres reachable
    cluster-wide today) — `[P2 · M · S]`
14. Kyverno guard: explicit opt-in label required on `envoy-external` HTTPRoutes
    ([RFC](../rfc/rfc-ingress-dns-edge.md)) — `[P2 · M · S]`
15. Rate-limiting / SecurityPolicy baseline on the public envoy-external routes — `[P2 · M · M]`

### Security — auth & identity ([RFC](../rfc/rfc-identity-sso.md))

16. Forward-auth pilot: Authentik proxy outpost + Envoy `SecurityPolicy` on the Longhorn UI (it can
    delete volumes; today LAN-open) — `[P1 · H · M]`
17. Roll forward-auth to the remaining unauthenticated UIs (flux-ui, policy-reporter,
    vmsingle/vmalertmanager routes, searxng, excalidraw) — `[P2 · H · M]`
18. Route-auth classification matrix in `applications.md`: every HTTPRoute = OIDC / forward-auth /
    app-local / deliberately-open — `[P2 · M · S]`
19. Retroactive identity ADRs via `adr-writer`: adopt-Authentik + blueprint-as-code — `[P2 · M · S]`
20. Harbor: add the Reloader annotation (5 rotatable ExternalSecrets, no auto-restart today) + fleet
    Reloader-coverage audit — `[P2 · M · S]`

### Security — pod hardening (the workload-hardening Enforce prerequisites)

21. searxng: `runAsNonRoot` + `readOnlyRootFilesystem` (runs as root today) — `[P1 · M · M]`
22. invoiceninja: de-root the `copy-app` / `prepare-storage` init containers — `[P2 · M · M]`
23. sparkyfitness + zomboid + minecraft: runAsNonRoot / drop-caps / seccomp — `[P2 · M · M]`
24. drawio + excalidraw + freshrss + DT sbom-uploader: add missing securityContexts — `[P2 · M · S]`
25. KEDA + external-secrets: explicit hardening overrides (chart defaults only today) — `[P3 · L · S]`
26. EnvoyProxy pod securityContext + raise ClientTrafficPolicy TLS floor 1.2 → 1.3 — `[P2 · M · S]`

### Security — supply chain ([RFC](../rfc/rfc-image-signing-verification.md))

27. Retroactive ADR: OpenBao Transit signing anchor; fix rfc-security-hardening's stale
    "re-anchor to Authentik" narrative — `[P2 · M · S]`
28. Dependency-Track vs GUAC consolidation decision (two platforms ingest the same weekly SBOMs) — `[P2 · M · M]`
29. Scheduled re-verification job: cosign verify + OCI-digest drift on deployed images — `[P3 · M · M]`
30. ADR-0026 step 2: shared rootless BuildKit service; drop the privileged DinD sidecar — `[P2 · H · L]`

### Security — runtime detection ([RFC](../rfc/rfc-runtime-detection-response.md))

31. RCA the 2026-06-19 "runtime agents destabilized the cluster" attribution (which agent, what
    mechanism — the 06-18 Longhorn incident is a confounder) — `[P2 · M · M]`
32. Reinstate ONE detector (Tetragon leaning) under ADR-0037-style gates, wired into alert
    delivery — or record retiring both and delete the manifests — `[P2 · H · M]`

### Talos / nodes

33. kube-apiserver audit logging → VictoriaLogs — `[P2 · M · M]`
34. KubePrism: enable explicitly + verify (relies on implicit default today) — `[P3 · L · S]`
35. Re-enable the in-apiserver PodSecurity admission (currently `$patch: delete`d — Kyverno is the
    only admission layer) — `[P2 · M · S]`
36. Secure-boot + LUKS2/TPM disk-encryption ADR + rolling apply window — `[P3 · M · L]`
37. Finish the taxonomy migration: `task talos:apply-node MODE=no-reboot` per node to strip the
    retired labels (owner; label-only, etcd-safe) — `[P2 · L · S]`
38. Investigate the soyo RAM regression (80 % worst, was 73 % on 06-21) + right-size the remaining
    BestEffort pods (spegel notably) — first OOM-kill targets under pressure — `[P1 · H · S]`

### Secrets endgame

39. **OpenBao unseal-key escrow out-of-cluster** (SOPS floor slot exists; the live key exists only in
    the in-cluster Secret — nightly snapshots are unusable without it,
    [RFC](../rfc/rfc-backup-dr.md)) — `[P0 · H · S]`
40. zomboid: migrate the last app SOPS secret → ESO, then re-wire or delete the suspended app; add a
    CI guard failing any new `*.sops.yaml` outside the floor — `[P2 · M · S]`
41. Land the freshrss dynamic-creds pilot: PgBouncer SIGHUP-reload sidecar iteration is in the
    working tree — verify mint→rotate→reload end-to-end, then declare ADR-0016 phase 1 — `[P2 · H · M]`
42. Pooling decision: CNPG `Pooler` CR vs per-app sidecar — one mechanism for dynamic creds + future
    replicas ([RFC](../rfc/rfc-postgres-data-layer.md)) — `[P2 · M · M]`

### Reliability — HA, PDBs, priorities

43. cert-manager + external-secrets webhooks → 2 replicas + PDB (single-replica admission SPOFs on
    the cert/secret critical path) — `[P1 · H · S]`
44. k8s-gateway → 2 replicas + PDB (internal split-DNS SPOF; one pod today) — `[P1 · H · S]`
45. Envoy proxies: PDB + topologySpread (2 replicas can co-schedule/co-evict today); envoy-gateway
    controller → 2 replicas — `[P1 · H · S]`
46. Fix the Kyverno PDB/drain deadlock: `minAvailable: 1` PDBs on single-replica
    background/cleanup/reports controllers block node drains — `[P2 · M · S]`
47. cilium-operator → 2 replicas (CNI IPAM/LB-IPAM control-plane SPOF) — `[P2 · M · S]`
48. PriorityClass scheme for data-plane criticals (openbao, envoy, k8s-gateway, victoria-metrics,
    CNPG, forgejo) — undefined preemption order under soyo memory pressure today — `[P2 · M · S]`
49. authentik media → Garage S3 (`AUTHENTIK_STORAGE__MEDIA__S3`), then unpin from fringe — both
    server replicas sit on one node behind an RWO volume — `[P2 · M · M]`
50. CNPG 2-instance exception test: evaluate forgejo + authentik against the criteria
    ([RFC](../rfc/rfc-postgres-data-layer.md)) — `[P2 · H · M]`
51. HelmRelease resilience defaults: add `install.remediation.retries` + `timeout` to the root
    patch (only upgrade remediation is defaulted today) — `[P2 · L · S]`
52. Accept-or-fix review of the single-replica utility tier (metrics-server, reloader, KEDA,
    trust-manager) — record the posture instead of leaving it accidental — `[P3 · L · S]`

### Reliability — backup & DR ([RFC](../rfc/rfc-backup-dr.md))

53. age.key + talsecret off-site escrow — **verify** copies exist outside git (owner) — `[P0 · H · S]`
54. etcd off-node snapshot backup → Garage (no automated etcd backup exists; logical corruption is
    currently unrecoverable) — `[P1 · H · M]`
55. Verify the Longhorn `gitops-backup` RecurringJob actually completes + restore-test one volume
    from Garage (machinery shipped 06-21, still unproven) — `[P1 · H · S]`
56. Longhorn RecurringJob coverage audit: every non-CNPG stateful PVC (forgejo-data, n8n, authentik
    media, game worlds) has a backup job — make the list checkable — `[P2 · H · M]`
57. CNPG coverage campaign: restore-test components for the 5 DBs missing them (dependency-track,
    guac, devex, authentik, grafana); DR components for the 8 missing — `[P2 · M · M]`
58. OpenBao snapshot restore drill into kind — proves snapshot + escrowed key end-to-end (pairs with
    #39) — `[P2 · H · M]`
59. guac: adopt the barman pattern or record the pg_dump-only tier exception — currently neither — `[P2 · M · S]`
60. Data-protection tier map ADR (all durable data, not just DBs) + total-loss runbook + drill
    cadence (staggered CNPG drills resume when CP RAM < 70 % — see #38) — `[P2 · H · M]`

### Reliability — Garage ([RFC](../rfc/rfc-object-storage-garage.md))

61. Garage host metrics scrape (`VMStaticScrape`) + capacity/staleness alerts — today only a
    blackbox probe watches the box every backup lands on — `[P2 · H · S]`
62. Garage host lifecycle doc (hardware, version, config export, upgrade procedure) + Garage-down
    recovery runbook (CNPG WAL backpressure) — `[P2 · M · S]`
63. Second S3 leg: 2nd Garage node or bucket replication — the 3-2-1 build — `[P2 · H · L]`

### Observability — alert delivery ([RFC](../rfc/rfc-alert-delivery.md))

64. **Notification channel** (ntfy + a critical-severity fallback leg) wired into VMAlertmanager
    receivers/routes — ends the `"null"`-receiver era — `[P0 · H · M]`
65. Grafana contact points + notification policy CRs → the same channel (16 SLO rules currently
    deliver nowhere) — `[P1 · H · S]`
66. Watchdog → external deadman heartbeat (healthchecks.io / uptime-kuma off-cluster) — silence
    pages — `[P1 · H · S]`

### Observability — pipeline ([RFC](../rfc/rfc-observability-pipeline.md))

67. kepler: fix the failing DaemonSet rollout or retire it — the one NOT-READY HelmRelease right
    now — `[P1 · M · S]`
68. Decide the commented-out telemetry: tempo, beyla, k6-operator/k6-canaries (k6 dashboards +
    rules point at data never collected), and unwired twitch-exporter — re-enable worker-pinned or
    remove — `[P2 · M · M]`
69. Pyroscope: owner-run etcd defrag → flip `suspend: false` (ADR-0037's sole gate; fsync p99 is
    3.9 ms) — `[P2 · M · S]`
70. Telemetry retention/durability tier ADR (15d metrics / 30d logs / 14d traces; the
    VMSingle-backup decision) — `[P3 · M · S]`
71. Retroactive pipeline ADRs via `adr-writer`: ~~Loki logging~~ (done — [ADR-0041](../adr/adr-0041-victorialogs-logging-backend.md) covers the log backend incl. Loki-era context) + the two-Alloy collector topology — `[P2 · S · S]`
72. Alert-coverage bundle: cloudflared tunnel-down, OpenBao TLS expiry, Garage capacity — `[P2 · M · S]`
73. Per-app Sloth SLOs (forgejo, authentik, ingress) + burn-rate alerts — `[P3 · M · M]`

### Observability — programs

74. DevEx program wiring: the 4 n8n workflows (form → refresh → rollups → incidents), first real
    pulse, demo-data teardown — `[P2 · M · M]`
75. GitOps-health dashboard (commit-vs-reconciled, drift, suspended count) — `[P3 · M · M]`

### Flux / GitOps / capacity

76. **Execute the ADR-0011/0015 cutover pack:** pull→push mirror flip, `sync.url` repoint to the
    in-cluster Forgejo Service, Forgejo webhook on the existing Receiver, break-glass runbook,
    GHCR re-home, GitHub RenovateJob retirement — `[P1 · H · L]`
77. ADR-0014 Codeberg push-mirror (post-cutover; resolve the ToS question first) — `[P3 · M · M]`
78. Platform-tier `healthChecks`/`wait` audit + `driftDetection.ignore` tuning on noisy HRs — `[P3 · L · S]`
79. Compute ResourceQuotas: label namespaces for the existing Kyverno quota generator (zero
    carriers today; count-only quotas everywhere) — `[P3 · M · S]`

### Storage tails (ADR-0008/0027/0029)

80. ADR-0010 stage 2: recreate the chart `longhorn` SC at 2 replicas (every volume on it is
    perpetually Degraded at 3) + migrate the ~18 `longhorn-general` references — `[P2 · M · M]`
81. Restrict the longhorn-manager DaemonSet to storage nodes (stale fringe toleration only today)
    + converge the soyo-2 straggler replica — `[P2 · M · S]`
82. ADR-0009 cold tier: supervised HDD wipe + node-annotation disk topology (the ADR-0007 disk
    gate; unlocks the v2/LINSTOR revisit too) — `[P3 · M · M]`

### CI / shift-left

83. kubeconform/CRD schema validation in CI — today it exists only in the local edit hook;
    `flux-local build` alone catches no schema drift — `[P1 · H · M]`
84. **Forgejo CI parity:** port the e2e gate set to `.forgejo/workflows` (currently a hello-world
    stub) — hard gate for this repo going Forgejo-leading (#76) — `[P1 · H · L]`
85. CI hygiene bundle: `timeout-minutes` on every job (none today), `permissions:` +
    `persist-credentials: false` on claude-review/labeler/label-sync, dedupe the double flux-local
    run, claude-review also on push-to-main — `[P2 · M · S]`
86. Fix the zizmor lefthook glob (misses `.yml` files) + run zizmor and gitleaks in CI, not just
    locally — `[P2 · M · S]`
87. shellcheck for `scripts/` + `.claude/hooks` in CI/lefthook (~1600 LOC unchecked; `.shellcheckrc`
    already exists) — `[P2 · M · S]`
88. SHA-pin the claude-review.yml actions (`checkout@v4`, `claude-code-action@v1` — the only
    tag-pinned workflow left) — `[P2 · M · S]`
89. Docs CI: mkdocs build + markdownlint on top of the link-checker just landing in e2e
    (`check-docs-links.sh`) — render breakage still ships silently — `[P2 · M · M]`
90. Grafana dashboard JSON validation in CI (66 GrafanaDashboard CRs, zero model validation) — `[P3 · M · M]`
91. `bootstrap/` (helmfile template) + `talos/` (talhelper validate) smoke tests in CI — `[P3 · M · S]`
92. Unit tests for the `.claude/hooks` guards (248 LOC gating every edit) + the stdlib Python
    validators — `[P2 · M · M]`

### DX / docs / horizon

93. `add-app` scaffold completeness: NetworkPolicy + alerts + `catalog-info.yaml` + restore-test
    wiring by default — every new app currently inherits those gaps — `[P2 · H · M]`
94. Backstage catalog: entities for the ~27 apps (auto-generate from the Flux tree) + a dependsOn
    graph (66 edges in-tree, nothing surfaces them) — `[P3 · M · L]`
95. `app.kubernetes.io/*` label standard via a Kyverno policy — `[P3 · M · M]`
96. Scheduled cluster-health digest: wire the empty `scheduled-maintenance.yml` stub (digest.sh
    runs only on a laptop systemd timer today) — `[P3 · M · M]`
97. Retroactive foundation ADR pack via `adr-writer`: Talos, Flux topology, Cilium datapath +
    the ingress/DNS/tunnel edge ([RFCs](../rfc/rfc-platform-foundations.md)) — `[P2 · M · M]`
98. ARC end-state: retire-or-restore decision + teardown/sunset checklist
    ([RFC](../rfc/rfc-github-actions-retirement.md); 0/0 "TEMP" since 06-18) — `[P2 · M · S]`
99. 3rd worker node / layered-hardware Phase-2 path choice — unlocks a 3-replica ceiling, real
    node-level HA, and the ADR-0007 engine revisit — `[P2 · H · L]`
100. Dedicated etcd SSD per soyo (L2/L3 isolation; lower urgency post-migration, still the clean
     fix) — `[P3 · M · L]`

---

## Sequencing notes

- **#64→#65/#66 before #32** — alert delivery must exist before runtime detection returns;
  detections nobody hears are cost without control. Same for #61's Garage alerts.
- **#39 pairs with #58** — the escrowed unseal key is only real once a restore drill proves it.
  #53 is the same class of owner action; do both in one sitting.
- **#84 gates #76** — this repo cannot go Forgejo-leading while `.forgejo/workflows/ci.yml` is a
  stub; port the gates first, then cut over, then #77 (Codeberg) and the GitHub RenovateJob
  retirement follow.
- **#21–26 gate #5**, **#4 gates image-hygiene**, and **#6 needs the verify-namespace carve-outs**
  — the enforce waves stay one-policy-per-commit per ADR-0032.
- **#38 is the lever for #60's drill re-enable** (CP RAM < 70 %) and lowers the risk of every
  rollout-heavy item; treat the RAM regression as the first reliability move.
- **#49 before #50** — authentik can't be meaningfully 2-instance while both replicas are pinned
  to one node by the RWO media volume.
- **#80–82 are window work** — storage changes ship isolated, spaced from other rollout-heavy
  commits (the batched-rollout collapse lesson).
- **#99 unlocks the horizon** — a third worker reopens 3-replica Longhorn, real node HA, and the
  ADR-0007 storage-engine gate; decide the layered-hardware path before buying.
