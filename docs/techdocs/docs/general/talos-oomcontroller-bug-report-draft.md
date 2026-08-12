# Draft upstream issues — siderolabs/talos + longhorn/longhorn

> **SECOND FINDING (2026-08-12) — RESOLVED UPSTREAM, do NOT file; track the
> release instead.** The Longhorn-breaking behavior on Talos v1.13.8 is
> open-iscsi 2.1.12 (extensions bump c8d5b9d2da) **renaming** the persisted
> node-DB key `node.session.conn_reopen_log_freq` (written by 2.1.11 =
> v1.13.7) → `sess_reopen_log_freq` with no compat alias — each version
> rejects the other's `/var/lib/iscsi` records (`Unknown parameter name` +
> `config file ... invalid`, exit 7), which persist across up- AND
> downgrades. Longhorn bundles no open-iscsi (it drives the host's iscsiadm),
> so no Longhorn version is affected differently. Already reported as
> [siderolabs/extensions#1182](https://github.com/siderolabs/extensions/issues/1182)
> and [open-iscsi#540](https://github.com/open-iscsi/open-iscsi/issues/540);
> compat patch merged 2026-08-11
> ([extensions 12c4033796](https://github.com/siderolabs/extensions/commit/12c403379657fa4a4bcd101e6e7478737501e242)),
> unreleased as of 2026-08-12. Local remediation applied: fleet pinned
> v1.13.7 (talenv gate) + `/var/lib/iscsi/{nodes,send_targets}` purged on the
> two ex-v1.13.8 nodes.

## Draft upstream issue — siderolabs/talos

> Status: DRAFT, not yet filed. File at <https://github.com/siderolabs/talos/issues/new>
> after the 2026-08-11 fringe-workstation incident review.
>
> **IMPORTANT — narrow before filing (research 2026-08-11):** the kill-*storm*
> component (no cooldown on the QoS trigger clause, ~500ms kill loop) is
> [#13622](https://github.com/siderolabs/talos/issues/13622), already **fixed in
> v1.13.6** via [#13675](https://github.com/siderolabs/talos/pull/13675); we hit
> it because we run v1.13.4. What remains UNFIXED (even on main) and is worth
> filing: (a) the victim ranker walks only kubepods/podruntime/system children,
> so cgroups outside them (escaped dind, orphaned shims) generate the pressure
> but can never be victims; (b) no empty-victim / kill-effectiveness feedback —
> a cgroup can rank on page-cache with zero live processes and be "killed"
> repeatedly to no effect. Also reference
> [discussion #11853](https://github.com/siderolabs/talos/discussions/11853)
> (maintainers consider the privileged-dind escape itself out of scope).
> Related fixed history: [#12526](https://github.com/siderolabs/talos/issues/12526)
> (v1.12.0 loop, fixed via #12602).

## Title

OOMController kill-loops kubepods cgroups with an empty victim list when the
memory pressure originates outside kubepods

## Bug Report

### Description

When node memory pressure is caused by cgroups **outside** `/kubepods` (in our
case: a docker-in-docker CI daemon whose nested containers' cgroups land at the
host root, `/sys/fs/cgroup/docker/<id>`), the PSI-driven OOMController enters a
futile kill loop:

1. PSI crosses the trigger threshold (genuinely — the node had ~0.6 GiB
   available of 15.7 GiB, ~11.8 GiB anonymous memory outside kubepods).
2. The controller selects a victim cgroup from `/kubepods` — in every
   observed iteration the same burstable pod (the Cilium agent).
3. It sends SIGKILL to that cgroup and logs `victim processes: []` — the kill
   frees nothing measurable.
4. Pressure is unchanged, so it re-triggers within seconds. This continued
   for **hours** (previous occurrence of the same pattern on 2026-08-04: 43
   hours, 346 Cilium restarts; this one: 464 restarts), until the kubelet
   starved on memory and stopped posting node status → NotReady. The node
   never recovers on its own.

Two problems compound here:

- **Victim selection is blind to non-kubepods cgroups**, so the actual
  consumer is never a candidate.
- **There is no feedback/back-off**: a kill that yields an empty victim list
  and no pressure relief is retried indefinitely against the same cgroup,
  repeatedly destroying a healthy CNI agent (each death re-arms
  `node.cilium.io/agent-not-ready`, so the node also flaps schedulability).

### Expected behavior

Any of the following would break the failure mode:

- consider non-kubepods cgroups (with appropriate protections for system
  slices) when they dominate memory usage;
- back off / escalate (e.g. log loudly, stop killing) when the selected
  victim cgroup returns no processes or the kill produces no PSI improvement;
- avoid re-selecting a cgroup whose kill just produced an empty victim list.

### Logs

```text
user: warning: [2026-08-11T17:20:38Z]: [talos] Sending SIGKILL to cgroup {"component": "controller-runtime", "controller": "runtime.OOMController", "cgroup": "/sys/fs/cgroup/kubepods/burstable/podc11937f9-989d-48ba-8453-06d2baa9392b"}
user: warning: [2026-08-11T17:20:39Z]: [talos] victim processes: {"component": "controller-runtime", "controller": "runtime.OOMController", "processes": []}
user: warning: [2026-08-11T17:20:40Z]: [talos] OOM controller triggered {"component": "controller-runtime", "controller": "runtime.OOMController"}
(repeats every 1-5 s for hours; pod c11937f9… is the cilium-agent DaemonSet pod)
```

### Environment

- Talos version: v1.13.4 (server), kernel 6.18.34-talos
- Kubernetes version: v1.36.1
- Platform: bare metal, amd64, single node affected (CI worker running a
  privileged docker:dind DaemonSet)

### Reproduction sketch

On a worker node, run a privileged docker:dind pod (host cgroup namespace, the
stock image entrypoint) and start containers through it until node PSI
crosses the OOMController threshold; the nested containers' memory sits in
`/sys/fs/cgroup/docker/*`, outside kubepods. Observe the controller
SIGKILL-looping kubepods cgroups with `victim processes: []`.

### Workaround (ours)

Wrap dockerd so its `--cgroup-parent` points inside the pod container's own
cgroup (replicating the dind entrypoint's cgroup-v2 nesting dance rooted at
the container cgroup instead of the host root). The nested containers then
count against the pod's memory limit and die by ordinary cgroup OOM.
