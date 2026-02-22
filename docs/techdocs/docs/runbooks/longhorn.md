# Runbook: Longhorn

Use this when Longhorn volumes are degraded/faulted or storage-related alerts fire.

## Fast triage

1) Check Longhorn system pods

- `kubectl -n longhorn-system get pods -o wide`

2) Check PVCs for impacted apps

- `kubectl -n <ns> get pvc`

3) Use Longhorn UI

- Look for:
  - replica rebuild loops
  - failed disks
  - node pressure

## Common causes

- Node disk pressure or filesystem issues.
- Replica scheduling constraints.
- Network flaps between nodes.

## Notes

- If an app is crashlooping due to storage I/O timeouts, stabilize Longhorn first.
