Thread Digest: Node-taxonomy migration finish (authentik/harbor), roadmap + skillsmith pass
One-line summary: Completed the last ~5% of a Talos/Longhorn migration that moved all apps + storage off the RAM-tight soyo control-planes, then re-inventoried the roadmap and audited two skills under the skillsmith standard.
Approx date / status: 2026-06-21/22 — done (one owner handoff outstanding).

Items
[GOTCHA] Kyverno blocks all RWX PVCs cluster-wide
Type: GOTCHA
Verification: [VERIFIED]
What: Creating any ReadWriteMany PVC is denied at admission by Kyverno policy storage-cnpg-governance/disallow-rwx-pvcs (also enforces require-approved-pvc-storageclass). RWX/NFS shared volumes are not available unless explicitly allowlisted. Multi-pod-shared-volume apps must therefore stay single-node, not use RWX. The denial happens at dry-run/admission, so a Flux Kustomization referencing an RWX PVC goes ReconciliationFailed without disrupting the running app.
Why it matters: Rules out RWX as the "share a volume across nodes for HA" solution; forced the capability-label single-node pin below.
Snippet: admission webhook "validate.kyverno.svc-fail" denied... disallow-rwx-pvcs: ReadWriteMany PVCs are not allowed unless this policy is adjusted with an explicit allowlist.
Suggested home: existing-skill (longhorn / kyverno-policy)
[PROCEDURE] Pin a single-node RWO-shared app via a node-unique capability label
Type: PROCEDURE
Verification: [VERIFIED]
What: When several pods share one RWO volume (cannot spread across nodes) and RWX is blocked, pin to a single node using a capability label that resolves to exactly one node — never a hostname or legacy label. authentik (2 server + 1 worker share /data media) → node.webgrip.io/cpu: high (fringe is the only high-CPU node), set as both nodeSelector and the hard nodeAffinity. Pods stay co-located, the RWO volume attaches cleanly, placement still goes through the taxonomy. Node-level HA later requires moving the shared data off RWO first (e.g. media → S3).
Why it matters: Removes a legacy-label dependency without a risky move and without RWX; keeps an app exactly where it is.
Snippet: kubernetes/apps/authentik/app/helmrelease.yaml (global nodeSelector: {node.webgrip.io/cpu: high} + matching nodeAffinity matchExpressions)
Suggested home: existing-skill (workload-placement)
[PROCEDURE] Break a goharbor RWO RollingUpdate Multi-Attach deadlock by deleting the old ReplicaSet
Type: PROCEDURE
Verification: [VERIFIED]
What: The goharbor chart hardcodes RollingUpdate (renders both strategy blocks, so Recreate via values is impossible). Pinning a single-replica RWO Deployment to move it nodes deadlocks: the old pod holds the volume, the new pinned pod sits ContainerCreating (Multi-Attach error). Deleting just the old pod isn't enough — the old ReplicaSet recreates it. Fix: delete the old ReplicaSet (kubectl delete rs <old-rs>); the Deployment won't recreate a superseded revision, the volume frees, the new pod attaches, and the HR upgrade goes UpgradeSucceeded. Must beat the HR timeout (20m for harbor).
Why it matters: Moved harbor registry+jobservice off soyo-3 (the last soyo app pods) without rolling back the whole release.
Snippet: mise exec -- kubectl delete rs harbor-jobservice-<hash> -n harbor --wait=false
Suggested home: existing-skill (workload-placement)
[GOTCHA] helm-controller cache-sync rollback is driven by a loaded control-plane API
Type: GOTCHA
Verification: [ASSERTED]
What: RWO-move/postRenderer HR upgrades had failed with failed to wait for object to sync in-cache after patching: context deadline exceeded → remediateLastFailure rolling the whole release back in a loop. After the soyo control-planes were emptied of apps (idle API), the same harbor move succeeded with no rollback. Hypothesis (fit the evidence, not proven causation): the cache-sync timeout was caused by the slow/loaded soyo apiserver; an idle control-plane lets the patch sync in time.
Why it matters: Operations that previously "couldn't be done via GitOps" may become safe once the control-plane is unloaded — retiming a move can avoid a refactor.
Snippet: verify outcome: kubectl get hr <app> -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}' → want UpgradeSucceeded, not RollbackSucceeded
Suggested home: existing-skill (workload-placement)
[FACT] dependency-track api-server is now a StatefulSet (not Recreate-via-postRenderer)
Type: FACT
Verification: [VERIFIED]
What: DT's api-server was converted to deploymentType: StatefulSet with native nodeSelector and no spec.postRenderers (an ordered STS recreate frees the RWO volume, sidestepping the RollingUpdate Multi-Attach deadlock). Older skill docs claiming "DT uses strategy: Recreate via its postRenderer" and citing DT as the postRenderer-Exception example were stale and were corrected.
Why it matters: Converting to a StatefulSet is a clean fix when a chart hardcodes RollingUpdate and you can't set Recreate.
Snippet: kubernetes/apps/security/dependency-track/app/helmrelease.yaml → apiServer.deploymentType: StatefulSet
Suggested home: existing-skill (workload-placement)
[FACT] All Longhorn StorageClasses are now Immediate; the longhorn-gitops SC was deleted
Type: FACT
Verification: [VERIFIED]
What: Every Longhorn SC is volumeBindingMode: Immediate now (longhorn, longhorn-general, longhorn-cold, longhorn-rwx, longhorn-snapshot). WFFC was eliminated because, with dataLocality: disabled, Longhorn volumes are network-attached so WFFC's PV-node-locking is pure downside (it permanently excluded the later-added worker-1). The longhorn-gitops SC (soyo-replica DR design) was retired/deleted — soyos stay 100% Longhorn-free; gitops DR is external-Garage-S3 backups + a GitHub fallback Flux source instead of a soyo replica. Legacy WFFC-era PVs keep their baked nodeAffinity until recreated.
Why it matters: Stateful apps can now be pinned to pool=worker freely; the storageclass Flux ks uses force: true so the immutable binding-mode change recreates the SC.
Snippet: check a PV is unlocked: kubectl get pv <pv> -o jsonpath='{.spec.nodeAffinity}' (empty = free) · dir: kubernetes/apps/longhorn-system/longhorn/storageclass/ (only cold,general,rwx,snapshot,kustomization remain)
Suggested home: existing-skill (longhorn)
[FACT] Longhorn 1.11 ignores defaultSettings.backupTarget — use a BackupTarget CR
Type: FACT
Verification: [VERIFIED] (target shows available=true)
What: Setting backupTarget/backupTargetCredentialSecret in the HelmRelease defaultSettings is silently ignored in Longhorn 1.11 (deprecated). The working mechanism is a BackupTarget CR named default. Creds come from the longhorn-backup-s3 ExternalSecret (OpenBao s3/cnpg-backup, mapped to AWS_*). A gitops-backup RecurringJob (cron 0 2 * * *) backs up volumes labeled recurring-job-group.longhorn.io/gitops-backup=enabled (forgejo-data, gitea-mirror).
Why it matters: The obvious config knob doesn't work; the CR does.
Snippet: kubernetes/apps/longhorn-system/longhorn/app/{backuptarget,backup-s3.externalsecret,recurringjob}.yaml · kubectl get backuptarget default -n longhorn-system -o jsonpath='available={.status.available}'
Suggested home: existing-skill (longhorn)
[GOTCHA] cilium/networks.yaml uses node labels for L2 announcement (real placement dependency)
Type: GOTCHA
Verification: [VERIFIED]
What: kubernetes/apps/kube-system/cilium/app/networks.yaml contains a CiliumL2AnnouncementPolicy (l2-policy-zomboid) whose nodeSelector.matchLabels selected nodegroup: fringe. This is a real dependency on a node label — dropping the label would break LB-IP announcement, not just "network config." Swapped to node.webgrip.io/pool: worker (cilium L2-elects one worker) before retiring the legacy labels.
Why it matters: Before retiring any node label, grep ALL consumers including Cilium CRDs — not just app nodeSelectors.
Snippet: grep -rn "nodegroup\|workload-tier" kubernetes/apps/
Suggested home: existing-skill (workload-placement / talos)
[GOTCHA] skillsmith SKILL.md self-triggered the dynamic shell-injection at load time
Type: GOTCHA
Verification: [VERIFIED]
What: The Claude Code skill loader executes the bang-backtick dynamic-injection pattern found in a SKILL.md body at load time. skillsmith/SKILL.md documented that very syntax using the live token, so invoking /skillsmith ran the literal example as a shell command → zsh: command not found: cmd, blocking the skill twice. Only SKILL.md is scanned for injection; sibling files (reference.md) are not. Fix: never write the literal bang-backtick token in a SKILL.md body — name the feature and put the literal syntax in reference.md.
Why it matters: Any skill that documents the injection syntax in its own body will fail to load; this is a repo-wide constraint.
Snippet: error: Shell command failed for pattern "!cmd": zsh: command not found: cmd
Suggested home: existing-skill (skillsmith — add as a Never)
[FACT] Skill loader substitutes ${CLAUDE_SKILL_DIR} and $ARGUMENTS into SKILL.md at load
Type: FACT
Verification: [VERIFIED]
What: When a skill loads, ${CLAUDE_SKILL_DIR} expands to the absolute skill path and $ARGUMENTS expands to the invocation args (empty if none) — observed in the loaded skill text. The skill command name derives from the directory name, not the frontmatter name:.
Why it matters: Documenting these tokens literally in a body causes them to be substituted/altered in-context.
Snippet: none
Suggested home: existing-skill (skillsmith)
[PREFERENCE] Skills must be token-conscious — only date incident-derived rules
Type: PREFERENCE
Verification: [VERIFIED] (explicit user feedback)
What: Do not stamp current-state facts with dates ("shipped 2026-06-21", "flipped 2026-06-20/21") in skill bodies — a skill body stays in context all session, so every line is recurring token cost and a ship-date gives the model nothing to act on. Only date a rule when it links an incident doc (e.g. the 2026-06-09/2026-06-18 Longhorn incident entries), where "look at what happened then" is the signal. State present-state in present tense.
Why it matters: User explicitly pushed back ("not adding random ass dates in the skills"); this is the skillsmith house standard.
Snippet: none
Suggested home: existing-skill (skillsmith) / CLAUDE.md
[PROCEDURE] roadmap-topup maintains roadmap.md at exactly 100 items via posture-counts.sh
Type: PROCEDURE
Verification: [VERIFIED]
What: docs/techdocs/docs/general/roadmap.md is a living backlog held at exactly 100 open items, maintained by the roadmap-topup skill. Capture ground truth with ./scripts/posture-counts.sh (verified hardening counts: PDB/NetworkPolicy/CiliumNetworkPolicy/ResourceQuota/SecurityPolicy file counts + Kyverno Audit-vs-Enforce split + namespaces-with-a-NetworkPolicy list). Move shipped work to the Done log, reframe partials, add new findings to hold at 100. Verify count: grep -cE "^[0-9]+\. " docs/techdocs/docs/general/roadmap.md.
Why it matters: Reusable inventory workflow; posture-counts.sh is the authoritative hardening snapshot.
Snippet: current posture (2026-06-21): PDB 2 · NetworkPolicy 17 across 11 app ns · CiliumNetworkPolicy 1 · ResourceQuota 4 · SecurityPolicy 0 · Kyverno 11 Audit / 6 Enforce
Suggested home: existing-skill (roadmap-topup)
[REFERENCE] Verified post-migration cluster state + audit commands
Type: REFERENCE
Verification: [VERIFIED]
What: After the migration: 0 Longhorn replicas on any soyo (42 on fringe + 42 on worker-1); 0 app pods on soyos; control-plane memory dropped from 80–83% to 65–73% (soyo-1 highest at 73%, the residual being control-plane + BestEffort-DaemonSet overhead, not apps); fringe 48%, worker-1 45%; both ingress gateways Programmed=True.
Why it matters: Confirms etcd-protection objective met; residual soyo RAM is structural to 12 GiB nodes.
Snippet: soyo replica count: kubectl get replicas.longhorn.io -n longhorn-system -o json | jq '[.items[]|select((.spec.nodeID|startswith("soyo")) and .status.currentState=="running")]|length'
Suggested home: doc (runbooks/node-taxonomy-migration-status.md)
[REFERENCE] Talos label-drop handoff commands (MODE=no-reboot)
Type: REFERENCE
Verification: [ASSERTED] (commands given to owner; not executed in-thread)
What: Removing the now-unused nodegroup/workload-tier labels from the live nodes requires a per-node Talos apply. Claimed etcd-safe because it's a label-only change that applies live without reboot. (Note: the talos skill warns "never bare apply-node" / prefer apply-node-safe with drain for config that reboots — the no-reboot label case is the stated exception.)
Why it matters: The last outstanding handoff of the migration (roadmap #34).
Snippet:

mise exec -- task talos:apply-node IP=10.0.0.24 HOSTNAME=worker-1 MODE=no-reboot
mise exec -- task talos:apply-node IP=10.0.0.23 HOSTNAME=fringe-workstation MODE=no-reboot
for ip in 10.0.0.20 10.0.0.21 10.0.0.22; do mise exec -- task talos:apply-node IP=$ip MODE=no-reboot; done
Suggested home: doc / memory
[REFERENCE] Node IPs / roles (homelab)
Type: REFERENCE
Verification: [VERIFIED]
What: soyo-1 10.0.0.20, soyo-2 10.0.0.21, soyo-3 10.0.0.22 (control-plane/etcd, 12 GiB, single SSD shared with Longhorn — soyo-3 address by IP, hostname flaky); fringe-workstation 10.0.0.23 (worker, high-CPU = only cpu=high node, 16 GiB + 1 TB HDD); worker-1 10.0.0.24 (worker, high-RAM). Garage S3 external host 10.0.0.110:3900.
Why it matters: Capability-label resolution (cpu=high → fringe) and the external-S3 SPOF depend on these.
Snippet: none
Suggested home: existing-skill (talos) / doc
[DECISION] gitops-critical apps pinned to workers; DR via external-S3 + GitHub fallback (not a soyo replica)
Type: DECISION
Verification: [VERIFIED] (implemented)
What: The originally-planned soyo Longhorn replica for forgejo/openbao was dropped as over-engineered: Garage S3 is external (10.0.0.110) so backups already survive a both-worker outage, and forgejo's eventual gitops-criticality is better handled by a GitHub fallback Flux GitRepository than by a soyo disk. forgejo/openbao/gitea-mirror are now pinned to pool=worker like any app.
Why it matters: Keeps soyos 100% Longhorn-free; decouples forgejo resilience from forgejo storage.
Snippet: none
Suggested home: doc (ADR-0026)
[PREFERENCE] Use the actual skill, not a manual re-implementation of its rules
Type: PREFERENCE
Verification: [VERIFIED] (explicit)
What: When the user asks to use a named skill (e.g. "do it with skillsmith"), invoke the Skill — don't just read its SKILL.md and apply the rules by hand. If the skill won't load, fix the blocker and invoke it. (Also reinforced: single-source-of-truth across skills — a fact lives in one canonical skill; others give a one-liner + "see the X skill". The RWO-deadlock duplication across two workload-placement sections was consolidated as a result.)
Why it matters: The user values the skill being run, and skillsmith's audit caught real issues (the loader bug, stale DT refs, a duplication) that the manual pass missed.
Snippet: none
Suggested home: CLAUDE.md / memory
[REFERENCE] Commit/push conventions reinforced in this thread
Type: REFERENCE
Verification: [VERIFIED]
What: Commit via mise so lefthook's zizmor resolves: mise exec -- git -c commit.gpgsign=false commit. Work trunk-based directly on main. Because concurrent agents share main, stage only your own files (never git add -A), and before pushing do git fetch origin main + verify git rev-list --count HEAD..origin/main == 0. Co-author trailer: Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>.
Why it matters: Avoids clobbering parallel work and lefthook failures.
Snippet: git fetch -q origin main && [ "$(git rev-list --count HEAD..origin/main)" = "0" ] && git push -q origin main && echo PUSHED || echo DIVERGED
Suggested home: CLAUDE.md
Open questions / unfinished
Longhorn volume backups never actually ran — BackupTarget is Available and the gitops-backup RecurringJob + labels are in place, but kubectl get backups.longhorn.io -n longhorn-system returned zero. First scheduled run is 02:00; restore-from-Garage is unproven (roadmap #58). [OPEN]
1 degraded Longhorn volume pvc-6f3514eb-... attached on fringe (likely a post-move rebuild; not investigated). The 5 "unknown" volumes are just detached/stopped-app volumes (normal). [OPEN]
Talos label-drop apply-node not yet run on the live nodes (roadmap #34). [OPEN]
authentik node-level HA still requires moving media → Garage S3 (AUTHENTIK_STORAGE__MEDIA__S3) then switching cpu=high → pool=worker (roadmap #47). [OPEN]
Garage S3 is a single external host — SPOF for ALL backups (CNPG/Longhorn/OpenBao) and CNPG WAL archiving (roadmap #63). [OPEN]
Explicit preferences/feedback I gave
Be token-conscious in skills; don't add ship-dates — only incident-linked dates belong in a skill body.
Actually invoke the requested skill (skillsmith), don't just apply its rules manually.
"Be careful" / "I want it to be completely clean" — wanted soyos 100% app-free and the migration fully closed out, with safety emphasis on the SSO (authentik).
Wanted follow-ups captured in the roadmap and learnings smithed into skills (not left in the thread).
