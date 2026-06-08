---
description: Walk through a CloudNativePG restore/disaster-recovery drill for an app.
argument-hint: "<app/namespace, e.g. authentik>"
allowed-tools: Bash(mise exec -- kubectl get*), Bash(mise exec -- kubectl describe*), Bash(mise exec -- kubectl logs*)
---

Run a **read-only verification** of disaster-recovery readiness for the CNPG database in: $ARGUMENTS. Do not restore into production — this confirms a restore *would* work and surfaces gaps.

Follow the `cnpg-database` skill's backup/restore section. Steps:

1. Find the `Cluster` resource for $ARGUMENTS under `kubernetes/apps/<ns>/<app>/app/database/`.
2. Confirm backups are configured and recent:
   - `mise exec -- kubectl get cluster,scheduledbackup,backup -n <ns>` — last successful backup age.
   - Verify the Garage/S3 WAL archive target is healthy — a stale target is the SPOF in [[cnpg-garage-wal-spof]].
3. Check `mise exec -- kubectl get cluster <name> -n <ns> -o jsonpath='{.status.firstRecoverabilityPoint}'` is set and recent.
4. Describe the bootstrap/recovery section of the manifest — confirm an `externalClusters` + `recovery` path exists (or document that only `initdb` is configured = no PITR).
5. Output: ✅ recoverable to PITR X / ⚠️ backups exist but no recovery path wired / 🔴 no usable backups — plus the exact manifest edit needed to close any gap. To actually perform a restore, hand off to me for a `bootstrap.recovery` Cluster on a throwaway namespace.
