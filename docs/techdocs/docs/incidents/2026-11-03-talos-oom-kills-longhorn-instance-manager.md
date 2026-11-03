# Incident 2026-11-03 — Talos OOMController kills Longhorn's instance-manager on fringe → Forgejo DB down

**Severity:** SEV2 (Forgejo, and with it Flux's git source, down in ~5-minute cycles)
**Window:** 2026-11-03 ~06:20 UTC → fix shipped the same morning
**Data loss:** none. Every volume kept two healthy replicas on worker-1 and worker-2.

## Summary

fringe-workstation ran out of memory (kernel OOM at 06:20:59 UTC, node briefly NotReady). After
that, Talos' userspace OOMController hit its PSI trigger every few minutes and SIGKILLed a pod
cgroup each time. Its default ranking scores any cgroup with a `memory.max` at 0.0, so it can
only pick pods **without a memory limit**. On fringe the largest pods without a limit were
Longhorn's runtime-created node pods (instance-manager, engine-image, csi-plugin). Killing the
instance-manager stops **every volume engine on the node** at once, so forgejo-db, grafana-db,
litellm-db, dependency-track-db and the ploeg/vikunja restore drills all fell over together,
came back, and fell over again about 4–5 minutes later.

## Evidence

- `talosctl -n 10.0.0.30 dmesg`: `OOM controller triggered` → `Sending SIGKILL to cgroup …` at
  06:49:01 and 06:53:22, matching the instance-manager pod being recreated at 06:48:53 and
  06:53:33. Between 06:14 and 06:41 the same controller killed `engine-image-ei-5ee94262-*` and
  `longhorn-csi-plugin-*` 25 times (lifetime restarts: 455 and 2584).
- Pod UIDs of the victim cgroups resolved to longhorn-system pods. `forgejo-dind` (2.3 GiB) was
  never chosen: it has a 6Gi limit.
- Longhorn volumes for forgejo-db went `faulted` → `detaching` → reattached on each cycle, with
  replicas on worker-1 and worker-2 staying `stopped`/healthy.
- Collateral: the ploeg restore-drill WAL volume left a stale iSCSI session on the host
  ("failed to logout target … stale namespace directory"), and ext4 aborted the journal on one
  device. Both were symptoms of engines being killed mid-I/O, not the cause.

## Root cause

The [2026-06-09 Longhorn OOM cascade](2026-06-09-longhorn-oom-cascade.md) gave `longhorn-manager`
Guaranteed QoS through a HelmRelease postRenderer. The pods Longhorn creates at runtime cannot be
reached that way, so a `LimitRange` gave them default **requests only**. The reasoning was "no
OOM-kill ceiling on storage components". Under Talos' OOMController ranking
(`memory_max.hasValue() ? 0.0 : …`, see [RFC: CI isolation on Talos](../rfc/rfc-ci-isolation-talos.md))
that same choice makes them the preferred victims. It is the same mechanism that kill-looped cilium
in August and the CNPG tier in [July](2026-07-11-talos-oom-db-tier.md).

## Fix

`kubernetes/apps/longhorn-system/longhorn/app/limitrange.yaml` now also sets a **default memory
limit of 4Gi** for every longhorn-system container that declares none. With every container
limited, kubelet sets a pod-level `memory.max`, and the OOMController ranks the pod 0.0, so it is
never selected. 4Gi is 2.3× the busiest instance-manager observed (worker-2, 1.7 GiB), so the
limit exists to opt out of the ranker, not to constrain. The LimitRange applies at pod creation,
so each node's pods pick it up on their next recreation.

Verify on fringe after its instance-manager is next recreated:

```sh
kubectl -n longhorn-system get pod -l longhorn.io/component=instance-manager \
  --field-selector spec.nodeName=fringe-workstation \
  -o jsonpath='{.items[*].spec.containers[*].resources.limits.memory}'
talosctl -n 10.0.0.30 dmesg | grep -E 'OOM controller triggered|Sending SIGKILL'
```

The first command should print `4Gi`. The SIGKILL lines that follow should resolve to pods
outside longhorn-system.

## Open items (pressure, not ranking)

The fix chooses a better victim but does not remove the pressure on fringe:

- **Leaked Lighthouse CI containers** (`lhci-*`, static-site-ci-runner) were alive on fringe's
  shared dind, two of them 6 h old. The generic reaper only removes containers older than 12 h.
- **`/dev/shm/forgejo-ci-shared` held 1.5 GiB** of node RAM.
- fringe memory requests sit at 84% of allocatable and limits at 283%. RAM is still the real lever.
