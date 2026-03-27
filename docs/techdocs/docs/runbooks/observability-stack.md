# Runbook: Observability stack

Use this when pods are not ready / restart storms / OOMKills in the `observability` namespace.

## Fast triage

1) Identify failing components

- `kubectl -n observability get pods -o wide`
- `kubectl -n observability get deploy,sts -o wide`

2) Inspect the failing pod

- `kubectl -n observability describe pod <pod>`
- `kubectl -n observability logs <pod> -c <container> --tail=200`
- If restarting:
  - `kubectl -n observability logs <pod> -c <container> --previous --tail=200`

3) Storage and object store checks

Common failure modes for Loki/Tempo/Mimir are:

- PVC full / degraded volumes
- object store connectivity / creds
- DNS failures

If it smells like storage:

- Check PVCs:
  - `kubectl -n observability get pvc`
- Check Longhorn runbook:
  - [docs/techdocs/docs/runbooks/longhorn.md](longhorn.md)

## What to fix first

- Prefer fixing the first failing dependency (DNS → storage → network → app).
- If Mimir is unhealthy, it can cascade into Prometheus remote_write symptoms.
