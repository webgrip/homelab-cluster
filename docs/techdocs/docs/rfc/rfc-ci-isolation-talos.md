# RFC: CI isolation on Talos — life after the shared privileged dind

- Status: **Proposed**
- Date: 2026-08-11
- Trigger: fringe-workstation NotReady incident 2026-08-11 (second occurrence of
  the 2026-08-04 class). Forensics: a **12-day-old orphaned buildx builder**
  (`buildx_buildkit_builder-*`, `moby/buildkit:buildx-stable-1`) on the shared
  dind daemon, its memory in host-root cgroups outside kubepods, ratcheting to
  ~12Gi until Talos's OOMController kill-looped cilium (464 restarts, `victim
  processes: []`) and the kubelet starved.
- Related: ADR-0026 (rootless CI builds — proposed), ADR-0027 (buildx
  docker-container driver for registry cache), ADR-0049 (OOMController exit-137
  signature), ADR-0050 (e2e status checks), `rfc-ci-pipeline-performance.md`,
  `general/talos-oomcontroller-bug-report-draft.md`.

## Verdict

**A shared privileged docker:dind daemon on Talos is an unsupported pattern,
and Sidero has said so explicitly** ([talos discussion 11853](https://github.com/siderolabs/talos/discussions/11853)
— "As you run it
as privileged, it can 'escape' cgroup tree... nothing Talos can do"). The
escape is not a bug anywhere: **KEP-2254 states privileged pods keep the host
cgroup namespace by design**, so the stock dind entrypoint's cgroup-v2 nesting
dance lands nested containers at the host cgroup root — outside kubepods,
invisible to kubelet eviction, cAdvisor, and Talos's OOMController (whose
victim walk is compile-time limited to `kubepods/*`, `podruntime`, `system`).

Nobody in the ecosystem runs our shape. Mainstream dind is a **per-job
sidecar** (ARC `dind` mode, GitLab dind service, and the official act_runner
example) — same cgroup hole, but daemon lifetime and state scoped to one job.
Builds are moving off dind entirely (kaniko archived June 2025; GitLab, CERN
and Buildkite all point at rootless BuildKit). The sanctioned long-term shape
for nested runtimes is **unprivileged pods + user namespaces** (`hostUsers:
false`, GA in k8s 1.36) — non-privileged pods on cgroup v2 get a *private*
cgroup namespace, which deletes this incident class outright.

We do not need to leave the pattern overnight: the 2026-08-11 containment
wrapper (dockerd `--cgroup-parent` rooted in the pod's own cgroup, commit
`76671383`) already restores the property that matters — **bounded memory the
kubelet can see** — plus a generic 12h orphan reaper and the
`NodeMemoryOutsideKubepods` invariant alert. This RFC stages the rest.

## What the incident actually was (mechanism chain)

1. Cross-repo build workflows used buildx's `docker-container` driver on the
   shared dind daemon; one builder container leaked on ~Jul 30 (job killed →
   no cleanup; the KinD-only reaper was name-blind to it).
2. Privileged pod ⇒ host cgroupns (KEP-2254) ⇒ the builder's cgroup lived at
   host-root `/docker/<id>` with `memory.max = max`: 7.5→12Gi over 12 days on
   a 15.7Gi node while every pod's working set summed to ~1.6Gi.
3. PSI crossed the OOMController trigger. Its ranker walks only
   kubepods/podruntime/system children; the real consumer was structurally
   invisible, so it killed the highest-ranked *visible* burstable pod cgroup —
   cilium's — every ~500ms. **v1.13.4's QoS trigger clause has no cooldown**;
   this exact storm is [talos#13622](https://github.com/siderolabs/talos/issues/13622),
   **fixed in v1.13.6** (5s cooldown, [#13675](https://github.com/siderolabs/talos/pull/13675)),
   with podruntime min/max protection added in v1.13.7.
4. Cilium was killable despite its 1Gi container limit because the ranker
   scores **pod-level** cgroups: the cilium pod's `memory.max` is unset
   (chart init/extra containers carry no limits, so kubelet cannot set a
   pod-level max). `memory_max.hasValue() ⇒ rank 0.0 ⇒ never killed`
   ([#13437](https://github.com/siderolabs/talos/pull/13437), already in
   v1.13.4) — the exemption lever exists, we just don't qualify for it.
5. Kills freed nothing (`victim processes: []` — the cgroup often scored on
   page-cache with no live procs), pressure persisted, kubelet starved →
   NotReady. Pod restarts cannot free host-root cgroups; only a reboot can.

## What CI actually needs (from the repo inventory)

The binding constraint is **not image builds** — it is the Kyverno Chainsaw
e2e check (1 of the 4 required `e2e /` PR contexts): `kind create cluster` on
the daemon, `docker exec` into the KinD control plane (the kubeconfig is
unusable across netns), and `docker run --network host`. Three of four e2e
checks use plain `docker run -v` with the `/mnt/ci-shared` bind-mount
contract. `docker build`/buildx runs only in *other* repos' workflows —
already targeted at the dedicated `forgejo-buildkitd` (with per-job
docker-container builders on dind as the fallback, which is what leaked).
No compose in CI. Full inventory: the 10-requirement list in the 2026-08-11
research notes; the warm per-node image store is the daemon's raison d'être
(cold pulls cost 4-10min/job on this disk).

## Options considered (ranked for this homelab)

| Option | Contains memory? | Verdict |
| --- | --- | --- |
| **Hardened shared dind** (containment wrapper + reaper + alert, shipped) | Yes — pod cgroup, fail-open edge | **Keep short-term.** Add `podPidsLimit`; retire LAN hostPort. |
| **Talos v1.13.8 upgrade** | n/a — bounds the *blast radius* (storm→rate-limited) | **Do now.** worker-2 already runs v1.13.7 happily. |
| **Kata RuntimeClass** (official Talos extension, Cloud Hypervisor) for KinD/e2e jobs | Hard — VM boundary; overhead ~130-160Mi/pod | **Adopt narrowly** for the chainsaw job. Needs a block-volume docker store (overlayfs can't stack on virtiofs) — the warm-cache hostPath doesn't port; acceptable for the e2e job only. |
| **Rootless dind + `hostUsers: false`** | Yes — private cgroupns by construction | Right destination, wrong year for KinD: kind-rootless delegation inside a pod is DIY, and [moby#52268](https://github.com/moby/moby/issues/52268) breaks non-root nested netns today. **Re-evaluate** on that issue + KEP-5474 (`writable_cgroups`). |
| Per-job dind sidecar (ecosystem default) | No better than shared (same cgroup hole) but job-scoped state | Fallback shape if the shared daemon bites again; costs the warm image store. |
| KubeVirt CI VM | Hard | Overkill: ~1Gi+ permanent tax + static VM reservation on 15.7Gi nodes; no Forgejo-native runner wiring. |
| Sysbox | (would be ideal) | **Disqualified on Talos** — Ubuntu-only host installer, no system extension; EE dead (archived 2025-08). |
| Dedicated non-k8s CI host | Absolute (physics) | Violates GitOps-first; the 2375 exposure gets worse off-cluster. Last resort. |

## Staged plan (each step independently shippable & reversible)

1. **Done (2026-08-11, `76671383`):** cgroup containment wrapper, generic 12h
   reaper, `NodeMemoryOutsideKubepods` alert (replay-verified over the
   incident window). Verify containment after the fringe reboot:
   `docker -H tcp://10.0.0.23:2375 run --rm alpine cat /proc/self/cgroup`
   must show a `/kubepods/.../docker/...` path.
2. **Talos v1.13.4 → v1.13.8** on all nodes (talos skill / `just talos-*`):
   picks up the #13675 storm cooldown + v1.13.7 podruntime reservations.
   Upgrade does not make escaped memory visible — it makes the failure slow
   and survivable instead of a 500ms kill-loop.
3. **Qualify cilium for the OOMController zero-rank exemption**: set memory
   limits on every container in the cilium pod (chart `initResources` etc.)
   so kubelet sets pod-level `memory.max` ⇒ rank 0.0 ⇒ never selected.
   Verify with `talosctl get oomactions` staying empty for cilium during the
   next pressure event, and pod cgroup `memory.max` ≠ `max`.
4. **`podPidsLimit`** via kubelet `extraConfig` — with nested containers now
   inside the pod cgroup, the pids controller finally covers CI too (closes
   the fork-bomb residual).
5. **Retire the LAN-exposed hostPort 2375** (staged migration already in the
   manifest; the Service path has been primary since 2026-07-27).
6. **Kill the leaker class at the source**: finish ADR-0026's step 2 — move
   the remaining cross-repo buildx flows to `forgejo-buildkitd` (remote
   driver) and *remove* the docker-container-on-dind fallback, so no buildx
   builder containers land on the shared daemon at all.
7. **Kata RuntimeClass for the chainsaw job** (kata extension via talconfig,
   `runtimeClassName: kata` on a dedicated per-job dind for KinD): VM wall
   around the one workload class that has now killed a node twice.
8. **Upstream**: file the refined Talos issue — not the storm (#13622, fixed)
   but the two remaining gaps: (a) ranker blind to non-kubepods cgroups that
   generate the pressure, (b) no empty-victim / kill-effectiveness feedback.
   Draft: `general/talos-oomcontroller-bug-report-draft.md` (update it to
   acknowledge v1.13.6 before filing).

## Execution log — 2026-08-12 (wave 1 + Talos rollout)

Steps 1-5 executed. What the rollout itself taught:

- **v1.13.8 is Longhorn-hostile — the fleet target became v1.13.7** (see
  `talos/talenv.yaml` for the gate). Root cause (research-corrected):
  open-iscsi 2.1.12 (v1.13.8's iscsi-tools) renamed the persisted node-DB key
  `conn_reopen_log_freq`→`sess_reopen_log_freq` with no compat alias, so each
  version rejects records the other wrote ("config file invalid", exit 7) and
  every engine op fault-loops; `/var/lib/iscsi` persists across up- and
  downgrades, so affected nodes also need a DB purge. Longhorn bundles no
  open-iscsi — no Longhorn version differs. Upstream
  [extensions#1182](https://github.com/siderolabs/extensions/issues/1182);
  compat patch merged 2026-08-11, unreleased. Reproduced on fringe AND soyo-1;
  v1.13.7 carries both OOMController fixes this RFC wanted, so nothing lost.
- **Every kyverno controller was a drain-blocker**: chart PDBs pin
  `minAvailable: 1` while cleanup/background/reports controllers shipped 1
  replica — unevictable forever. All bumped to 2 (`e536a84d`, `3ba5c868`).
- **Single-replica volumes made worker-1 undrainable**: Garage's
  `longhorn-single` volumes under the default `block-if-contains-last-replica`
  policy block even on stopped replicas. `nodeDrainPolicy:
  allow-if-replica-is-stopped` (`41e5f503`) keeps in-use protection but lets
  quiescent data release the node.
- **cache-server pinned to the storage workers** (`67df77c6`) — its RWO engine
  had blocked three consecutive control-plane drains via instance-manager PDBs.
- Verified end-state: all 6 nodes v1.13.7, `podPidsLimit: 4096` live
  everywhere, cilium pod-level `memory.max` = 1Gi (OOMController rank 0),
  dind containment proven on-host (`/kubepods/.../docker/buildkit`, no
  host-root `/docker`), fringe `oomactions` ledger empty, outside-kubepods
  memory back to baseline.
- Cleanups completed same day: pyroscope removed outright (owner decision;
  its volume was the drain-blocker); both ex-v1.13.8 nodes' iSCSI DBs purged;
  **worker IP renumber finished live** — the old addresses were META-partition
  install-time snapshots (key 0x0a), not DHCP; `talosctl meta delete 0x0a`
  per worker flipped kubelet to .30/.31/.32 with zero reboots.

## Re-evaluation triggers

- [moby#52268](https://github.com/moby/moby/issues/52268) closes **and** kind
  documents rootless-in-pod → revisit rootless dind + `hostUsers: false` as
  the end-state (deletes the privileged daemon entirely).
- containerd ships KEP-5474 `writable_cgroups` on a Talos release → same.
- Forgejo's native Kubernetes runner backend
  ([forgejo discussions#66](https://codeberg.org/forgejo/discussions/issues/66))
  graduates from PoC → per-job pods replace the daemon for `container:` jobs.
- `NodeMemoryOutsideKubepods` fires again post-containment → the wrapper's
  fail-open path triggered; escalate to step 7 regardless of schedule.
