# Runbook: Apps (baseline)

Use this when a random workload is down (CrashLoopBackOff, `Unavailable`, readiness probe failures) or a PVC is close to full.

## Fast triage

1) Find what’s unhealthy

- `kubectl get pods -A -o wide`
- `kubectl get deploy,sts,ds -A -o wide | egrep -v ' 1/1 | 2/2 | 3/3 '`

2) Inspect one failing pod

- `kubectl -n <ns> describe pod <pod>`
- `kubectl -n <ns> logs <pod> -c <container> --tail=200`
- If it’s crashlooping:
  - `kubectl -n <ns> logs <pod> -c <container> --previous --tail=200`

3) Check events (often shows scheduling/image/PVC problems)

- `kubectl -n <ns> get events --sort-by=.lastTimestamp | tail -n 50`

## PVC pressure

- List PVCs:
  - `kubectl -n <ns> get pvc`
- If using Longhorn, confirm volume health and replicas in the Longhorn UI.

## Common causes

- Bad config/secret (missing env var, invalid config).
- Image pull errors.
- Node pressure (memory/disk) evicting pods.
- Storage issues (unbound PVC, degraded volume).
