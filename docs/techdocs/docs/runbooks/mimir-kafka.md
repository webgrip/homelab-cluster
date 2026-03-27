# Runbook: Mimir Kafka

Use this when Kafka in `observability` is crashlooping or Kafka PVC usage alerts fire.

## Fast triage

- `kubectl -n observability get pods -l app.kubernetes.io/name=kafka -o wide`
- `kubectl -n observability logs -c kafka <pod> --tail=200`
- If restarting:
  - `kubectl -n observability logs -c kafka <pod> --previous --tail=200`

## Check PVC health

- `kubectl -n observability get pvc`
- Confirm the underlying Longhorn volume is healthy.

## Shrink Kafka PVC (delete/recreate)

Kubernetes does **not** support shrinking an existing PVC. To shrink (for example) 40Gi → 10Gi you must delete the PVC and let it be recreated.

This is disruptive and will wipe the embedded Kafka data.

Workflow (GitOps-first):

- Update the HelmRelease values in Git so `values.kafka.persistence.size` is the new desired size.
- Temporarily suspend reconciliation so Flux/Helm does not race your manual deletes:
  - `flux suspend helmrelease mimir-distributed -n observability`
  - or:
    - `kubectl -n observability patch helmrelease mimir-distributed --type=merge -p '{"spec":{"suspend":true}}'`

Then perform the PVC delete/recreate steps appropriate to the chart/controller.

When stable, re-enable reconciliation:

- `flux resume helmrelease mimir-distributed -n observability`
