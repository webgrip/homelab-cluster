# Longhorn reference — health one-liners, runbooks, incidents

Contents: [Read-only health](#read-only-health) · [Runbooks](#runbooks) · [Incidents](#incidents)

## Read-only health

```bash
# robustness spread + active rebuilds (rebuilding==0 while degraded>0 = WEDGED)
mise exec -- kubectl get volumes.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '[.items[].status.robustness]|group_by(.)|map({(.[0]):length})|add'
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '[.items[]|select(.status.currentState=="rebuilding")]|length'
# replica spread per node
mise exec -- kubectl get replicas.longhorn.io -n longhorn-system -o json | mise exec -- jq -r '[.items[]|select(.status.currentState=="running")|.spec.nodeID]|group_by(.)|map({(.[0]):length})|add'
```

## Runbooks

[longhorn-rebuild-wedge](docs/techdocs/docs/runbooks/longhorn-rebuild-wedge.md) ·
[longhorn-im-cpu-converge](docs/techdocs/docs/runbooks/longhorn-im-cpu-converge.md)
(capacity/taxonomy history → [ADR-0008](docs/techdocs/docs/adr/adr-0008-confine-longhorn-to-workers.md)–[0029](docs/techdocs/docs/adr/adr-0010-storageclass-consolidation.md) status logs)

## Incidents

[06-09 OOM cascade](docs/techdocs/docs/incidents/2026-06-09-longhorn-oom-cascade.md) ·
[06-18 IM-cpu detonation](docs/techdocs/docs/incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md) ·
[06-19 reboot → wedge](docs/techdocs/docs/incidents/2026-06-19-node-taxonomy-migration-storage-churn.md)
