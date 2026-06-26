# Truth-Check Report

## Stats

- **Total items checked: 107** (B1=13, B2=15, B3=10, B4=4, B5=10, B6=9, B7=16, B8=12, B9=18)

**By verdict:**
| Verdict | Count |
|---|---|
| CONFIRMED | 79 |
| CORRECTED | 2 |
| REFUTED | 1 |
| PARTIAL | 24 |
| UNVERIFIABLE | 1 |

**By confidence:**
| Confidence | Count |
|---|---|
| HIGH | 82 |
| MEDIUM | 23 |
| LOW | 2 |

---

## ⚠️ Corrections — what the consolidated set got WRONG or oversimplified

Every CORRECTED / REFUTED / PARTIAL item, ordered by doc impact (highest-impact / about-to-write-first at top).

| item | original claim | corrected truth | evidence (repo path:line or URL) | doc impact |
|---|---|---|---|---|
| **B4-1** cosign signing / key-only Kyverno verify (no Rekor) | Harbor=key, GHCR=keyless OIDC/Fulcio/Rekor; the GHCR keyless policy explicitly sets rekor.url; key-only verify with "no rekor block → no tlog lookup" | **Both Harbor AND webgrip GHCR are key-signed** with one OpenBao Transit ECDSA-P256 key (`cosign-webgrip`, `--tlog-upload=false`). There is no webgrip keyless+rekor.url policy — rekor.url only governs third-party `ghcr.io/kyverno/*`. **"No rekor block → no tlog lookup" is wrong**: Kyverno (1.18.1, cosign 2.0) verifies the Rekor tlog **by default**; a `--tlog-upload=false` signature needs an explicit `rekor:{ignoreTlog:true}` per verifyImages entry, which the three Audit policies currently LACK (latent bug masked by Audit mode). | `image-verify-audit.yaml:48-55` (webgrip GHCR now key-based), `:87-88` (rekor.url only on kyverno rule); commit `fc5fdf1` (2026-06-26); Kyverno issue #11771; `image-verify-harbor-audit.yaml:62-63` (no rekor block) | **Material.** Stop calling webgrip GHCR keyless; reserve keyless+rekor language for third-party kyverno images. Add `rekor.ignoreTlog:true` to all three verify policies as a **gate before any Audit→Enforce promotion**. The stale `supply-chain-pipeline.md` ("keyless") and stale CLI test rule names (`verify-github-slsa-provenance`/`verify-cyclonedx-sbom`) need fixing. |
| **B3-5** per-registry build/push engine | The original `.github` `docker-build-push-ghcr` action was actually the generic engine (display name "(Registry)", "Harbor by default") — a misnomer | **Misattribution.** The live `.github/composite-actions/docker-build-push-ghcr` is named **"(GHCR)"**, hardcodes `registry: ghcr.io`, and **rejects non-ghcr.io tags** — it is genuinely GHCR-only. The generic "(Registry)" / "configurable OCI registry, Harbor-default" engine is a **NEW** `.forgejo docker-build-push-registry` composite, not a renamed old one. (Core structural claim — one engine + thin harbor/ghcr wrappers, `HARBOR_ROBOT_*`→`REGISTRY_USERNAME/TOKEN`, `runs-on:docker` — is confirmed.) | `.github/composite-actions/docker-build-push-ghcr/action.yml` (name "(GHCR)", `:45` registry ghcr.io, `:79` "Only ghcr.io registry is allowed"); `.forgejo/composite-actions/docker-build-push-registry/action.yml` (name "(Registry)") | **Yes.** Correct any skill/doc text saying the old `-ghcr` action was "actually the generic engine / Harbor by default". State: a NEW `docker-build-push-registry` engine was introduced in `.forgejo`; the old `.github` `-ghcr` action stays ghcr.io-only and frozen. |
| **B8-11** Forgejo CI metrics + runner logs | Forgejo exports no Actions metrics AND runner logs are NOT in Loki (OTel-style labels only, no namespace/pod/container) | **REFUTED (Loki half).** Loki now carries `namespace/pod/container` labels alongside OTel labels, and **Forgejo runner logs ARE present** (`{pod=~"forgejo-runner.*"}` = 2 streams/701 entries; `{namespace="forgejo"}` = 5 streams/1048 entries). The alloy pipeline was relabeled since the digest. (Metrics half CONFIRMED: `/metrics` is `gitea_*` count gauges only, no CI timing → still needs a custom exporter.) | live Loki `list_loki_label_names` = [cluster, container, deployment_environment, …, namespace, pod, …]; `query_loki_stats` results | **Yes — split the item.** Keep the metrics gotcha (no native CI timing → custom exporter). DROP/rewrite the Loki claim: runner logs are queryable via LogQL on `namespace`/`pod`; the "logs not in Loki" workaround is obsolete. |
| **B9-13** ADR/RFC documentation conventions | Decisions get an ADR number ONLY when ratified; pending ones are listed as unnumbered candidate ADRs | **CORRECTED.** ADRs are numbered when **authored/proposed**, advancing Proposed→Accepted in place — `adr-0033` and `adr-0034` are live counterexamples (numbered AND Status: Proposed). There is no "unnumbered candidate ADR" convention; "candidate/pending" is a Status value, not a number-withholding rule. (All other sub-claims — paths, banner, sections, dual-registration, stale `architecture/` text, RFC wiring, markdownlint rules — are correct.) | `ls adr/` = adr-0001..0036; `adr-0033`/`adr-0034` numbered + Status:Proposed; `adr/index.md:12` (stale architecture/ path) | **Yes.** Fix the convention note: ADRs get a number at authoring time (Proposed); drop the "unnumbered candidate ADR" framing. Flag the `String(content).replace(backticks, ZWSP)` github-script tip as infrastructure-repo-specific (not in this repo). |
| **B4-3** Harbor SBOM trigger / two cosign actions asymmetry | The `.github` mirror pushes to GHCR via keyless OIDC/Fulcio/Rekor (part of the trust chain) | The cluster now **verifies webgrip GHCR with the OpenBao Transit KEY** (see B4-1). If the `.github` mirror still signs keyless at push time, that is build-side only and is **no longer what Kyverno trusts** — do not present GHCR as a keyless target in the trust chain. (SBOM-asymmetry, fail-soft `::warning::`, `curl -K` 0600, cosign 2.4.3/Syft 1.21.0 github.com pins, DT `:8080/api/v1/bom` all CONFIRMED.) | DT endpoint `sbom-uploader/cronjob.yaml:58`, `policy-bootstrap/job.yaml:27`; OpenBao role `config.sh:65-75`; cross-repo action in webgrip/infrastructure | **Mostly keep; one fix.** Drop/qualify the "GHCR = keyless Fulcio/Rekor" characterization. Cross-repo `.forgejo/actions/cosign-sign-attest` details unverifiable here. |
| **B1-1** reusable-workflow expansion → racing builds | Forgejo ≥15 expansion flattens inner jobs so a caller's `if:` doesn't gate them — unconditionally | **Expansion is CONDITIONAL**: it flattens only when the calling job **OMITS `runs-on`** (PR #10525, "expands only when runs-on is absent"). Under that condition the caller's `if:` doesn't gate inner jobs (independent dispatch) → both mutually-exclusive calls build. If the caller keeps `runs-on`, no expansion happens and `if:` gates normally. | forgejo.org/2026-04-release-v15-0; Codeberg PR #10448→#10525, #10614; `ocirepository.yaml:13` (17.1.0) | **Yes.** Docs/skill must state the runs-on-omission precondition; adding `runs-on` to the caller is itself a valid dedupe alternative. |
| **B5-9** Harbor coordinates/version/storage metrics (REFERENCE) | Storage growth via `harbor_statistics_total_storage_consumption` / `harbor_project_quota_usage_byte` | **Metric names WRONG/unverified.** The repo prometheusrule wires only `harbor_core_http_request_total`/`up{}`; the repo runbook (`harbor.md:80-83`) names different metrics and flags them unverified; the canonical Harbor exporter metric is **`harbor_quotas_size_bytes`** (type hard/used) / `harbor_system_volumes_bytes`. (All other coordinates — chart 1.19.1/2.15.x, LAN-only envoy-internal 10.0.0.27, in-cluster `:80`, private `webgrip`, `oidc_admin_group harbor-admins`, break-glass user `admin`, OpenBao `secret/harbor/robot-webgrip` — CONFIRMED.) | `prometheusrule.yaml` (no quota metrics); `harbor.md:80-83`; sysdig/goharbor metrics docs | **Yes.** Do NOT carry the two bogus metric names into docs; use `harbor_quotas_size_bytes`/`harbor_system_volumes_bytes` (or mark unverified pending first scrape). |
| **B5-7** manifest-GET vs pull / skopeo warm procedure | Warm Harbor via an in-cluster skopeo Job; ref-normalization + tag+digest rejection rules | **Mechanism CONFIRMED** (manifest GET doesn't register/cache/scan; a real pull does; digest pin already guarantees image==running). But the **skopeo-Job warm procedure and ref-normalization rules are an unbuilt/unexecuted plan** ("full warm run pending") — no committed artifact. | `find -iname '*skopeo*'/'*warm*'` = none (expected, unbuilt); Harbor proxy-cache + OCI digest semantics | **Yes.** Present the manifest-GET-vs-pull mechanism + digest-pin equivalence as established; mark the skopeo warm-Job and normalization details as an unexecuted procedure to validate before relying on it. |
| **B5-8** proxy-cache provisioner / proxy-project list | Six upstream proxy projects (dockerhub, ghcr, quay, gcrmirror, k8s, forgejo) | **Stale enumeration.** The live configmap creates a **7th** proxy project `mcr → mcr.microsoft.com` (playwright base) and `dockerhub` uses Harbor's native **docker-hub provider** (url `hub.docker.com`), not a generic docker-registry. (Talos mirror still has six — mcr is proxy-only, no Talos mirror.) | `harbor-proxy-config.configmap.yaml:229-231` (mcr), `:203` (docker-hub provider) | **Yes.** List SEVEN upstream proxy projects (add mcr); note dockerhub uses Harbor's docker-hub provider; keep the Talos-mirror count at six. |
| **B8-1** spegel DriftDetected | spegel is the ONLY HR that perpetually drifts | Mechanism (global `mode:warn` patch, unapplied per-HR `ignore` fix, DaemonSet server-default drift) CONFIRMED; the word **"ONLY"** could not be re-verified across all HRs (requires live `gotk_reconcile_condition` sweep). The "third defaulted field" is hand-waved. | `flux/cluster/ks.yaml:38-43`; spegel HR has no `driftDetection` block (fix unapplied); roadmap item 75 | **Soften "only HR"** to "the persistent/notable HR drift we've seen"; cite proposed ignore paths + roadmap item 75. Mechanism doc value stands. |
| **B8-7** Trivy/DT supply-chain numbers | trivy-sbom-uploader CronJob Sundays **02:00**; auto-populates **159** projects | Schedule is **Sunday 02:10** (`10 2 * * 0`), not 02:00; count is a moving snapshot (**159→163**, "~160 and growing"); the resource is `dependency-track/app/sbom-uploader`, not a standalone "trivy-sbom-uploader". (Whole-fleet third-party scope and false-critical paging CONFIRMED.) | `sbom-uploader/cronjob.yaml:24` (`10 2 * * 0`); live `dt_portfolio_projects{state=total}`=163; `prometheusrule.yaml:65-72` | **Minor.** Write schedule "Sunday 02:10", count "~160 (grows over time)", resource `dependency-track/sbom-uploader`. |
| **B8-8** Sloth burn-rate alerts linger | Burn-rate SLO alerts keep firing after recovery because the burned budget is still in the long window | **Oversimplified.** Sloth MWMB page rules require long **AND** short window over threshold; the short window resolves pages **quickly** after recovery. What lingers is long-window ticket/warning rules or re-breaches, not the page rule "indefinitely". (Lock-step disable of k6 SLO + `K6CanaryMetricsMissing` is shipped/CONFIRMED; "check `probe_success` now" advice is sound.) | sloth.dev MWMB docs + SRE workbook; `sloth/slos/kustomization.yaml:11`; `prometheusrule-synthetic-k6-canaries.yaml` commented out | **Adjust the explanation** (replace "budget still in long window" with the long-AND-short-window MWMB mechanism). Keep lock-step disable guidance verbatim. |
| **B9-2** safety hook blocks mutations (string-match) | `guard-destructive.sh` blocks via **string-match** (even `--help`/comments); blocks Longhorn vol/replica/node mutations | **Regex/word-based** (`grep -qE` on collapsed command), NOT literal string-match. It does NOT block `kubectl get` nor recoverable `kubectl delete pod/job` (only protected resource TYPES + `-f`). There is **no Longhorn-specific rule** in the file — Longhorn is caught only via generic `kubectl patch`/protected-delete. No `--help` carve-out, so help/comment text with a trigger word can trip it. | `guard-destructive.sh:21,26-35` | **Refine** the skill/memory note: "regex/word-based, no --help exemption"; drop the dedicated Longhorn-rule claim. Keep practical advice (strip trigger words; hand destructive cmds to human). |
| **B6-1** Forgejo-leading repo cutover / un-mirror | Un-mirror has NO REST API — UI-only ("Convert to a regular repository" in Danger Zone) | Order + Danger-Zone Convert CONFIRMED, but **un-mirroring is no longer strictly UI-only**: Forgejo added `POST /repos/{owner}/{repo}/convert` (PR #8932, merged 2025-09-14, backported to 15.0/16.0). Cluster runs chart 17.1.0 (app ~15.0.x) which plausibly carries it. | `forgejo-leading/SKILL.md:16-39`; Forgejo PR #8932; forgejo.org/docs/v15.0 repo-mirror | **Update** the skill's "no REST API" framing — note `POST .../convert` could automate bulk un-mirroring. Keep manual Danger-Zone path as the documented/verified route but stop asserting it's the ONLY way. |
| **B9-17** skillsmith loader bang-backtick injection | Loader substitutes `${CLAUDE_SKILL_DIR}` and `$ARGUMENTS` | Behavior (loader executes bang-backtick at load → embedding the literal token self-triggers "command not found"; command name = directory name, not frontmatter) is correct. The exact **substitution-variable spelling** (`${CLAUDE_SKILL_DIR}` vs `${CLAUDE_PLUGIN_ROOT}`) is harness-version-dependent and unconfirmed. | Claude Code skills/slash-command docs; `.claude/skills/` dirs | **Keep the gotcha** (never write the literal bang-backtick token in a SKILL.md body; put it in reference.md). Verify the env-var name against the deployed harness before publishing it as canonical. |
| **B9-14** TechDocs/mkdocs plugin pinning | Pin `mkdocs-redirects==1.2.2` in `infrastructure/ops/docker/techdocs-builder/Dockerfile`; plugins:[- redirects] not yet enabled | Mechanics (install-before-enable, file-relative links, in-cluster Backstage build) CONFIRMED, but the Dockerfile path + version pins are **cross-repo** (webgrip/infrastructure, not homelab-cluster). In homelab-cluster the redirects plugin is **already wired** via `mkdocs.yml redirect_maps`, so the live risk is "the builder image must carry mkdocs-redirects or the build fails", not "don't enable it yet". | `mkdocs.yml` uses redirect_maps (enabled); Dockerfile/pins cross-repo | **Attribute** Dockerfile/pin specifics to the infrastructure repo. Keep the provider-agnostic rule (install plugin in image before enabling; file-relative links; Mermaid label hygiene). |
| **B6-7** gitea-mirror SQLite / `.profile-private` | Members-only org profile = a `.profile-private` repo | `.profile-private` is a **GitHub convention** — Forgejo only documents the public `.profile` repo (root `README.md`); making it private just hides the README. Treat `.profile-private` as unverified for Forgejo. (All gitea-mirror facts — v3.8.4, `/app/data` SQLite, 2Gi, forgejo ns, UI-only — and the `.profile` root-README fact are CONFIRMED.) | `gitea-mirror/app/helmrelease.yaml:40-41,62`; forgejo.org/docs/latest/user/profile | **Drop/flag** the `.profile-private` members-only claim as unverified-for-Forgejo. Keep gitea-mirror SQLite/UI-only + `.profile` root-README facts. |
| **B1-6** workflow_call secrets warning is benign | The `workflow_call.secrets` parser warning is benign at runtime | **"Benign" only for pure-reusable files** never triggered standalone. For a file that ALSO has `push`/`pull_request` triggers, the rejection **suppresses those triggers too** (issue #6069) — NOT benign. `workflow_call.secrets` is unsupported; pass secrets from the calling job. | Codeberg issue #6069; forgejo/act PR #70 | **Yes.** Qualify "benign": holds only for files with no non-workflow_call trigger; mixed-trigger files silently lose push/PR runs. |
| **B1-8** `github.repository_owner`/`github.sha` empty on workflow_dispatch | Both are empty on workflow_dispatch (hardcode webgrip in derived refs) | The github context is incomplete on workflow_dispatch and the hardcode-webgrip workaround is real/correct, but the **exact pair (owner + sha both empty)** could not be independently confirmed upstream — treat as observed, possibly version-specific; re-verify after Forgejo upgrades. | `openbao/bootstrap/config.sh:71` (workflow_dispatch path); Forgejo #4789 | **Yes.** Keep the workaround (defensive regardless); flag the underlying emptiness as observed/version-dependent, not a documented invariant. |
| **B1-2** caller job id must differ from inner job ids | Caller-id == inner-job-id under expansion → "must contain at least one job without dependencies" | The error and v15 expansion are independently CONFIRMED, but the **specific collision mechanism** is in-thread-observed, not upstream-documented, and only applies when expansion is active (caller omits `runs-on`). | Forgejo Actions reference (validation rule); PR #10525 | **Yes.** Keep the rename-the-caller fix + misleading-error warning, but tag the exact mechanism as observed-not-upstream-documented and conditional on runs-on omission. |
| **B6-3** GitHub push-mirror PAT needs workflow scope | (CONFIRMED claim) | CONFIRMED, but the in-repo script comment is wrong: `scripts/forgejo-sync.sh:24` documents `GH_MIRROR_TOKEN` as "scope repo" only — it must be **repo + workflow** or workflow-file commits fail to mirror while tags/releases still sync. | `scripts/forgejo-sync.sh:24`; GitHub discussion #26254 | (Listed for completeness — verdict was CONFIRMED.) Update the script's `GH_MIRROR_TOKEN` comment to "repo + workflow". |
| **B2-2** agent_labels fixed at registration | A runner advertises only labels stored at registration; config.yaml does NOT update the server (blanket) | **Path-specific, not universal.** True for the ephemeral one-job path here (one-job invoked without `--label`, provisioner registered without labels). But **daemon-mode runners re-declare labels from config on restart**, and re-registration without `--labels` RESETS them (hence `--keep-labels`). ("forgejo-runner not act_runner" + one-job flag surface CONFIRMED.) | `configmap.yaml:27`; `scaledjob.yaml:140-144,191`; code.forgejo.org runner v12.10.2 cmd.go; PR #4610 (`--keep-labels`) | **Yes.** Scope the claim to the one-job/ephemeral path; note daemon-mode runners DO update labels from config on restart. Keep the "query `action_runner` Postgres; empty version = never ran" tip. |
| **B7-11** helm-controller cache-sync rollback (LOW) | A loaded soyo apiserver caused the cache-sync timeout → rollback loop | Symptom (`context deadline exceeded` rollback loop from a postRenderer patch; emptied control-plane let the harbor move succeed) is real, but the **causal claim remains an unverified hypothesis** — the postRenderer was also removed (confound). | `dependency-track/app/helmrelease.yaml:28-33` (corroborates one half); commit `2db5b15` | **Keep framed as a hypothesis** to investigate, not a rule. Pair with the confirmed lesson: a post-render affinity patch (not native nodeSelector) drove DT's rollback loop, reverted in `2db5b15`. |
| **B3-9** Forgejo auth + Releases/Issues REST shapes | Asset upload `-F "attachment=@<file>"`; `# Forgejo: dropped <X>` GHAS/Models comments | Core auth model + REST shapes are code-backed/CONFIRMED, but **two sub-claims unverifiable in this checkout**: the literal multipart field `-F "attachment=@<file>"` (code shows `?name=` + multipart, exact field name not located) and the "GitHub Advanced Security/Models dropped" comment convention. | committed `.forgejo` workflows (issues/generate/topics/releases); `wordpress-plugin-release*.yml:262/266` | **Minor.** When documenting asset upload, verify the multipart field name against the actual curl rather than copying from the digest. |
| **B5-... (none beyond above)** | | | | |

---

## Unverifiable / needs owner or live-cluster action

- **B1-7 (`on_source_change` occasionally misses a push):** The headline "the engine occasionally drops a valid push" is an inherently one-off, unlogged race that cannot be confirmed or falsified against any primary source. **What would confirm it:** reproducible run-history evidence of a valid path-matching push that produced no run (a run-number gap) from the cross-repo webgrip/infrastructure Actions history. *Note: the actionable sub-mechanics — amend→identical tree→no path match→no run; config-only change→empty matrix — ARE sound and should be the durable takeaway; downgrade the "occasional detection miss" to an anecdotal caveat, not a documented engine trait.*

---

## Confirmed & safe to enshrine

HIGH-confidence CONFIRMED items, grouped by domain (titles only). Cleared for docs/skills.

**Forgejo Actions engine (B1):**
- Composite/reusable resolution splits by call-site; data.forgejo.org incomplete mirror
- Cluster Forgejo serves actions from data.forgejo.org because DEFAULT_ACTIONS_URL is unset
- Workflow-directory precedence is first-existing-dir-wins (empty `.forgejo/workflows` lever)
- CI-created release does NOT fire a release Actions event — dispatch explicitly (add `type: string` to inputs)
- semantic-release-monorepo `outputs.version` is the full namespaced tag
- Forgejo runner pod logs show only the DinD sidecar
- KEDA warm-pool runner + activeDeadlineSeconds → false KubeJobFailed (fix shipped)

**Runner & CI speed (B2):**
- forgejo-runner is a KEDA ScaledJob, 3-container ephemeral host-mode pod
- Privileged DinD today; rootless BuildKit roadmap (ADR-0008)
- Worker-pool node shape & runner placement (pool=worker; retired fringe taint)
- Runners have NO CPU limit → never throttled; lever is requests + cold start
- Resource/scaling rightsize values shipped in 04c6151
- Dominant CI cost is emulated arm64 (QEMU) → amd64-default + gated QEMU (ADR-0036)
- forgejo-runner 12.10.2 has NO action offline mode at any layer (ADR-0035)
- buildx must stay even for amd64-only (registry cache export needs its driver)

**Dockerfile & semantic-release (B3):**
- Parameterize base registries via ARGs defaulting upstream; Forgejo→Harbor proxy paths
- Inter-image pin via GHCR-proxy path so ONE digest works in both pipelines
- Two-tree layout (frozen `.github` + adapted `.forgejo`) enforced by a parity check
- Tiered port (T1/T2/T3) of GitHub workflows to `.forgejo`
- semantic-release on Forgejo: `@saithodev/semantic-release-gitea`, env-gated on a literal flag
- "Release once, publish many" — Forgejo sole authority, GitHub pure mirror
- Pinned semantic-release toolchain; checkout@v6 broken on non-GitHub runners

**Signing / OpenBao (B4):**
- OpenBao cosign-signer JWT role must bind the Forgejo workflow_dispatch/branch claim shape

**Harbor & secrets (B5):**
- Harbor native SBOM column gated by `sbom:create` (NOT `scan:create`)
- Robot provisioner convergence PUT reusing stored full name
- Talos registry mirror is a silent no-op unless nodes can DNS-resolve Harbor (extraHostEntries → 10.0.0.27)
- Route images via transparent Talos mirror (fail-open); apply with no drain/reboot
- Harbor 2.15 proxy returns full upstream tag list → Renovate works; registryAliases keys on host only
- Charts go through Harbor by URL-rewrite; only non-bootstrap OCI; NOT fail-open
- Provision Forgejo org Actions secrets via OpenBao + CronJob; reserved prefixes (WEBGRIP_)
- Write to OpenBao as admin via OIDC (root token revoked)

**Forgejo-leading migration (B6):**
- Verify un-mirror via the `.mirror` flag, not anon `permissions.push`
- GitHub push-mirror PAT needs the workflow scope
- Converting a pull-mirror leaves Actions AND Pull-Requests units OFF; library repos keep Actions OFF
- Don't copy GitHub status_check_contexts into Forgejo branch protection
- Forgejo PAT granular scopes — `/user` 403s, org-list needs read:organization
- forgejo-sync.sh + migration API shapes; migrate webgrip/workflows first
- `gh api` prints error body to stdout on 404 — fallback must be outside `$(...)`

**Talos / etcd / Longhorn (B7):**
- `task talos:upgrade-node` built-in drain stalls on single-replica-PDB workloads — force-drain first
- Two distinct Talos node operations with different drain behavior; use the recipes
- Version pins in two files; generated clusterconfig gitignored
- etcd quorum / HA math — corrects the "go to 1 control-plane" intuition
- Capability labels are the placement contract (Cilium L2 CRDs consume node labels too)
- Pin a single-node RWO-shared app via a node-unique capability label (RWX blocked)
- Kyverno blocks all RWX PVCs cluster-wide
- Break a goharbor RWO RollingUpdate Multi-Attach deadlock by deleting the old ReplicaSet
- Convert a chart that hardcodes RollingUpdate to StatefulSet (DT api-server); VCT storageClass immutable
- All Longhorn StorageClasses now Immediate; longhorn-gitops SC deleted
- Default longhorn SC still provisions 3 replicas on a 2-storage-node cluster (deliberate deferral)
- Longhorn 1.11 ignores `defaultSettings.backupTarget` — use a BackupTarget CR
- Post-reboot Longhorn churn self-heals serially; detect rebuilds via JSON `rebuildStatus`

**Flux & observability (B8):**
- Grafana threshold rules need a top-level `expression: <input-refId>` (broke all 16 SLO rules ~3 weeks)
- Pre-flight a Grafana alert-rule shape with a throwaway MCP rule
- PromQL anti-patterns: `count()` over a boolean gauge; empty filtered set → NoData not 0 (`or vector(0)`)
- Operator-managed Grafana ServiceMonitor needs release label + operator's actual selector labels
- Two independent alert engines with no unified view
- Bootstrap Jobs/CronJobs need explicit worker pinning; etcd fragmentation double-alerted
- Live alert/SLO read surfaces, dashboard UIDs, validators (REFERENCE)
- Query per-job resource peaks without series explosion; MCP UIDs and serviceaccount

**Kyverno / hooks / worktrees (B9):**
- Kyverno enforce mechanics + test-harness allowlist hole (ADR-0033)
- Fresh worktrees lack gitignored bootstrap files; `.worktreeinclude` copies them (Claude-created only)
- Worktrees solve working-dir collisions but NOT push-to-main collisions
- Concurrent agents on unprotected main — fetch, verify survival, stage explicit paths
- Repo validate/commit conventions (lefthook, run-flux-local-test.sh)
- Per-app Flux Kustomizations live in the app namespace; `${SECRET_DOMAIN}` needs substituteFrom
- Bash/git tool gotchas (cwd reset, zsh globs, commit `--` pathspec ordering)
- roadmap-topup holds roadmap.md at 100 items via posture-counts.sh (live-verified)
- Conflict resolutions: Harbor SBOM committed; runner=docker label only; ADR-0035=scoped mirror

---

## Cross-repo (verify elsewhere)

Truth lives in **webgrip/workflows** or **webgrip/infrastructure**, not this repo — handoff, not for this repo's docs:

- **B2-3 github-runner image contents/gaps** — the Dockerfile is `webgrip/infrastructure/ops/docker/github-runner/Dockerfile`. The php/dotnet/CodeQL/node-under-externals specifics can only be re-verified there.
- **B2-10 constrictor (strangler) build-workflow chain** — the harbor-wrapper → registry-engine → composite call graph + filenames live in **webgrip/workflows**.
- **B2-12 verifyRelease cache-only build / no cache-to** — `.releaserc.js` is in **webgrip/workflows**; cache-hit speedup is ASSERTED-until-run.
- **B2-13 `@semantic-release/exec` Lodash templating** — exact `.releaserc.js` config is in **webgrip/workflows** (behavior is documented/correct).
- **B2-14 base-image pull mirroring belongs in the buildx builder's buildkitd config** — the buildx/dind builder config lives in **webgrip/workflows** (layering analysis upstream-correct; dind-ConfigMap backed out 2026-06-25).
- **B3-9 Forgejo asset-upload multipart field + GHAS/Models "dropped" comments** — verify the exact `-F attachment=@` field name against the live `.forgejo` workflow curl.
- **B4-3 `.forgejo/actions/cosign-sign-attest` internals** (registry gate, `curl -K` 0600, v2.4.3/v1.21.0 pins, `/v1/auth/forgejo/login`, `.github` keyless mirror) — verify in **webgrip/infrastructure**.
- **B9-13 `String(content).replace(backticks, ZWSP)` github-script escape** — cross-repo (infrastructure techdocs build-summary); not in this repo's `.github/`.
- **B9-14 techdocs-builder Dockerfile + plugin version pins** (`mkdocs-redirects==1.2.2`, `techdocs-core==1.5.3`, awesome-pages absence) — **webgrip/infrastructure** `ops/docker/techdocs-builder/Dockerfile`.
- **B6-3 `GH_MIRROR_TOKEN` value/scope** — token lives in `~/.config/webgrip/forgejo.env` (owner machine), not in-repo; scope must be repo + workflow.

---

## Net effect on the write plan

- **Supply-chain / signing pipeline rewrite is the biggest change.** Stop writing "GHCR is keyless OIDC/Fulcio/Rekor" anywhere — as of `fc5fdf1` (2026-06-26) webgrip GHCR is **key-signed with the same OpenBao Transit key as Harbor**. Reserve keyless+rekor.url language strictly for third-party `ghcr.io/kyverno/*`. Rewrite the stale `supply-chain-pipeline.md` and fix the dead CLI-test rule names.

- **The harbor SBOM section is mostly safe to enshrine, with two repairs.** The `sbom:create` (not `scan:create`) RBAC gotcha is fully confirmed at Harbor v2.15.1 source and is the load-bearing fact to document. But (a) drop the bogus storage metric names — use `harbor_quotas_size_bytes`/`harbor_system_volumes_bytes`; and (b) the proxy-project list must show **seven** upstreams (add `mcr → mcr.microsoft.com`), while the Talos mirror stays at six.

- **The forgejo-actions engine doc+skill must add a correctness footnote on reusable-workflow expansion.** State the `runs-on`-omission precondition for flattening (caller `if:` only fails to gate when expansion is active); qualify the `workflow_call.secrets` "benign" claim (breaks push/PR triggers on mixed-trigger files); and treat the `github.repository_owner`/`github.sha`-empty workaround as observed/version-specific. Also fix the engine-naming: the generic "(Registry)" engine is NEW in `.forgejo`; the old `.github` `-ghcr` action stays GHCR-only.

- **Add a Kyverno tlog promotion gate to the policy docs.** The three image-verify policies are Audit-only AND currently lack `rekor.ignoreTlog:true`, so they'd fail to verify a `--tlog-upload=false` signature against a real signed image. Document "do NOT flip Audit→Enforce until a real signed release verifies green AND the policies gain `rekor.ignoreTlog:true`" as the explicit gate.

- **The talos force-drain runbook addition is solidly confirmed (B7-1) and safe to write** — single-replica-PDB workloads stall the built-in upgrade drain; `kubectl drain --disable-eviction` first. Fix one inventory transcription error wherever copied: Talos v1.13.4 ships **etcd v3.6.12**, not v2.6.12.

- **The forgejo-leading skill needs a small modernization, not a rewrite.** Un-mirroring is no longer strictly UI-only (`POST .../convert`, PR #8932, backported to 15.0) — useful for bulk migration; and drop the `.profile-private` members-only claim (GitHub convention, undocumented in Forgejo).

- **In the observability docs, split the Forgejo-CI item:** keep "no native CI timing metrics → custom exporter", but DELETE "runner logs aren't in Loki" — they now are (LogQL on `namespace`/`pod`). Also tighten three precision points: Sloth MWMB doesn't "linger" (short window resets pages quickly); SBOM uploader runs Sunday 02:10 with "~160 and growing" projects; soften spegel "only HR that drifts".

- **For any harness/tooling docs:** describe `guard-destructive.sh` as regex/word-based with no `--help` exemption (not "string-match", no dedicated Longhorn rule); note ADRs are numbered at authoring/Proposed time (no "unnumbered candidate" convention); and verify the skillsmith env-var spelling (`${CLAUDE_SKILL_DIR}` vs `${CLAUDE_PLUGIN_ROOT}`) against the deployed harness before quoting it.
