# Incident 2026-07-17 — forgejo netpol identity trap → silent WAL death → GitOps deadlock

**Severity:** SEV2 (in-cluster git + CI down; Flux's source of truth down with it — no fix could reconcile)
**Duration:** silent degradation 2026-07-15 → 07-17 (~2 days, WAL archiving dead while reporting healthy); hard outage a few hours on 07-17 until bridge-apply recovery.
**Data loss:** none (WAL retained on the volume; archiving resumed and drained after recovery).

## Summary

The 2026-07-15 zero-trust rollout enabled default-deny on the `forgejo` namespace with
kube-apiserver egress "allowed" via `ipBlock 10.43.0.1/32:443` — which under Cilium **never
matches** (API-server traffic carries the reserved `kube-apiserver` *identity*; CIDR rules don't
govern it — the ADR-0005 trap, hit here for the **third** time). The DB layer was also missing
`components/cnpg-netpol`.

Two layers failed at different speeds:

1. **Fast, visible:** the CNPG instance manager needs the API at startup — the next postgres
   restart wedged it (exit 1, `dial tcp 10.43.0.1:443: i/o timeout`).
2. **Slow, silent:** the **barman-cloud plugin also needs API access** (it reads the `ObjectStore`
   CRD). WAL archiving died instantly — but the Cluster kept showing `ContinuousArchiving=True`.
   Since WAL only recycles after successful archiving, `pg_wal` filled the 5Gi `walStorage` volume
   in ~1.5 days, which is what actually crashed postgres.

Forgejo down took down Flux's own source ([ADR-0011](../adr/adr-0011-flux-source-forgejo.md)) —
a **GitOps deadlock**: the manifest fix existed but nothing could reconcile it.

## Impact

- Forgejo (git hosting, CI, Renovate target) down; Flux reconciliation stalled cluster-wide on the
  last-applied state.
- Both forgejo provisioner Jobs failed past `backoffLimit` and sat terminal (22–45h) — the trigger
  for the Job self-heal doctrine (`provisioner-job` skill).
- The renovate provisioner stayed dead ~3 more days on a *second* netpol gap (missing **ingress**
  allow from the `renovate` namespace to forgejo:3000) — found only because the new self-heal retry
  loop kept visibly re-failing.

## Root cause

```text
zero-trust default-deny on forgejo ns
  + apiserver egress written as ipBlock 10.43.0.1/32 (inert under Cilium — identity, not CIDR)
  + DB-layer ks missing components/cnpg-netpol
  → CNPG instance manager loses API at startup (exit 1)
  → barman-cloud plugin loses API → WAL archiving dies SILENTLY (status still True)
  → pg_wal fills the 5Gi walStorage volume (~1.5 days)
  → postgres crashes (exit 4, CNPG low-disk gate) → Forgejo down → Flux source down → deadlock
```

Diagnostic wrinkle: the forgejo-db crash-loop **exit codes changed as layers peeled** (1 → 4 after
the netpol fix). Re-read the logs after each fix — don't assume one root cause.

## Recovery — bridge-apply (no break-glass needed)

Instead of the [flux-source break-glass repoint](../runbooks/flux-source.md), the fix was
committed locally, the **byte-identical** manifests hand-applied out-of-band, the DB recovered
(live PVC expand + pod delete — CNPG never propagates a `walStorage` size change from git to the
live PVC), Forgejo came up, the commit was pushed, and Flux **adopted** the hand-applied resources
on first reconcile (verified: the CNPs picked up `kustomize.toolkit.fluxcd.io/name` ownership
labels). Pattern documented in the flux-source runbook.

## Fixes

| Change | Where |
| --- | --- |
| `components/cnpg-netpol` added to the DB-layer ks | `kubernetes/apps/forgejo/forgejo/app/database/kustomization.yaml` |
| `allow-provisioner-apiserver` CNP (`toEntities: kube-apiserver`) for the provisioner Jobs | `kubernetes/apps/forgejo/networkpolicy.yaml` |
| Ingress allow from the `renovate` namespace on :3000 | `kubernetes/apps/forgejo/networkpolicy.yaml` |
| `walStorage` 5Gi → 10Gi (+ NOTE that git size changes don't reach the live PVC) | `kubernetes/apps/forgejo/forgejo/app/database/cluster.yaml` |
| Inert `ipBlock 10.43.0.1/32` rules NOTE'd out (backstage, n8n, sparkyfitness, vikunja, freshrss) | per-ns `networkpolicy.yaml` |
| Job self-heal doctrine (force annotation + `cleanup-opt-in-failed-jobs` retry loop) | `kubernetes/apps/kyverno/policies/app/cleanup-opt-in.yaml`, `provisioner-job` skill |

## Lessons

1. **`ContinuousArchiving=True` is not evidence archiving works** when the barman-cloud plugin has
   lost API access — verify via recent `backups.postgresql.cnpg.io` / WAL objects in the bucket.
   (cnpg-database skill.)
2. **cnpg-netpol belongs in the DB-layer ks** of every zero-trust namespace; apiserver access is
   identity-based (`toEntities: kube-apiserver`), never `ipBlock`. (network-policy skill; third
   recurrence.)
3. **Ingress is a zero-trust checklist too** — every consumer of forgejo:3000 needs an explicit
   ingress allow; egress-only sweeps miss it silently.
4. **`walStorage` size changes in git never resize the live PVC** — expand the PVC directly, then
   delete the pod. (cnpg-database skill.)
5. **Bridge-apply beats break-glass** when the outage's fix is itself a manifest: commit locally,
   hand-apply byte-identical, push after recovery — Flux adopts cleanly. (flux-source runbook.)
6. **Terminal Failed Jobs never self-recover** — Kubernetes won't retry past `backoffLimit` and
   Flux won't replace a spec-matching Job; hence the opt-in cleanup-retry loop.
   (provisioner-job skill.)

## Related

- [2026-07-11 — Talos OOMController kills the CNPG DB tier](2026-07-11-talos-oom-db-tier.md) — the
  sibling failure class on the same DB tier (QoS, not netpol).
- [ADR-0005](../adr/adr-0005-cilium-gateway-egress-for-oidc.md) — the identity-vs-CIDR mechanism.
- [ADR-0011](../adr/adr-0011-flux-source-forgejo.md) / [flux-source runbook](../runbooks/flux-source.md) —
  why Forgejo down = Flux down, and the recovery options.
