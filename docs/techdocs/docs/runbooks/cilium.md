# Runbook: Cilium

Use this when `CiliumAgentDown` is firing or pod networking breaks.

## Fast triage

1) Check daemonset status

- `kubectl -n kube-system get pods -l k8s-app=cilium -o wide`

2) Inspect logs

- `kubectl -n kube-system logs ds/cilium --tail=200`

3) Check node health

- `kubectl get nodes -o wide`

## Common causes

- Node-level networking issues (NIC down, routes).
- Cilium upgrade/config drift.
- Resource pressure causing agent restarts.

## Next actions

- If multiple nodes are affected, focus on the first failing dependency: node networking → Cilium pods → service routing.
