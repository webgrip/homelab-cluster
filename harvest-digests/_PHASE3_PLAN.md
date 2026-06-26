# PHASE 3 SYNTHESIS — PLAN (read-only; nothing written)

## Reconnaissance summary

The repo already has **deep** coverage of most of this knowledge set: 36 ADRs, 17 RFCs, a `supply-chain-overview.md` + `supply-chain-pipeline.md`, a detailed `forgejo-runner.md` runbook, ADR-0035/0036 + `rfc-ci-pipeline-performance.md` (already capture the amd64/QEMU + action-clone-wall decisions almost verbatim), and 16 skills. So the synthesis is mostly **targeted gap-fills + corrections**, not bulk new docs.

**Verified against the repo:** `.worktreeinclude` exists; `scripts/{validate_grafana_alert_expr.py,check-kyverno-test-coverage.sh,posture-counts.sh,forgejo-sync.sh}` exist; commit `9938e09` (sbom:create grant) is real; ADR-0035/0036 registered in `adr/index.md`; spegel is referenced as a drifter only in `roadmap.md`/`ks.yaml`, not in `flux.md`.

**Verified ABSENT (cross-repo, keep out of homelab docs):** `scripts/forgejo-parity-check.sh` and `scripts/generate-forgejo-workflows.sh` do NOT exist here — the entire "CI library structure" / two-tree parity / per-registry-engine cluster lives in sibling repos `webgrip/workflows` + `webgrip/infrastructure`. Those are **out of scope for this repo's docs** (→ deferred / handoff-only).

---

## 1. Item → action → target file → why

| # | Knowledge item | Action | Target file (exact) | Why |
|---|---|---|---|---|
| 1 | Forgejo reusable-workflow **v15 expansion** flattens inner jobs, **ignores caller `if:`** → duplicate racing builds; caller-job-id ≠ inner-job-id | **create** | `docs/techdocs/docs/general/forgejo-actions-engine.md` (new) | HIGH-confidence engine behavior with no home today; bit a real incident; cross-cuts every reusable consumer |
| 2 | Composite/reusable **resolution splits by call-site**; `data.forgejo.org` is an incomplete mirror (404s on github-script/cosign/sbom-action/webgrip/*); `DEFAULT_ACTIONS_URL` unset | **create** (same new doc) | `docs/techdocs/docs/general/forgejo-actions-engine.md` | Same doc; ADR-0035 references the *symptom* but the resolution-by-call-site mechanism isn't written down |
| 3 | Workflow-dir precedence (first-existing-dir-wins, `.forgejo`→`.gitea`→`.github`); `workflow_call: secrets:` parser warning is benign | **create** (same new doc) | `docs/techdocs/docs/general/forgejo-actions-engine.md` | Dispels "double-runs both trees" fear; both HIGH-confidence |
| 4 | Empty `github.repository_owner`/`github.sha` in `workflow_dispatch`; CI-created release fires no release event (dispatch explicitly + `type: string`); `semantic-release-monorepo` version is the full namespaced tag | **create** (same new doc, "context gotchas" section) | `docs/techdocs/docs/general/forgejo-actions-engine.md` | HIGH-confidence Forgejo-vs-GitHub context differences; reusable across all webgrip CI |
| 5 | `agent_labels` fixed at registration; runner advertises ONE honest label `docker`; it's `forgejo-runner` not `act_runner`; DB-query check; logs show only DinD sidecar | **update** | `docs/techdocs/docs/runbooks/forgejo-runner.md` | Runbook already covers the runner; add the label-semantics + "logs only show dind, get job log from UI" + `action_runner` DB-query trick to its troubleshooting |
| 6 | KEDA warm-pool + `activeDeadlineSeconds` → false `KubeJobFailed` every ~2h | **skip** | `docs/techdocs/docs/runbooks/forgejo-runner.md` | Already documented (runbook lines 21-24 explicitly: "NO activeDeadlineSeconds … false KubeJobFailed churn") |
| 7 | Resource rightsize values (dind 4Gi→1.5Gi, minReplica 1→2, request-vs-limit scheduling) | **skip** | — | Already in runbook lines 36-39 |
| 8 | amd64-default + gated QEMU; buildx must stay; Harbor `:cache` ref; verifyRelease cache-only; offline-mode-absent; constrictor migration | **skip** | — | Fully covered by ADR-0035, ADR-0036, `rfc-ci-pipeline-performance.md` (read & confirmed near-verbatim) |
| 9 | cosign via OpenBao Transit + per-job OIDC, key-only Kyverno verify; `cosign-signer` JWT role binds `workflow_dispatch`/branch claim shape (not `event_name=release`/tags) | **update** | `docs/techdocs/docs/general/supply-chain-overview.md` | Overview's sequence diagram still shows `event=release` / `refs/tags/*` claims (lines 187-192, 215); the verified binding is `workflow_dispatch` / `refs/heads/*`. Correct the claim shape + the audience-URL `?`vs`&` gotcha |
| 10 | Harbor native SBOM gated by `sbom:create` NOT `scan:create`; `.sbom` accessory ≠ `.att` attestation; robot provisioner non-idempotent → convergence `PUT /robots/{id}` (commit 9938e09) | **create** | `docs/techdocs/docs/runbooks/harbor.md` (new "SBOM column & robot RBAC" section) — *or* a short new `docs/techdocs/docs/runbooks/harbor-supply-chain.md` | HIGH-confidence (from Harbor source), real 403 fixed in-repo; Harbor runbook has no SBOM/robot-RBAC section. Prefer extending `harbor.md` |
| 11 | Talos registry mirror is a silent no-op without `extraHostEntries` DNS resolution; node DNS (not pod DNS) for pulls; transparent mirror fail-open, no-reboot apply | **skip/verify** | `docs/techdocs/docs/adr/adr-0017-registry-mirror-talos-spegel.md` + `harbor.md` | Likely already in ADR-0017 — **must read ADR-0017 before writing** to avoid dup; if the `extraHostEntries` DNS prerequisite is missing, add a one-paragraph correction note. Tentative: **update** ADR-0017 only if gap confirmed |
| 12 | Harbor 2.15 proxy returns full tag list (Renovate works); `registryAliases` host-only; charts via URL-rewrite not mirror | **skip** | — | Already in MEMORY (`harbor-chart-routing-renovate.md`) and almost certainly ADR-0016; not a doc gap (verify against ADR-0016 — if absent, fold one line into `harbor.md`, else skip) |
| 13 | `task talos:upgrade-node` built-in drain **stalls on single-replica-PDB** (kyverno + CNPG) → force `kubectl drain --disable-eviction` first; stalled upgrade safe to Ctrl+C | **update** | `docs/techdocs/docs/runbooks/talos-rolling-upgrade.md` | **Confirmed gap** — grep shows NO mention of disable-eviction/PDB/force-drain; this caused a real silent-stall on all 5 nodes. High-value runbook addition |
| 14 | Post-reboot Longhorn churn self-heals serially; detect rebuilds via JSON `rebuildStatus` not table grep | **update** | `docs/techdocs/docs/runbooks/longhorn-rebuild-wedge.md` (or `longhorn.md`) | Useful operational gotcha; check existing longhorn runbooks first — likely an additive note, not a new doc |
| 15 | Node inventory/hardware (5 nodes, v1.13.4/k8s 1.36.1, SATA-not-NVMe, worker-1 hosts CNPG fleet) | **skip** | — | Covered by `runtime-inventory.md` + `talos-cluster.md` + ADR-0025; the talos skill already owns placement. (Verify version pins current; if `runtime-inventory.md` still says NVMe or an old version, **update** that one line) |
| 16 | etcd quorum math; 3 CP is HA minimum (corrects "go to 1"); fragility = correlated failure not node count | **skip** | — | Covered by `etcd-health.md` runbook + ADR-0025/0026; not a gap |
| 17 | Capability labels are the placement contract; Cilium L2 `CiliumL2AnnouncementPolicy` consumes node labels too (grep before retiring a label) | **update** | `.claude/skills/workload-placement/SKILL.md` *or* `talos` skill reference | The "grep all consumers incl. Cilium CRDs before dropping a node label" is a sharp gotcha the placement skill should carry. Light touch — likely a reference.md addition |
| 18 | Pin single-node RWO-shared app via node-unique capability label (RWX blocked); Kyverno blocks ALL RWX cluster-wide | **skip** | — | RWX-blocked is in ADR-0035, `network-policy`/`workload-placement` skills, and roadmap; the RWO-pin pattern is in ADR-0028. Confirm `workload-placement` skill mentions RWX-block; if not, one line |
| 19 | Break goharbor RWO Multi-Attach deadlock by deleting old ReplicaSet; DT api-server → StatefulSet; VCT storageClass immutable | **update** | `docs/techdocs/docs/runbooks/harbor.md` ("Common problems" table) + a note in `longhorn.md` | The RS-deletion fix for the Multi-Attach deadlock is a concrete, reusable recovery not in the harbor runbook's problem table |
| 20 | Grafana threshold rule needs top-level `expression:` (broke 16 SLO rules ~3wk); pre-flight via throwaway MCP rule | **skip** | — | Fully captured by ADR-0030 + the `grafana-dashboard` skill (validator `validate_grafana_alert_expr.py` exists). Verify the skill mentions it; if not, one line |
| 21 | PromQL anti-patterns: `count()` vs `sum()` over boolean gauge; empty set → NoData (`or vector(0)`), except intentional `noDataState: Alerting` | **update** | `.claude/skills/grafana-dashboard/SKILL.md` (reference) *or* `alerting-principles.md` | Sharp, reusable PromQL gotchas. `alerting-principles.md` is the natural doc home; the grafana skill the natural skill home. Add to one (prefer the skill's reference.md to keep it actionable) |
| 22 | Operator-managed Grafana ServiceMonitor needs `release:` label AND operator's actual selector labels | **update** | `docs/techdocs/docs/runbooks/observability-stack.md` or `grafana-dashboard` skill | Verified-specific gotcha (the blind spot that hid the 3-week outage). Light addition; read target first |
| 23 | Two independent alert engines (Grafana SLO CRDs + Prometheus/Sloth) with no unified view; dedupe done | **skip** | — | Likely in `observability-stack.md`/`supply-chain-pipeline.md` (the latter lists the GrafanaAlertRuleGroups). Verify; skip if present |
| 24 | Trivy/DT "supply-chain" numbers = whole-fleet third-party, NOT your images; `TrivyExposedSecretsDetected` mislabels High/Medium as critical | **skip** | — | Exactly the thesis of `supply-chain-cve-triage.md` (read & confirmed). Not a gap |
| 25 | Sloth burn-rate alerts linger post-recovery; disable alerts/SLOs in lock-step with workload (k6) | **update** | `docs/techdocs/docs/runbooks/synthetic-probes-blackbox.md` or `k6-canaries.md` | Useful operational note; read target first, additive only |
| 26 | Bootstrap Jobs/CronJobs need explicit worker pinning (worker-pool component patches Deploys/STS/CNPG, NOT bare Jobs) | **skip/verify** | ADR-0028 | Likely an ADR-0028 nuance already; if the "bare Jobs aren't patched" caveat is absent there, add one line. Otherwise skip |
| 27 | Forgejo exports NO Actions/CI metrics; runner logs not in Loki (OTel labels) | **update** | `docs/techdocs/docs/runbooks/forgejo-runner.md` (a "What you can't observe" note) + `forgejo.md` Observability | Counters-only `/metrics`, no run-duration; a CI dashboard needs a custom exporter. Short, prevents wasted dashboard attempts |
| 28 | Forgejo-leading cutover order; un-mirror = Danger-Zone Convert; verify via `.mirror` not anon push; `workflow` PAT scope; Actions+PRs units OFF after convert; don't copy GitHub status-check contexts; PAT `/user` 403 | **skip** | — | This is the **`forgejo-leading` skill's** domain (and ADR-0024 + MEMORY `forgejo-leading-repo-migration.md`). The skill already exists and matches. Verify the skill carries the `.mirror`-not-push + `workflow`-scope + status-check gotchas; if any are missing, **update the skill's reference**, not a doc |
| 29 | `gitea-mirror` config is SQLite/UI-only; `.profile`/`.profile-private`; no `.github`-org-defaults equivalent | **skip** | — | Belongs to `forgejo-leading` skill / MEMORY. Verify-then-skip |
| 30 | `gh api` prints error body to stdout on 404 → fallback must be outside `$(...)` | **memory** (not docs) | MEMORY note or `forgejo-leading` skill reference | Tiny shell gotcha; too granular for techdocs. Fold into the skill reference if a natural spot, else memory |
| 31 | Provision Forgejo org Actions secrets via OpenBao+CronJob; write-only API; reserved `FORGEJO_/GITHUB_/GITEA_` prefixes → use `WEBGRIP_` | **update** | `.claude/skills/provisioner-job/SKILL.md` (reference) | The reserved-prefix + write-only-verify-by-log gotchas are exactly provisioner-job territory and HIGH-confidence. Light reference addition |
| 32 | Write to OpenBao as admin via OIDC (root revoked); `kubectl exec` token is non-admin | **skip** | — | Almost certainly in `external-secrets` skill / `openbao-restore.md` runbook. Verify-then-skip |
| 33 | Safety hooks block kubectl/Longhorn/talosctl mutations by string-match (even `--help`/comments) | **skip** | — | Already in CLAUDE.md + `.claude/` hooks + the forgejo-runner runbook's GitOps-only note. Not a doc gap |
| 34 | `.worktreeinclude` copies gitignored bootstrap files into Claude-created worktrees only; worktrees don't solve push-to-main collisions; `claude --worktree` defaults | **create** (small) | `docs/techdocs/docs/general/worktrees.md` (new) OR a section in an existing dev-workflow doc | `.worktreeinclude` exists in-repo but is undocumented — a contributor finding it deserves an explanation. Small, HIGH-confidence. (The push-to-main-collision half is already in MEMORY) |
| 35 | Concurrent agents on unprotected `main` revert each other; fetch + verify-not-behind + explicit pathspec before push | **skip** | — | In CLAUDE.md (trunk-based rule) + MEMORY `concurrent-agents-main-collisions.md`. Reinforce in worktrees doc (#34), not a new doc |
| 36 | Repo validate/commit conventions; ADR/RFC conventions (nav + redirect_maps + index registration); mkdocs/TechDocs build in-cluster only, pin plugins before enabling | **skip** | — | CLAUDE.md + `skillsmith` + existing ADR/RFC index conventions cover this. Not a gap |
| 37 | skillsmith bang-backtick loader-injection gotcha; `${CLAUDE_SKILL_DIR}`/`$ARGUMENTS` expansion; command name = dir name | **update** | `.claude/skills/skillsmith/SKILL.md` (reference) | This is the skillsmith skill's own footgun — belongs in its reference. HIGH-confidence |
| 38 | Forgejo vs GitLab forge-choice rationale | **skip** (or optional blog) | — | MEDIUM-confidence, conceptual, no decision artifact. At most a blog post; not reference docs. Default skip |
| 39 | roadmap-topup maintains roadmap at 100 via posture-counts.sh | **skip** | — | The `roadmap-topup` skill owns this exactly |
| 40 | Apply + live-verify a Flux change; verify by real status not proxy artifact | **skip** | — | In `flux.md` runbook + CLAUDE.md GitOps rule + preference (→ memory). Not a doc gap |

---

## 2. NEW SKILL candidates

| Candidate | Purpose | When-to-use trigger | Source items |
|---|---|---|---|
| **`forgejo-actions`** (engine/CI authoring) | The Forgejo-Actions-vs-GitHub-Actions behavior gap when authoring/debugging in-cluster CI workflows: v15 reusable-workflow flattening (`if:` ignored, job-id collision, racing builds), call-site action resolution + `data.forgejo.org` 404s, workflow-dir precedence, empty `workflow_dispatch` contexts, semantic-release-monorepo tag shape, the no-release-event dispatch pattern, `runs-on: docker`. | Authoring/debugging a `.forgejo/workflows/*` or reusable workflow, "duplicate/racing build", "no files found after reading paths action.yml", a `uses:` 404 (`remote: Not found`), empty `github.sha`/`repository_owner`, "release didn't trigger the build", semantic-release version double-prefix. | Items 1–4, 27, parts of 5 (label semantics). **Strong candidate** — distinct from the `forgejo-leading` skill (repo cutover) and the `forgejo-runner` runbook (the pod/KEDA infra). This is the missing third leg: *workflow authoring semantics*. |
| *(reject)* `git-worktrees` skill | — | — | Worktree knowledge (#34) is thin and one-shot → a small **doc** (`general/worktrees.md`), not a skill. Documented, not skill-ified. |
| *(reject)* `forge-choice` skill | — | — | One-time conceptual decision; at most a blog. Not procedural/repeatable. |

The **CI library structure / two-tree parity / per-registry engine** cluster (knowledge "CI library structure & semantic-release on Forgejo") is a candidate **handoff doc, not a skill, and not for this repo** — its scripts (`forgejo-parity-check.sh`, `generate-forgejo-workflows.sh`) live in `webgrip/workflows`/`infrastructure`. Recommend it stay in those repos' docs; here at most a one-line pointer from the existing `handoffs/webgrip-*-harbor-publish.md`.

---

## 3. Conflicts with existing docs/skills

| Existing file | Nature of conflict | Resolution in plan |
|---|---|---|
| `docs/techdocs/docs/general/supply-chain-pipeline.md` | **Stale architecture.** Written GitHub-first: "GitHub Actions workflow … GitHub OIDC identity `token.actions.githubusercontent.com` … pushes to GHCR … keyless." The new verified truth is **Forgejo-leading, key-based via OpenBao Transit, Harbor-primary, dual-publish**. The Kyverno OIDC contract section (subject = `github.com/webgrip/infrastructure/.github/workflows/...@refs/tags/*`) is now wrong for the Harbor path. | **Flag for update**, but NOT blindly rewrite — the GHCR/keyless path still exists as the `.github` mirror. Add a "this describes the legacy GHCR path; the primary path is now Forgejo+Transit, see supply-chain-overview.md" banner + correct the Kyverno contract to note the Harbor key-only policy. Needs owner approval on scope (full rewrite vs. banner+pointer). |
| `docs/techdocs/docs/general/supply-chain-overview.md` (sequence diagram) | **Claim-shape mismatch.** Diagram shows OIDC claims `event_name=release`, `ref=refs/tags/*` (steps 7, 187-192, 215). Verified binding is `event_name=workflow_dispatch`, `ref=refs/heads/*` (the original tag-based binding 400'd). | Item 9 — update the claim shape + add the audience-URL `?`vs`&` gotcha. |
| `docs/techdocs/docs/adr/adr-0035-action-clone-wall.md` (+ rfc-ci-pipeline-performance) | **No conflict — already correct.** Knowledge set flagged copy-16's "pre-baked cache" framing as superseded by copy-13's "scoped LAN mirror, offline-mode-absent." The repo ADR already reflects copy-13. | Skip (item 8). |
| Knowledge "runner advertises `docker, default, ubuntu-latest`" (copy 7) vs `docker` only (copy 5) | Internal-to-knowledge conflict, already resolved to single `docker` (DB-verified). `forgejo-runner.md` runbook already says "advertises exactly one honest label — `docker`" (line 13). | No conflict with repo; item 5 just adds the *why* (agent_labels at registration). |
| Knowledge `scripts/forgejo-parity-check.sh` / `generate-forgejo-workflows.sh` | **Do not exist in this repo** (verified). Knowledge sourced them from sibling repos. | Keep out of homelab docs (deferred/handoff). |
| Knowledge "DT uses `strategy: Recreate` via postRenderer" (called stale in-knowledge) vs "converted to StatefulSet" | Already self-corrected in the knowledge set; need to ensure no existing repo doc still says Recreate-postRenderer. | Item 19 — verify `harbor.md`/any DT doc; correct if stale. |

---

## 4. Preferences → memory (NOT docs)

- **Enforce nothing yet — Audit only.** Flip Kyverno `image-verify-harbor-audit` + GHCR policies Audit→Enforce only after a release is green with zero false positives. Explicitly not done.
- **Verify by REAL status, not a proxy artifact.** A published tag/Release ≠ a green CI run; "I updated the IaC" ≠ "the running resource changed." Quote concrete evidence (exact line + log) over assertion. User repeatedly asks "so it all works now?" and pushes back on premature "verified."
- **Challenge/verify what a metric actually measures before reporting** (the supply-chain alerts = third-party fleet, not their images).
- **GitOps-first, statelessly rebuildable, one scoped change at a time;** prefer reconciled-from-git mechanisms (provisioner Jobs/CronJobs, ESO, publisher CronJobs); surface irreducible manual prereqs as explicit handoffs. Acceptable exception: one-time OpenBao `generate-root` break-glass.
- **Labels must be TRUE, not masks.** It's `forgejo-runner`, not `act_runner` — don't reason from `act` docs (corrected 3×).
- **Author RFC/ADR before implementation; constrictor/strangler additive pattern** ("ghcr should be ghcr, harbor should be harbor"); don't repurpose an existing workflow; don't RFC a trivial change.
- **Pin missing external actions to github.com case-by-case** (greppable), NOT a global `DEFAULT_ACTIONS_URL` flip.
- **Forgejo is leading; GitHub mirrors Forgejo; neither cuts separate releases.** Wants `package.json` bumped on release; inter-image base pinned by version+digest with Renovate tracking.
- **Respect deliberate deferrals** (longhorn SC at 3 replicas is a decision, not a bug); don't break a HelmRelease via an immutable-VCT swap without a coordinated owner recreate — present the trade-off.
- **Skills must be token-conscious; only date incident-derived rules** (no ship-dates), present-state in present tense; use the actual skill, not a manual re-implementation; use documented flows/recipes not raw commands.
- **Triage-then-handover:** lead with read-only state assessment, then hand a complete ordered copy-pasteable command set for hook-blocked mutating steps. User verifies via pasted CI logs from the IDE.
- **Node-touching Talos applies are human-gated;** stage GitOps-side first. **`webgrip.dev` is not sensitive** (fine in plaintext `talenv.yaml`).
- **Scripts must NEVER print token values** (length/HTTP-code/masked only). Casual/collaborative; comfortable doing manual UI steps while assistant scripts the deterministic parts.
- (Existing memories already cover: NL fast-learning hardware beginner / EU sourcing / power-cost weighting; dashboard UX preferences. → no change, just confirm not contradicted.)

---

## 5. Open questions / TODO (NOT docs)

- **[CI]** Real-job A/B of the amd64-fast path; verifyRelease ≤2-min target; confirm `-fast` files synced to the Forgejo mirror; verifyRelease changes left uncommitted in both sibling repos.
- **[CI]** Is the action-clone wall still significant once QEMU is gone? If yes, execute ADR-0035's scoped LAN mirror (~6 docker-build action repos).
- **[CI]** Forgejo `actions/cache@v4` persistence of `~/.npm` across ephemeral runs — unverified.
- **[CI]** Forgejo-Actions-API → Prometheus exporter + Grafana "CI overview" dashboard — the only viable better-UI/trends path (native `/metrics` is counters-only).
- **[CI]** Final controlled release: confirm image+signature in BOTH Harbor and GHCR, the `chore(release) [skip ci]` commit-back, GitHub Releases populated.
- **[CI]** Flip Kyverno Audit→Enforce once a release is green with zero false positives.
- **[Harbor]** Final visual confirmation of the SBOM column on the next real release; whether the explicit pipeline SBOM POST is redundant given `auto_sbom_generation`.
- **[Harbor]** Full warm Job run (digest-normalized refs); ADR-0016/0017 + rfc-harbor-proxy-cache need a correction note about the `extraHostEntries` DNS prerequisite (the original fallback drill was non-representative); 6 images can't be routed (`reg.kyverno.io/*`, `oci.external-secrets.io/*`).
- **[Forge migration]** Mirror token fix not applied (`GH_MIRROR_TOKEN` lacks `workflow` scope); infrastructure mirror divergence; GitHub Actions still enabled on migrated repos; `--all` sweep needs `read:organization`; ~65 repos remain.
- **[Docs]** `techdocs-builder` image must be rebuilt+published with `mkdocs-redirects==1.2.2` before the next docs build (plugin already enabled → build fails until rebuilt); homelab-cluster has no `on_docs_change.yml`.
- **[Storage/HA]** etcd backups don't exist (roadmap #52); spegel `driftDetection.ignore` not applied; Longhorn volume backups never actually ran (BackupTarget Available but no backups); Garage S3 single host = SPOF; whether to use worker-1 as a second Longhorn replica home.
- **[Talos/placement]** Label-drop (`nodegroup`/`workload-tier`) not yet run on live nodes (roadmap #34); authentik node-HA needs media→S3 first; whether worker-1's CNPG DBs landed on a soyo during its force-drain — flagged, unverified.
- **[Observability]** Kyverno audit→enforce flips deliberately not executed; owner-gated: seed Codeberg PAT, `talosctl etcd defrag`, re-enable pyroscope; `harbor-jobservice` flapping CrashLoopBackOff.
- **[Worktrees]** Decide whether to add a universal post-checkout git hook + `scripts/new-worktree.sh`; copy-vs-symlink drift for rotated files unresolved.
- **[Runner]** GHCR `webgrip/*` package visibility unknown (private → needs ghcr-pull secret in keyless policies); `infrastructure/ops/kyverno/.../verify-webgrip-images.yaml` keyless-Enforce policy should be removed/converted.

---

## 6. DEFERRED (low-confidence / unverifiable / out-of-scope)

| Item | Confidence | Reason deferred |
|---|---|---|
| **CI library two-tree parity, per-registry engine, `forgejo-parity-check.sh`, `generate-forgejo-workflows.sh`, tiered T1/T2/T3 port, semantic-release pin set, Forgejo REST shapes** | HIGH but **cross-repo** | Verified those scripts/files do NOT exist in homelab-cluster — they live in `webgrip/workflows` + `webgrip/infrastructure`. Document there, not here. At most a one-line pointer from existing `handoffs/`. |
| `on_source_change` occasionally misses a push; amending doesn't re-trigger | MEDIUM ([ASSERTED]) | Transient/unreproduced; keep out of docs until reproducible. → forgejo-actions skill reference at most, as a "known flakiness" line. |
| `@semantic-release/exec` `verifyReleaseCmd` Lodash-templated (build dynamic strings in JS) | MEDIUM ([ASSERTED]) | Belongs to sibling-repo `.releaserc.js`; not a homelab-cluster artifact. Defer to infra repo. |
| Mirroring base-image pulls belongs in buildkitd builder config not dind ConfigMap | MEDIUM ([ASSERTED], approach backed out unshipped) | Already in MEMORY (`forgejo-runner-base-image-mirror-layer.md`); design analysis, not a settled doc. Keep in memory only. |
| Dockerfile base-registry ARG parameterization + GHCR-proxy inter-image pin | HIGH but **cross-repo** | Lives in `infrastructure/ops/docker/*/Dockerfile`; not in this repo. Defer to infra repo docs. |
| helm-controller cache-sync rollback driven by loaded control-plane API | **LOW** ([ASSERTED] hypothesis, causation unproven) | Knowledge set itself says "needs verification." Do not enshrine. → open question / memory note at most. |
| Default longhorn SC still provisions 3 replicas on 2 storage nodes (deliberate deferral) | HIGH | Verified deliberate (ADR-0029 Stage 2). Not deferred as *unverified* — but it's a respect-the-deferral note, already in ADR-0029. Skip from docs; → memory preference (already captured in §4). |
| Parallel-AI-agent worktree tooling landscape (Claude Squad, Vibe Kanban, etc.) | **LOW** ([ASSERTED], web research) | Generic ecosystem trivia, not repo-specific, ages fast. Exclude from docs entirely. |
| Forgejo vs GitLab forge-choice | MEDIUM (conceptual) | No decision artifact; at most a future blog. Default exclude. |
| `gh api` 404-stdout / `git commit -- pathspec` ordering / zsh glob hard-error / `git -C` cwd-reset | HIGH but **too granular** | Tooling micro-gotchas; clutter techdocs. → fold the highest-value ones into the relevant skill *reference.md* (forgejo-leading / skillsmith) or leave in memory, not standalone docs. |

---

### Recommended write set if approved (smallest defensible footprint)

**New (3):** `general/forgejo-actions-engine.md` (items 1–4, +27) · `general/worktrees.md` (item 34, small) · *(optional)* extend `runbooks/harbor.md` rather than a new harbor-supply-chain file.
**Update (docs, ~6):** `runbooks/talos-rolling-upgrade.md` (#13, confirmed gap) · `runbooks/forgejo-runner.md` (#5, #27) · `general/supply-chain-overview.md` (#9 claim-shape) · `general/supply-chain-pipeline.md` (#9/conflict banner — *scope needs your call*) · `runbooks/harbor.md` (#10, #19) · `runbooks/flux.md` (spegel-as-known-drifter note).
**Update (skills, ~4):** `forgejo-leading` ref (#28-30 gaps if any) · `provisioner-job` ref (#31) · `skillsmith` ref (#37) · `grafana-dashboard` or `workload-placement` ref (#17, #21, #22 — pick one home each).
**New skill (1):** `forgejo-actions` (workflow-authoring semantics) — strongest candidate; complements existing `forgejo-leading` + `forgejo-runner`.

**Two decisions I need from you before writing:**
1. **`supply-chain-pipeline.md`** — full rewrite to Forgejo-leading, or a stale-banner + pointer to `supply-chain-overview.md` (lower-risk)?
2. **`forgejo-actions` engine knowledge** — new standalone **skill**, or just the **general doc** `forgejo-actions-engine.md` (or both)?

Nothing has been written. Awaiting approval.
