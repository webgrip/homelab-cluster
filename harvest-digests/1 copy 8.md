Thread Digest: Repairing the homelab's SLO/alerting layer, plus supply-chain framing corrections
One-line summary: Diagnosed and fixed a silently-broken Grafana SLO alerting layer (and several follow-on alert/placement bugs) on a Flux GitOps homelab, then corrected a misframing of what the Trivy/Dependency-Track "supply-chain" alerts actually measure.

Approx date / status: 2026-06-21 → 2026-06-26 — done (Workstreams A–I shipped; a few owner-gated items + framing fixes open)

Items
[GOTCHA] Grafana threshold alert rules silently error without a top-level expression: field
Type: GOTCHA
Verification: [VERIFIED] (created a throwaway rule via MCP with the field → health: ok; without it → parse error)
What: A GrafanaAlertRuleGroup SSE chain (Prometheus query node + a type: threshold node) errors on every evaluation with [sse.parseError] failed to parse expression [threshold]: no variable specified to reference for refId threshold unless the threshold node's model includes expression: <input-refId> (the bare refId string, e.g. query — NOT $query, NOT UI-style A). The legacy conditions[].query.params:[query] is not sufficient. This broke all 16 SLO rules for ~3 weeks; kubeconform and flux-local build do NOT catch it because the operator CRD types model as preserve-unknown-fields.
Why it matters: The entire SLO/SLA alerting layer was non-functional and undetected. Two rules with execErrState: Alerting produced false-positive critical pages; the other 14 errored silently.
Snippet:

        - refId: threshold
          model:
            refId: threshold
            type: threshold
            expression: query        # <-- REQUIRED (bare input refId)
            datasource: { uid: "-100", type: __expr__ }
            conditions: [ { type: query, evaluator: {type: gt, params: [0]}, operator: {type: and}, query: {params: [query]}, reducer: {type: last} } ]
Suggested home: existing-skill (grafana-dashboard)
[PROCEDURE] Pre-flight a Grafana alert-rule shape with a throwaway MCP rule before mass-editing
Type: PROCEDURE
Verification: [VERIFIED]
What: Before editing many rules, create one throwaway rule via the Grafana MCP alerting_manage_rules (operation create), get it to confirm health != error, then delete it. This validates exact SSE syntax against the live Grafana version without touching GitOps-managed rules. After committing rule fixes, verify via alerting_manage_rules list with states:["error"] (expect empty) and get a rule whose data exceeds threshold to confirm it transitions to firing.
Why it matters: Render-time validation (kubeconform/flux-local) cannot catch SSE model errors; live rule-health re-query is the only real acceptance test.
Snippet: mcp__grafana__alerting_manage_rules operation=create … data=[{refId:query,model:{expr:"vector(1)",…}},{refId:threshold,model:{type:threshold,expression:"query",conditions:[…]}}]
Suggested home: existing-skill (grafana-dashboard)
[GOTCHA] count(kube_node_status_condition{status="true"}) counts nodes, not pressured nodes
Type: GOTCHA
Verification: [VERIFIED] (live: 0 nodes under pressure, yet count()≈5 → permanent firing; fixed to sum() and reconciled)
What: kube_node_status_condition{condition="MemoryPressure",status="true"} emits one series per node with value 0 or 1. count(...) therefore returns the node count (~5) regardless of actual pressure → permanent false-positive critical alert. Use sum(...) (sums the 0/1 values = nodes actually under pressure). Same anti-pattern applies to any kube_*_status_condition/boolean-gauge metric.
Why it matters: Two critical alerts (slo-node-memory-pressure, slo-node-disk-pressure) fired forever. count over a label-filtered boolean gauge is almost always wrong.
Snippet: sum(kube_node_status_condition{condition="MemoryPressure",status="true"})
Suggested home: existing-skill (grafana-dashboard)
[GOTCHA] count()/sum() over an empty filtered set returns NoData, not 0
Type: GOTCHA
Verification: [VERIFIED] (committed or vector(0) across 11 rules; flux-local passed)
What: Rules like count(up == 0), count(flux_resource_info{ready="False"}), count((cert_expiry - time()) < X) return an empty vector when healthy, so the rule sits in health: nodata (indistinguishable from a broken metric pipeline) instead of showing 0/Normal. Append or vector(0). Do NOT add it to rules whose noDataState: Alerting is intentional (e.g. a "metrics-exporter-stale" detector or a "watch-the-watchers" meta-rule) — there NoData must page.
Why it matters: Makes a healthy SLO render green and distinguishable from a data outage.
Snippet: count(up == 0) or vector(0)
Suggested home: existing-skill (grafana-dashboard)
[GOTCHA] Operator-managed Grafana ServiceMonitor needs the release label AND the right selector
Type: GOTCHA
Verification: [VERIFIED] (a .claude skill guard blocked the edit until the release label was added; metric appeared after reconcile)
What: For kube-prometheus-stack to scrape the grafana-operator-managed Grafana, the ServiceMonitor must (1) carry metadata.labels.release: kube-prometheus-stack (Prometheus's serviceMonitorSelector), and (2) its spec.selector.matchLabels must match the operator's actual Service labels: app.kubernetes.io/managed-by: grafana-operator + grafana.internal/instance: grafana (NOT app.kubernetes.io/name: grafana). Missing either → grafana_alerting_* never scraped → no way to meta-monitor alert health.
Why it matters: Without it, a "watch-the-watchers" rule sits in NoData forever — the blind spot that hid the 3-week outage.
Snippet: metadata.labels.release: kube-prometheus-stack
Suggested home: existing-skill (grafana-dashboard)
[FACT] The cluster runs TWO independent alert engines; no single unified view
Type: FACT
Verification: [VERIFIED]
What: (1) Grafana-managed SLO rules (GrafanaAlertRuleGroup CRDs under kubernetes/apps/observability/grafana/app/alerting/{slo-platform,slo-security,slo-observability}.yaml, organized by Grafana folders Platform/Security/Observability) — read at grafana.${SECRET_DOMAIN}/alerting/list. (2) Prometheus-native alerts (kube-prometheus-stack + Sloth PrometheusServiceLevel + custom PrometheusRules) — read at alertmanager.${SECRET_DOMAIN} or prometheus.${SECRET_DOMAIN}/alerts. Some conditions were alerted by BOTH (DT critical/policy/risk). There is no dashboard unifying both engines.
Why it matters: "What's firing?" requires checking both UIs; double-alerting is a real dedup hazard.
Snippet: ALERTS{alertstate="firing"} (Prometheus) vs alerting_manage_rules list states:["firing"] (Grafana)
Suggested home: doc (observability) / existing-skill (grafana-dashboard)
[DECISION] Resolve DT double-alerting by keeping the Grafana SLO rules, dropping the PrometheusRule dupes
Type: DECISION
Verification: [VERIFIED] (removed the dependency-track.critical group; kept recording rules)
What: DependencyTrack{CriticalVulnerabilities,PolicyViolationsFail,HighRiskScore,MetricsExporterDown} in kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-security-dt.yaml duplicated the Grafana slo-dt-* rules on identical metrics/thresholds. Removed the PrometheusRule alert group (kept its recording rules); Grafana SLO layer is the single source.
Why it matters: Eliminates duplicate pages for the same condition.
Snippet: none
Suggested home: doc (RFC: observability alerting reliability)
[GOTCHA] Trivy/Dependency-Track "supply-chain" numbers are whole-fleet third-party scans, NOT your images/Harbor/SBOMs
Type: GOTCHA
Verification: [VERIFIED] (live: dt_portfolio_projects{state="total"}=159; the trivy-sbom-uploader CronJob header confirms it)
What: A trivy-sbom-uploader CronJob (kubernetes/apps/security/dependency-track/app/sbom-uploader/cronjob.yaml, "scans all running cluster images with Trivy and uploads CycloneDX SBOMs to Dependency-Track", Sundays 02:00) auto-populates DT with 159 projects = every upstream third-party image (postgres, cilium, longhorn, grafana, alpine, etc.). trivy-operator scans all running pod images registry-agnostically — no Harbor and no first-party-shipped SBOM required. So "63 critical CVEs / 2332 policy fails / risk 5961" are about upstream images (fixed by version bumps/Renovate), NOT the user's build artifacts. Only ghcr.io/webgrip/github-runner was genuinely first-party.
Why it matters: It is wrong to frame these as "your supply chain"; remediation is upstream version bumps, and these are low-urgency informational signals, not first-party-build risk.
Snippet: dt_portfolio_projects{state="total"} ; sum by (namespace,resource_name)(trivy_image_vulnerabilities{severity="Critical"}) > 0
Suggested home: doc (supply-chain-cve-triage.md) / memory
[GOTCHA] TrivyExposedSecretsDetected labels itself severity: critical but matches Critical|High|Medium
Type: GOTCHA
Verification: [VERIFIED] (live: the 2 firing instances were severity="High" in guac-db-backup and sparkyfitness-db-1; all Critical series = 0)
What: In kubernetes/apps/security/trivy-operator/app/prometheusrule.yaml, TrivyExposedSecretsDetected expr is sum by (...) (trivy_image_exposedsecrets{severity=~"Critical|High|Medium"}) > 0 but carries labels.severity: critical — so a Medium/High finding in an upstream base image pages as critical. The 2 firing were High-severity in stock postgres/backup images — near-certain base-image false positives (example keys/test certs), not leaked first-party creds.
Why it matters: Over-aggressive severity labeling turns base-image scanner noise into critical pages. Verify the ExposedSecretReport CR before treating as a real leak.
Snippet: none
Suggested home: existing-skill (grafana-dashboard) / doc
[GOTCHA] KEDA warm-pool runner + activeDeadlineSeconds = false KubeJobFailed every ~2h
Type: GOTCHA
Verification: [VERIFIED] (Job status reason: DeadlineExceeded, failed at exactly startTime+7200s)
What: The forgejo-runner ScaledJob keeps a warm pool (minReplicaCount) blocked on forgejo-runner one-job --wait. With jobTargetRef.activeDeadlineSeconds: 7200, an idle waiting runner is killed as DeadlineExceeded (a Failed Job) every 2h; KEDA retained failedJobsHistoryLimit: 5 → 5 permanent KubeJobFailed alerts. Fix: remove activeDeadlineSeconds (the warm runner waits cleanly and completes on a job; Forgejo's per-job timeout is the real runaway cap) and set failedJobsHistoryLimit: 0 (reaps the stale backlog via KEDA + stops future lingering Failed objects; real CI failures are visible in Forgejo's Actions UI).
Why it matters: activeDeadlineSeconds caps wait+execute, so it kills intentionally-blocking warm runners. File: kubernetes/apps/forgejo/forgejo-runner/app/scaledjob.yaml.
Snippet: failedJobsHistoryLimit: 0 + (no activeDeadlineSeconds)
Suggested home: memory / doc (forgejo runner)
[FACT] AppsTierWorkloadSpilledToControlPlane excludes *-runner-* but not provisioner/CronJob pods
Type: FACT
Verification: [VERIFIED] (alert fired on forgejo-ci-provisioner-* + forgejo-actions-secrets-* on soyo-3; fixed by pinning)
What: The alert (in kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-nodes.yaml) excludes .*-(runner|metrics-exporter|sbom-uploader|policy-bootstrap)-.* but NOT provisioner/CronJob bootstrap pods. Stateless forgejo bootstrap Jobs had no nodeSelector and scheduled onto a soyo control-plane. Fix = add nodeSelector: { node.webgrip.io/pool: worker } to their pod specs (ADR-0028; the forgejo storage exception was dropped, so forgejo pins to workers like every other app).
Why it matters: Bootstrap Jobs/CronJobs need explicit worker pinning; the components/placement/worker-pool component only patches Deployments/StatefulSets/CNPG, not bare Jobs.
Snippet: nodeSelector: { node.webgrip.io/pool: worker }
Suggested home: existing-skill (workload-placement)
[DECISION] Silence alerts/SLOs in lock-step when their watched workload is deliberately disabled
Type: DECISION
Verification: [VERIFIED] (K6CanaryMetricsMissing cleared after commenting out the rule + SLO)
What: k6-operator/k6-canaries were suspended (commented out of kubernetes/apps/observability/kustomization.yaml, "to free fringe resources") but K6CanaryMetricsMissing + the slo-synthetic-k6-canary Sloth SLO were left active and fired forever. Resolution: comment those two out of their kustomizations with a note pointing back to the k6 suspension, so re-enabling k6 re-enables them together. Kept slo-synthetic-availability (blackbox probe_success, independent of k6).
Why it matters: Disabling a monitored component without disabling its alerts produces permanent false alerts.
Snippet: none
Suggested home: doc (observability)
[FACT] Sloth burn-rate / synthetic-availability alerts linger after the underlying probe recovers
Type: FACT
Verification: [VERIFIED] (probe_success{endpoint=~"grafana|prometheus|alertmanager"}=1 while Synthetic*Availability still firing)
What: Multi-window burn-rate SLO alerts (Sloth PrometheusServiceLevel, e.g. slo-synthetic-availability.yaml fed by blackbox probe_success) keep firing for a while after the endpoint recovers, because the error budget burned during the outage is still inside the long window. Check probe_success current value before treating a Synthetic*Availability alert as a live outage.
Why it matters: Avoids chasing a "down" alert when the thing is already back up.
Snippet: probe_success{endpoint="prometheus"}
Suggested home: doc (observability)
[GOTCHA] The longhorn StorageClass still provisions 3 replicas on a 2-storage-node cluster
Type: GOTCHA
Verification: [VERIFIED] (kubectl get sc longhorn -o jsonpath='{.parameters.numberOfReplicas}' = 3; DT api-server volume was degraded)
What: The chart-created default longhorn SC carries numberOfReplicas: 3 (from persistence.defaultClassReplicaCount, an immutable SC param), but only 2 Longhorn-schedulable nodes exist (fringe-workstation + worker-1) with hard replica anti-affinity → a 3-replica volume can never be healthy. Existing volumes were reduced to 2 at runtime; any reprovision returns to 3. The chart's defaultSettings.defaultReplicaCount: "2" does NOT override an explicit SC param. The maintainers deliberately left the SC at 3 ("to avoid breaking the HR upgrade") — durable convergence to 2 is deferred (ADR-0029 Stage 2 / ADR-0027), documented in kubernetes/apps/longhorn-system/longhorn/app/helmrelease.yaml.
Why it matters: Explains recurring "volume degraded" (e.g. dependency-track-api-server); the runtime replica patch is not durable.
Snippet: mise exec -- kubectl get sc longhorn -o jsonpath='{.parameters.numberOfReplicas}'
Suggested home: existing-skill (longhorn)
[GOTCHA] StatefulSet volumeClaimTemplates.storageClassName is immutable — changing it breaks the HelmRelease
Type: GOTCHA
Verification: [ASSERTED] (reasoned from K8s immutability rules; not executed live this thread)
What: Repointing a chart-rendered StatefulSet PVC to a different StorageClass (e.g. longhorn→longhorn-general) is rejected by the API (immutable VCT field), so the helm upgrade fails and the HelmRelease goes not-Ready until the STS + PVC are deleted and recreated. For DT api-server this is acceptable only because /data is a rebuildable NVD/OSV cache (the encryption key lives in the dependency-track-secret Secret, not /data) — per the chart's own comment. CNPG cluster storageClass changes are similarly disruptive (PVC recreate / data risk).
Why it matters: "Just change the SC" silently breaks reconciliation; requires a coordinated owner-gated recreate.
Snippet: kubectl -n security delete sts dependency-track-api-server --cascade=foreground && kubectl -n security delete pvc data-dependency-track-api-server-0
Suggested home: existing-skill (longhorn) / existing-skill (cnpg-database)
[GOTCHA] Imperative kubectl/Longhorn mutations are hard-blocked by a guard hook — even with explicit user approval
Type: GOTCHA
Verification: [VERIFIED] (PreToolUse:Bash hook … BLOCKED (GitOps policy): direct kubectl mutation. Make the change in Git and let Flux reconcile, or run it yourself outside Claude.)
What: .claude/hooks/guard-destructive.sh blocks any kubectl patch/delete/edit/apply (and Longhorn volume/replica/node mutations) at the tool layer, regardless of user instruction in-chat. The agent must make the change in Git (GitOps) or hand the exact command to the human to run outside Claude. Read-only kubectl get/exec wget and kubectl get --raw /readyz are allowed.
Why it matters: The agent cannot execute even a safe, user-approved runtime patch (e.g. Longhorn numberOfReplicas 3→2); plan around handing it off.
Snippet: mise exec -- kubectl -n longhorn-system patch volumes.longhorn.io <pv> --type=merge -p '{"spec":{"numberOfReplicas":2}}' (owner runs)
Suggested home: CLAUDE.md / memory
[PROCEDURE] When the in-cluster MCP servers time out, fall back to the kubectl path
Type: PROCEDURE
Verification: [VERIFIED] (grafana + kubernetes MCP both returned upstream connect error … connection timeout; kubectl worked)
What: The grafana and kubernetes MCP servers are in-cluster, LAN-only, and route via the internal gateway; a brief LAN/ingress blip makes both time out simultaneously even while the cluster is healthy. Confirm cluster reachability with mise exec -- kubectl get --raw '/readyz', then read Prometheus firing alerts directly: kubectl exec -n observability prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- wget -qO- 'http://localhost:9090/api/v1/alerts'. (Note: Grafana-managed SLO rule states are NOT in Prometheus and are unavailable this way.)
Why it matters: MCP timeouts ≠ cluster down; you can still get Prometheus-native alert state via kubectl.
Snippet: mise exec -- kubectl exec -n observability prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- wget -qO- 'http://localhost:9090/api/v1/alerts'
Suggested home: existing-skill (cluster-health subagent) / doc
[FACT] zizmor GitHub-Actions linter is a lefthook pre-commit step but is not pre-installed
Type: FACT
Verification: [VERIFIED] (commit touching .github/workflows/ failed sh: 1: zizmor: not found; pip install zizmor into the repo .venv fixed it; later commits passed)
What: .lefthook.toml runs zizmor --offline {staged_files} on .github/workflows/*.yaml and .github/actions/**/action.yaml. It is not provisioned by default. Install with python3 -m pip install zizmor (lands in the repo .venv/bin, then resolves on PATH for the hook). Other pre-commit hooks: format-yaml (yamlfmt, stage_fixed=true), format-just, format-mise.
Why it matters: Editing any workflow file blocks commits until zizmor is installed.
Snippet: python3 -m pip install zizmor ; .venv/bin/zizmor --offline .github/workflows/<file>.yaml
Suggested home: CLAUDE.md / doc
[GOTCHA] The Kyverno CLI test harness used a hardcoded policy allowlist that omitted 6 policies
Type: GOTCHA
Verification: [VERIFIED] (replaced with kind-based discovery; 39 CLI tests still pass)
What: scripts/lib/kyverno-tests.sh prepare_kyverno_test_workspace() hardcoded the list of policies copied into the test workspace, silently omitting workload-hardening-audit, workload-advanced-hardening-audit, secrets-observability-ops-audit, image-hygiene-audit, image-verify-harbor-audit, storage-cnpg-governance — so those could be promoted to Enforce with zero CLI coverage and CI stayed green. Replaced the array with discovery by kind over policies/app/*.yaml.
Why it matters: A test harness allowlist can hide untested enforced policies; discover by kind instead.
Snippet: grep -rlZ -E '^kind: (ClusterPolicy|Policy|PolicyException|ClusterCleanupPolicy)$' "${policy_dir}"/*.yaml
Suggested home: existing-skill (kyverno-policy)
[FACT] Kyverno enforce mechanics in this repo: per-rule failureAction, no per-rule "action", split/overrides
Type: FACT
Verification: [VERIFIED] (read across all policies)
What: Policies set spec-level validationFailureAction: Audit|Enforce, and individual rules can override with failureAction: Audit inside an otherwise-Enforce policy (effective action = rule's failureAction if set, else spec-level). There is no per-rule "action" knob beyond failureAction. Promotion levers: whole-policy flip, validationFailureActionOverrides (per-namespace), or splitting a policy (clean rules → a new -enforce.yaml, dirty rules stay in -audit). Autogen duality: every Pod policy emits both <rule> (Pod/background) and autogen-<rule> (controller/admission) findings — a PolicyException must waive both or admission still blocks.
Why it matters: Core to safely promoting audit→enforce one at a time without an admission outage.
Snippet: validationFailureActionOverrides: [{action: Enforce, namespaces: [...]}]
Suggested home: existing-skill (kyverno-policy)
[GOTCHA] A "concurrent agent" shares the same local repo/working tree — commits interleave; fetch+verify before push
Type: GOTCHA
Verification: [VERIFIED] (HEAD advanced mid-session via commits not made by this agent — Talos v1.13.4 upgrade, dashboard fixes; pre-existing .mise.toml/talos/talenv.yaml working-tree edits were not this agent's)
What: Another actor commits to main in the same working directory during a session. Their commits appear directly in local history (one linear history, clean fast-forward pushes). Defenses that worked: stage files explicitly by path (never git add -A), git fetch origin main + check git rev-list --left-right --count origin/main...HEAD before each push, and leave pre-existing uncommitted files (e.g. .mise.toml, talos/talenv.yaml) untouched.
Why it matters: Avoids clobbering others' work or committing unrelated changes.
Snippet: git rev-list --left-right --count origin/main...HEAD
Suggested home: memory
[REFERENCE] ADR/RFC conventions + nav registration
Type: REFERENCE
Verification: [VERIFIED] (added ADR-0030..0034 + 2 RFCs this way)
What: ADRs: docs/techdocs/docs/adr/adr-NNNN-<kebab>.md, zero-padded monotonic number (never reused; a reversal gets a new superseding ADR). RFCs: docs/techdocs/docs/rfc/rfc-<topic>.md (no number; the umbrella). No front-matter; open with # H1 then > Status: **Accepted** · Date: YYYY-MM-DD · Part of [RFC: …](../rfc/...). Sections: Context / Decision / Consequences / Alternatives considered. Cross-folder links use ../rfc/ and ../adr/. Must register new docs in three places: the ADR/RFC tables in docs/techdocs/docs/adr/index.md, and the nav: list in docs/techdocs/mkdocs.yml. This thread added ADR-0030 (threshold rule shape + lint), 0031 (meta-monitoring), 0032 (re-enable pyroscope on worker pool), 0033 (Kyverno enforce promotion), 0034 (approved-registries stays Audit).
Why it matters: Matches house style and keeps the techdocs nav valid.
Snippet: > Status: **Accepted** · Date: YYYY-MM-DD · Part of [RFC: …](../rfc/rfc-….md)
Suggested home: doc / CLAUDE.md
[REFERENCE] New validators added this thread + their CI wiring
Type: REFERENCE
Verification: [VERIFIED] (both run; wired into .github/workflows/e2e.yaml)
What: scripts/validate_grafana_alert_expr.py — stdlib-only (no PyYAML; bare CI python3 lacks it) text linter that fails if any GrafanaAlertRuleGroup SSE node of type ∈ {threshold,math,reduce} lacks a sibling expression:. scripts/check-kyverno-test-coverage.sh — fails CI if an enforcing ClusterPolicy isn't exercised by a CLI test with a result: fail case (pass-case advisory; pre-existing untested storage-cnpg-governance baselined in a KNOWN_UNTESTED array). Both wired as steps in e2e.yaml; the grafana one also runs inside scripts/run-flux-local-test.sh. Mirror the existing scripts/validate_alert_annotations.py (dependency-free) pattern.
Why it matters: Shift-left guards for the two bug classes that shipped silently.
Snippet: python3 scripts/validate_grafana_alert_expr.py "$GITHUB_WORKSPACE"
Suggested home: doc / existing-skill (flux-validate, kyverno-policy)
[REFERENCE] Live alert/SLO read surfaces + key dashboard UIDs
Type: REFERENCE
Verification: [VERIFIED] (dashboards listed via MCP search)
What: Aggregate views: grafana.${SECRET_DOMAIN}/alerting/list (Grafana SLO rules), alertmanager.${SECRET_DOMAIN} (Prometheus alerts + silences), prometheus.${SECRET_DOMAIN}/alerts. Drill-down dashboards (grafana.${SECRET_DOMAIN}/d/<uid>): security-overview (SOC Command Center), security-trivy-sbom, dt-supply-chain-001, kyverno-violations, kyverno-policy-insights, platform-etcd, obs-stack-overview, talos-node-health. Source-of-truth apps: dependency-track.${SECRET_DOMAIN}, harbor.${SECRET_DOMAIN}, Policy Reporter.
Why it matters: Saves rediscovering where to read each concern.
Snippet: none
Suggested home: doc (observability)
[FACT] etcd fragmentation is double-alerted; defrag is the owner-gated remediation
Type: FACT
Verification: [VERIFIED] (both EtcdDbHighFragmentationRatio (custom) and etcdDatabaseHighFragmentationRatio (stock) fire ×3 members)
What: Two alerts fire on the same etcd boltdb fragmentation condition across all 3 control-plane members (a custom rule + the stock kube-prometheus-stack one — a dedup candidate). Remediation is owner-run talosctl etcd defrag (one member at a time, leader last; runbook docs/techdocs/docs/runbooks/etcd-health.md); it is also the gating prerequisite for re-enabling pyroscope.
Why it matters: Recurring warning; the fix is a deliberate human op, not a manifest change.
Snippet: talosctl etcd defrag (leader last)
Suggested home: existing-skill (talos)
[REFERENCE] Forgejo Actions reserves FORGEJO_/GITHUB_/GITEA_ secret/var prefixes
Type: REFERENCE
Verification: [ASSERTED] (documented in the forgejo-actions-secrets.cronjob.yaml header comment; not re-tested this thread)
What: Org-level Forgejo Actions secrets/variables must NOT use the FORGEJO_/GITHUB_/GITEA_ prefixes (reserved for built-ins; the API rejects them — secret PUT 400, var POST/PUT 400/404). Use a WEBGRIP_-prefix instead. Secret values are write-only over the API (can't read back), so the provisioner PUTs every tick (create-or-update). There is no ESO push-provider for Forgejo Actions secrets — use the "in-cluster CronJob hits the Forgejo admin API" pattern.
Why it matters: Naming a Forgejo Actions secret with a reserved prefix silently 400s.
Snippet: secret names WEBGRIP_CI_TOKEN, vars WEBGRIP_FORGEJO_URL / WEBGRIP_CI_BOT_NAME
Suggested home: existing-skill (forgejo-leading) / doc (forgejo)
Open questions / unfinished
DT volume 2-replica durability [OPEN]: all DT volumes are currently 2+healthy, but provisioning default is still 3. Owner to choose: scoped api-server className→longhorn-general + one-time PVC recreate, vs cluster-wide longhorn SC convergence to 2 (ADR-0029 Stage 2). Neither executed.
Kyverno audit→enforce campaign (Workstreams D waves 1–14) [OPEN]: framework shipped (RFC, ADR-0033/0034, CI gate); the actual enforce flips are deliberately NOT executed — each gated on a clean per-rule PolicyReport over a reconcile cycle + an admission-watch.
Owner-gated ops not done [OPEN]: seed Codeberg PAT into OpenBao (bao kv put secret/codeberg/pages token=<REDACTED>); talosctl etcd defrag; re-enable pyroscope (suspend: false) after defrag.
Proposed follow-ups not yet done [OPEN]: re-frame supply-chain-cve-triage.md as third-party image hygiene; downgrade upstream-CVE alerts from critical pages to informational; fix TrivyExposedSecretsDetected severity labeling; confirm the 2 ExposedSecretReports are false positives.
harbor-jobservice [OPEN]: flapping CrashLoopBackOff (~8 restarts/12h, currently Running); pre-existing, root cause not investigated.
Explicit preferences/feedback I gave
Don't unilaterally make changes that break a HelmRelease (e.g. an immutable-VCT StorageClass swap) without a coordinated owner recreate; present the trade-off instead.
Challenge / verify framing before reporting — the user correctly pushed back that the "supply-chain" alerts don't reflect their images/Harbor/SBOMs; I had conflated whole-fleet Trivy auto-scanning with first-party supply chain. Verify what a metric actually measures before characterizing it.
GitOps-first, one change at a time: separate scoped commits per fix ("fix these one by one"), validate with ./scripts/run-flux-local-test.sh, commit with git -c commit.gpgsign=false commit, push to main directly.
Respect deliberate deferrals: when maintainers documented a conscious deferral (e.g. the longhorn SC left at 3), treat it as a deliberate decision, not a bug to silently override.
Don't manually renumber the managed 100-item roadmap (docs/techdocs/docs/general/roadmap.md); it's maintained by the roadmap-topup skill.
Plan-mode discipline: explore (Explore agents) → design (Plan agents) → ask clarifying questions via AskUserQuestion → write the plan file → ExitPlanMode.
