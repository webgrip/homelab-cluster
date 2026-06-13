# Homelab Cluster Improvement Roadmap

> Living document. Re-inventoried **2026-06-13** against live cluster state and git history.
> `#NN` refs point back to the original 100-step audit plan so history stays traceable.
> Impact = High/Med/Low, Effort = S/M/L.

## Where we stand (2026-06-13)

Live snapshot taken for this rewrite:

- **Flux:** all Kustomizations/HelmReleases Ready. Suspended on purpose: `observability/pyroscope`
  (etcd I/O contention) and `drawio` (not needed right now).
- **etcd:** healthy — DB ~198 MB (was 436 MB), fragmentation ratio **1.33** (< 1.5 alert
  threshold). The defrag/compaction + load-shedding work landed; **#59 is resolved.**
- **Memory:** control planes soyo-1/2/3 at ~78–80% used, fringe-workstation ~64%. RAM on the
  control planes is still the binding constraint — which is why restore drills stay **off**.
- **Restore drills (#39):** intentionally suspended (owner decision — too much storage/CP load).
  Schedules retained for a one-line re-enable once CP headroom improves.

Since the original audit, two things happened in parallel: the **P0 batch shipped**, and the owner
ran a sustained **reliability / resource-right-sizing sprint** plus opened a new **Forgejo↔Renovate
migration** workstream (ADRs 0011–0013 + RFC). Both are reflected below.

---

## ✅ Done

### P0 batch (2026-06-12)
- **#1** coredns split-DNS to k8s-gateway (a follow-up `bb7d647` fixed a duplicate-zone crashloop).
- **#2/#3** zomboid disable documented; stale empty `cnpg-dr/` + `apps/zomboid-exporter/` removed.
- **#5** `.gitignore` broadened for decrypted artifacts.
- **#9/#12** flux-local runs on push to main; yamllint added to e2e CI.
- **#10** ~30 pre-existing alert-annotation violations fixed + validator wired into CI; also fixed
  a Harbor alert that referenced a nonexistent metric and could never fire.
- **#61** ESO not-ready / sync-error alerts (metrics verified live).
- **#62** CNPG WAL/backup-age alerts — already shipped in the `cnpg-monitoring` component.
- **#41** InvoiceNinja MariaDB now has a nightly `mysqldump → Garage S3` backup (its only off-box path).
- **#59** etcd defrag — **resolved** (verified healthy above).
- Skipped with reason: **#11** kubeconform (26 false positives from `${SECRET_DOMAIN}`; flux-local
  already validates post-substitution).

### Reliability & resource right-sizing sprint (owner, 2026-06-12/13)
- Right-sized over-reserved workloads; **dropped ~40k unused apiserver + etcd/kyverno histogram
  series**; capped Dependency-Track heap → meaningful Prometheus/RAM relief.
- Kyverno background scan 1h→24h (event-churn reduction); **admission-controller hard-spread across
  nodes** (partial HA).
- Longhorn: `guaranteedInstanceManagerCPU` + a LimitRange giving BestEffort CSI sidecars default
  requests; GUAC + OpenBao BestEffort components given resources; OpenBao init-Job GC.
- **#7755eff** flux-local validation now works locally and fails loudly (closes the "no output"
  gap I hit during the P0 batch).

### Auth maturity (owner)
- Harbor OIDC client credential is now **fully GitOps** (no CLI ceremony) with a pinned RS256 signing
  key. This proves the self-managed-GitOps-OIDC-credential pattern that **#23** (observability auth)
  depends on — see [runbooks/observability-auth.md](docs/techdocs/docs/runbooks/observability-auth.md).

---

## 🔧 In progress — active workstream

### Forgejo ↔ Renovate migration (ADRs 0011–0013 + rfc-renovate-forgejo)
Dual-run Renovate against Forgejo with GitHub kept as the data oracle; static bot PAT; dormant
Forgejo path scaffolded. This is the owner's current focus — not on the original audit list. Keep
the RFC's phase gates as the source of truth for this stream; the roadmap just tracks that it's live.

---

## P1 — Next up (safe, unblocked, mostly fire-and-forget)

These need no live-cluster babysitting and are individually reversible. Good batch to take now.

| # | Item | Impact | Effort | Notes |
|---|------|--------|--------|-------|
| 73 | Rewrite `external-secrets-plan.md` + runbook from Infisical → OpenBao | High | M | 4 docs still describe a backend that doesn't exist; pure docs, zero cluster risk |
| 6 | gitleaks/trufflehog scan of **full git history** for key files | High | S | Confirm age.key/kubeconfig/tunnel.json never committed historically |
| 55 | Enable Flux HelmRelease `driftDetection` via the global Kustomization patch | High | S | 0 today; cheap insurance against silent drift |
| 53 | PriorityClasses for Flux/Cilium/CoreDNS/cert-manager/ESO/Longhorn | High | M | 0 today; makes OOM-eviction order deliberate, not luck (matters at ~80% CP RAM) |
| 54 | PodDisruptionBudgets for CoreDNS, envoy gateways, Authentik, CNPG | Med | M | 0 today (kyverno got anti-affinity only); protect against drain zeroing a service |
| 51 | Authentik server → 2 replicas, hard anti-affinity | High | S | Still 1/1 — SSO is a login SPOF |
| 52 | cloudflared → 2 replicas | High | S | Single tunnel pod = external access severed on one eviction |
| 40 | Add restore-test components to authentik, grafana, guac, dependency-track | Med | M | Author now (kept suspended like the others until CP RAM frees) |

## P2 — Build (structural; real effort, deferred risk)

| # | Item | Impact | Effort | Notes |
|---|------|--------|--------|-------|
| 23 | Prometheus/Alertmanager behind Authentik (Envoy `SecurityPolicy` OIDC) | High | M | Design ready; Harbor proved the GitOps-OIDC pattern — now lower-risk to land. Needs you at the cluster for the OIDC-flow test |
| 24 | Auth-matrix sweep: Longhorn, Policy Reporter, OpenBao UI, Backstage | High | M | Follows #23's pattern |
| 31 | Re-enable Hubble (gates network policy) | Med | M | Still disabled |
| 32/33 | Default-deny CiliumNetworkPolicy + per-ns allows; crown-jewel netpols (OpenBao, CNPG) | High | L | 6 NetworkPolicies, 0 Cilium, no default-deny today; do after #31 |
| 26–29 | Promote audit→enforce: image-verify, require-digest, RBAC, workload-hardening | High | L | The audit-mode ratchet; per-namespace rollout |
| 36/37 | Dynamic Postgres credentials (ADR-0010) — ship for one app, then fleet | High | L | Endgame for static DB secrets |
| 44 | Full DR drill of the hibernated `cnpg-disaster-recovery`; write runbook from it | High | M | |
| 45 | Garage SPOF: document RPO + evaluate 2nd Garage / replicated MinIO | High | L | 10 DBs + registry + media all depend on one box |
| 34 | Kubernetes API audit logging → Loki | Med | M | No control-plane audit trail today |
| 39 | Re-enable restore drills (staggered) **once CP RAM headroom improves** | Med | S | Blocked on memory, not etcd anymore |

## P3 — Horizon (high-effort or low current risk; decide accept-vs-implement)

| # | Item | Impact | Effort |
|---|------|--------|--------|
| 60 | Second SSD per soyo node for dedicated etcd storage (unblocks Pyroscope return) | High | L |
| 91 | Add a worker / document the fringe-workstation single-worker SPOF | High | L |
| 47 | OpenBao 3-node Raft (or document accepted single-node risk + unseal drill) | Med | L |
| 89 | Talos secure-boot + TPM disk encryption — decide in an ADR | Med | L |
| 68 | Bring Pyroscope back on fringe only (after #60) | Low | M |
| 94 | Per-node RAM budget doc + alert on allocatable-vs-requested > 85% | Med | M |

---

## Workstream view

- **Docs & hygiene** — #73, #6 → kill the Infisical-era contradiction; confirm no historical leaks.
- **HA & failure domains** — #51, #52, #53, #54, #55 → no single pod/node takes a tier down.
- **Auth everywhere** — #23, #24 (Harbor pattern now generalizable).
- **Network containment** — #31 → #32/#33.
- **Audit→enforce** — #26–29.
- **Secrets endgame** — #36/#37.
- **Backup/DR trust** — #40, #44, #45, #39 (when RAM allows).

## Sequencing notes

- **#59 etcd defrag is done** — restore-drill re-enable (#39) is now gated only on **CP memory
  headroom**, not etcd. Watch soyo-* memory; when it drops, #39 + #40 can go live staggered.
- **#31 (Hubble) gates #32/#33** — don't author default-deny blind.
- **#23 is de-risked** by the Harbor fully-GitOps-OIDC work; it's the highest-value P2 to pull forward.
- The **Forgejo migration** is the owner's active stream — sequence new work around its phase gates.
