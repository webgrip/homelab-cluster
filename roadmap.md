# Homelab Cluster Improvement Roadmap

> Derived from a four-lens audit (shift-left CI, hardening, reliability, repo hygiene) on 2026-06-12.
> Item numbers (`#NN`) are stable references back to the original 100-step plan, so re-ordering here
> doesn't break cross-references. Each item carries **Impact** (High/Med/Low) and **Effort** (S/M/L).

## How to read this

The repo is already mature — strong Kyverno coverage, ESO+OpenBao, ADR discipline, component reuse.
The gaps are structural, not foundational:

1. **Shift-left is inverted.** The best validation (flux-local diff, Claude review, kubeconform, zizmor,
   the alert-annotation validator) runs only on PRs or only locally — but work lands trunk-based on `main`,
   so it almost never runs.
2. **Hardening is parked in Audit mode.** Image verification, RBAC, workload hardening all observe-only.
3. **Reliability rests on untested assumptions.** Restore tests suspended, Garage is a 10-database SPOF,
   InvoiceNinja's MariaDB has no backup, drift detection off.
4. **Two apps (`zomboid`, `cnpg-dr`) aren't wired into the root kustomization, and docs still describe Infisical.**

---

## Priority tiers

| Tier | Meaning | Act within |
|------|---------|-----------|
| **P0 — Now** | Live risk or cheap correctness fix; failure is silent or already happened | This week |
| **P1 — Near** | Closes a known gap that bit you before, or unblocks a tier of follow-on work | 2–6 weeks |
| **P2 — Build** | Structural improvement; meaningful effort, deferred risk | 1–3 months |
| **P3 — Horizon** | High-effort or low-current-risk; decide accept-vs-implement | Quarter+ |

---

## The five things first

If nothing else, do these — they convert live risk into managed risk:

1. **#9–12** — Make CI run on every push to `main` (flux-local, kubeconform, yamllint, alert validator).
2. **#39** — Un-suspend CNPG restore tests. Untested backups are the single biggest silent risk.
3. **#23** — Put Prometheus / Alertmanager behind Authentik. They're reachable unauthenticated today.
4. **#41** — Give InvoiceNinja's MariaDB a backup path. Single pod, zero backup.
5. **#1–3** — Fix the wiring/drift: commit the coredns change, rewire `zomboid` and `cnpg-dr`.

---

# P0 — Now (this week)

Cheap, reversible, and either fixes a live exposure or stops silent drift.

> **Execution status (2026-06-12):** P0 shipped. Done: #1, #2, #3, #5, #9, #10
> (incl. fixing ~30 pre-existing alert-annotation violations + a Harbor metric-name
> typo), #12, #39 (re-enabled staggered overnight 01:00–06:00 UTC), #41, #61.
> #62 was already covered by the `cnpg-monitoring` component (no work needed).
> **Deferred with reason:** #11 kubeconform — not viable as a blanket gate (26
> false positives from `${SECRET_DOMAIN}` postBuild substitution; `flux-local`
> already renders+validates post-substitution). #23 — design + ready manifests
> captured in `runbooks/observability-auth.md`; needs a live Authentik credential
> and OIDC-flow test (lockout risk), so not auto-wired. #59 etcd defrag — imperative
> `talosctl` op, not representable in GitOps; must be run by the operator.

## Correctness & hygiene
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 1 | Commit or revert the uncommitted `coredns/helmrelease.yaml` change (uncommitted manifest = guaranteed drift) | High | S |
| 2 | Investigate why `./zomboid` is missing from `kubernetes/apps/kustomization.yaml` while the app runs live; rewire or remove | High | S |
| 3 | Same for `./cnpg-dr` — DR manifests exist but nothing references them; wire in or mark drill-only | Med | S |
| 5 | Delete stray `.decrypted~*.sops.yaml` artifacts; add `.decrypted~*` to `.gitignore` | Med | S |

## Shift-left (make CI match the trunk-based reality)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 9 | Add `on: push: branches[main], paths: kubernetes/**` to `flux-local.yaml` — primary validation never fires today | High | S |
| 10 | Wire `scripts/validate_alert_annotations.py` into `e2e.yaml` — validator exists, never runs | High | S |
| 11 | Add `kubeconform -strict` (datreeio CRD catalog) as a CI step | High | S |
| 12 | Add `yamllint` / `yamlfmt --lint` as a CI step | Med | S |

## Hardening (live exposure)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 23 | Put Prometheus + Alertmanager HTTPRoutes behind Authentik — highest-impact finding | High | M |

## Reliability (untested = unprotected)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 39 | Un-suspend CNPG restore tests; stagger them at night instead of off | High | S |
| 41 | Give InvoiceNinja MariaDB a backup path (mysqldump → Garage minimum) | High | M |
| 59 | Run pending `talosctl etcd defrag` on all three soyo nodes (436MB→163MB) | Med | S |
| 61 | Add `ExternalSecretSyncFailed` / store-unhealthy alerts — masked the 2026-06-09 incident | High | S |
| 62 | Add CNPG WAL-archive-failure + last-backup-age alerts (per DB) | High | S |

---

# P1 — Near (2–6 weeks)

Closes known gaps and unblocks the enforce/automation tiers that follow.

## Shift-left (finish the CI parity)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 13 | Add `zizmor` (Actions security lint) to CI — lefthook-local only today | Med | S |
| 14 | Add path-gated `push: main` trigger to `renovate-dry-run.yaml` | Low | S |
| 15 | Make lefthook install non-optional; CI job fails if local hooks and CI diverge | Med | M |
| 16 | CI gate: fail when a Kyverno policy exists without a test directory (15/27 untested) | Med | M |
| 17 | Expand `run-kyverno-chainsaw.sh` from 3 → all Enforce-mode policies | High | M |
| 20 | Add `just precommit` (yamlfmt + yamllint + kubeconform + flux-local on changed ks) — seconds, not post-push surprise | Med | M |
| 21 | Alert on `e2e.yaml` failure (no PR gate exists; you must watch the signal) | Med | S |

## Hygiene
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 4 | Delete empty `apps/zomboid-exporter/` directory | Low | S |
| 6 | Run gitleaks/trufflehog across **full git history** to confirm key files never committed | High | S |
| 7 | Remove root `Taskfile.yaml` duplication; justfile as single entry, delegate to `.taskfiles/` | Low | S |
| 8 | Finish zomboid SOPS→ESO migration (last blocked secret) | Med | M |

## Hardening (start the audit→enforce ratchet)
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 24 | Auth matrix sweep: confirm Longhorn, Policy Reporter, OpenBao UI, Backstage each behind Authentik | High | M |
| 25 | Finish Authentik trust re-anchor that gates image-verify enforcement | High | M |
| 30 | Add explicit securityContext + resources to Harbor HelmRelease (rides chart defaults today) | Med | S |
| 33 | NetworkPolicies for the crown jewels regardless of cluster-wide rollout: OpenBao, CNPG clusters | High | M |

## Reliability — backups you can trust
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 40 | Add restore-test components to authentik, grafana, guac, dependency-track | High | M |
| 46 | Verify OpenBao Raft snapshots restore (one restore into kind); alert on snapshot staleness | High | M |
| 63 | Add restore-test-failure + not-run-in-N-days alerts (protects #39 from regressing) | Med | S |

## Reliability — HA basics
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 51 | Scale Authentik server to 2 replicas, hard anti-affinity — SSO is a login SPOF | High | S |
| 52 | Scale cloudflared to 2 replicas — single pod = external access severed | High | S |
| 53 | Add PriorityClasses; assign to Flux, Cilium, CoreDNS, cert-manager, ESO, Longhorn | High | M |
| 54 | Add PodDisruptionBudgets for CoreDNS, envoy gateways, Authentik, CNPG | Med | M |
| 55 | Enable Flux HelmRelease drift detection via global Kustomization patch | High | S |
| 58 | Longhorn `defaultReplicaCount` 3 → 2 to match every actual StorageClass | Med | S |

## Observability
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 64 | Cert-expiry alerts beyond cert-manager (OpenBao TLS, hand-rolled) | Med | S |
| 65 | cloudflared tunnel-connectivity alert | Med | S |
| 66 | Flux `KustomizationSuspended > N days` alert — suspended things rot invisibly | Med | S |
| 67 | Re-enable or remove Beyla (suspended with no documented reason, unlike pyroscope) | Low | S |

## Secrets
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 73 | Rewrite `external-secrets-plan.md` + runbook to OpenBao — 40+ Infisical refs describe a dead backend | High | M |
| 75 | CI guard: fail when a new `*.sops.yaml` appears outside the allowed floor list | Med | S |

---

# P2 — Build (1–3 months)

Structural improvements; real effort, deferred risk.

## Shift-left depth
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 18 | CLI tests for untested audit policies (image-hygiene, workload-hardening, storage-cnpg, …) | Med | M |
| 19 | Grafana dashboard JSON validation (jq schema + dashboard-linter) in CI | Low | M |
| 22 | Decide Forgejo CI story: mirror e2e there or delete the stub | Low | S |

## Hardening — promote audit → enforce
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 26 | Promote `image-verify-audit` → Enforce for `ghcr.io/webgrip/*` | High | M |
| 27 | Promote `require-image-digest` → Enforce for platform namespaces (ratchet from ~59%) | Med | M |
| 28 | Promote `rbac-least-privilege-audit` → Enforce after a clean PolicyReport week | High | M |
| 29 | Promote `workload-hardening-audit` → Enforce namespace-by-namespace (start stateless) | High | L |
| 31 | Re-enable Hubble (prerequisite for flow-informed network policy) | Med | M |
| 32 | Default-deny `CiliumClusterwideNetworkPolicy` + per-ns allows from observed flows | High | L |
| 34 | Enable Kubernetes API audit logging in Talos controller patch; ship to Loki | Med | M |
| 35 | Re-add Pod Security Admission (`baseline`) as defense-in-depth behind Kyverno | Low | S |

## Hardening — dynamic credentials
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 36 | Unblock dynamic DB creds (ADR-0010 option a); ship Phase 1 for freshrss | High | L |
| 37 | Roll dynamic creds to remaining CNPG apps; retire static DB ExternalSecrets | High | L |
| 38 | Finish ADR-0008 rootless CI builds (BuildKit, kill DinD) | Med | M |

## Reliability — backups & DR
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 42 | Decide searxng/valkey persistence (back up or declare disposable in ADR) | Low | S |
| 43 | Scheduled Longhorn backups to external target for non-DB PVCs (minecraft, zomboid, authentik media, forgejo) | High | M |
| 44 | Full DR drill of hibernated `cnpg-disaster-recovery`; write runbook from experience | High | M |
| 45 | Address Garage SPOF: document RPO, add WAL-failure alert tier; evaluate 2nd Garage / replicated MinIO | High | L |
| 48 | Periodic (quarterly) bootstrap-from-scratch rebuild test in VM/kind | Med | M |
| 49 | CI check: bootstrap helmfile chart versions match HelmReleases (kill bootstrap drift) | Med | M |
| 50 | Write "total cluster loss → restored" runbook; verify off-site age.key/talsecret escrow | High | M |

## Reliability — HA & failure domains
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 56 | Audit `dependsOn` graph: ESO-before-consumers, CNPG-operator-before-clusters explicit | Med | M |
| 57 | Add Flux `healthChecks` + `wait: true` to platform-tier Kustomizations | Med | M |

## Observability
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 68 | Bring Pyroscope back on fringe only (hard anti-affinity) once #59/#60 land | Low | M |
| 69 | Define Sloth SLOs for Forgejo, Authentik, ingress; alert on burn rate | Med | M |
| 70 | "GitOps health" dashboard: e2e status, commit-vs-reconciled, drift, suspended count | Med | M |
| 71 | Mimir/Kafka memory alert before OOM (RAM is scarcest resource) | Med | S |
| 72 | Verify Claude Code telemetry metric names; enable pending settings.json wiring | Low | S |

## Secrets endgame
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 74 | Mark SOPS migration complete; write ADR-0011 capturing final architecture | Med | S |
| 76 | Secret-rotation cadence doc for floor secrets (age key, talsecret, deploy key) | Med | S |
| 77 | Rotate webgrip org token; set up cron timer (open plugin item) | Med | S |
| 78 | Tune ESO `refreshInterval` deliberately per secret (not flat 1h × 37) | Low | S |

## 10x leverage — automate the toil
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 79 | Expand Renovate automerge to minor for low-risk leaf apps (after Phase 2 gates exist) | Med | M |
| 80 | Renovate `postUpgradeTasks` running `flux-local test` (chart bumps self-validate) | High | M |
| 81 | Schedule `triage-renovate` weekly to label/comment PR risk | Med | S |
| 82 | Generate Backstage catalog from Flux tree (script: every ks.yaml → Component) — 95% missing today | Med | M |
| 83 | Build TechDocs in CI (mkdocs build) so broken links fail fast | Low | S |
| 85 | Make `add-app` scaffold include alerts + restore-test + Backstage entry + auth annotation by default | High | M |
| 86 | Nightly scheduled cluster-health digest with delta summary | Med | S |
| 87 | Standardize `app.kubernetes.io/*` labels via Kyverno mutate policy | Low | M |
| 88 | `kustomize build` smoke test for `bootstrap/` + `talos/` paths in CI | Low | S |

---

# P3 — Horizon (quarter+)

High-effort or low-current-risk; decide accept-vs-implement, capture in an ADR either way.

## Node & platform
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 60 | Second SSD per soyo node for dedicated etcd storage — root-cause fix for the etcd/Longhorn contention class | High | L |
| 89 | Evaluate Talos secure-boot + TPM disk encryption; decide accept-or-implement in ADR | Med | L |
| 90 | Pin Talos system extensions; add etcd-health gate before drain in `apply-node-safe` | Med | M |
| 91 | Add a worker or document accepted risk: fringe-workstation is a node-level SPOF for all `nodegroup: fringe` | High | L |
| 92 | Document etcd encryption-at-rest key rotation (Talos secretbox) in runbooks | Low | S |
| 93 | Add KubePrism (local API LB) for kubelet→apiserver resilience during VIP failover | Med | S |
| 94 | Per-node RAM budget doc + alert on allocatable-vs-requested > 85% | Med | M |

## Resilience deepening
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 47 | Plan OpenBao 3-node Raft (or document accepted single-node risk + unseal drill) | Med | L |

## Docs, knowledge, closing the loop
| # | Item | Impact | Effort |
|---|------|--------|--------|
| 84 | Auto-generate dependency/topology diagram from `dependsOn` + `substituteFrom` | Low | M |
| 95 | Incident → action-item pipeline: post-mortems get checkbox follow-ups; CI lists unclosed ones | Med | M |
| 96 | Update `security-platform.md` + hardening RFC: flip shipped items "future" → "done" | Med | S |
| 97 | ADR/RFC index page auto-listing status (proposed/accepted/superseded) | Low | S |
| 98 | Document the split-DNS + coredns custom-zone change in the dns runbook | Low | S |
| 99 | Quarterly: re-run this audit's four lenses as a scheduled review; diff against this roadmap | Med | M |
| 100 | Define "done" for this era; write the retrospective; pick the next horizon | Low | S |

---

## Workstream view (for picking a focused sprint)

If you'd rather attack one theme end-to-end than work by tier:

- **Shift-left CI** — #9–22, #75, #80, #83, #88 → *Outcome: every push to main is validated.*
- **Audit→Enforce hardening** — #23–35 → *Outcome: policies block, not just observe.*
- **Dynamic secrets** — #36–38, #73–78 → *Outcome: short-lived DB creds, SOPS chapter closed.*
- **Backup/DR trust** — #39–50, #63 → *Outcome: every stateful app has a tested restore path.*
- **HA & failure domains** — #51–60, #91, #93 → *Outcome: no single pod/node/box takes a tier down.*
- **Observability gaps** — #61–72, #94 → *Outcome: you're alerted on what actually broke you before.*
- **Automation / 10x** — #79–88, #99 → *Outcome: new apps born compliant; toil generated, not hand-maintained.*

---

## Sequencing notes (dependencies)

- **#31 (Hubble) gates #32 (network policy).** Don't author default-deny blind.
- **#25 (trust re-anchor) gates #26 (image-verify enforce).**
- **#59/#60 (etcd defrag / dedicated SSD) gate #68 (Pyroscope return).**
- **Phase-2 CI gates (#16, #17, #80) should land before #79 (automerge expansion)** — don't widen automerge until the pipeline can catch a bad bump.
- **#36 unblocks #37.** Ship dynamic creds for one app before rolling the fleet.
- **#39 needs #63** to avoid silently re-suspending later.
