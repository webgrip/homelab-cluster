# Incident 2026-09-27 — Longhorn 1.11.3 rotates its webhook CA mid-upgrade → every manager crash-loops

**Severity:** SEV2 (storage control plane down; a concurrent database roll then took Forgejo, Flux's source, down for minutes)
**Duration:** 2026-09-27 08:41 → 09:18 UTC (37 min). Longhorn managers down 08:41 → 09:11; databases recovered by 09:18.
**Data loss:** none. The data path (instance-managers, engines) kept running throughout; volumes stayed healthy.

## Summary

The Longhorn chart upgrade 1.11.2 → 1.11.3 (commit `94b460b2`) started new `longhorn-manager` pods.
On start they found the admission-webhook CA secret unreadable, generated a new CA and leaf certificate,
and then called their own `failurePolicy: Fail` mutating webhook while the webhook configurations still
trusted the old CA. The API server rejected the served certificate (`tls: bad certificate`) and every
manager exited. Flux rolled the release back to 1.11.2, but the old managers reuse the rewritten secrets,
so they crash-looped the same way. With no manager serving the webhook, no manager could start.

While the managers were down, commit `6287d0d4` from a concurrent session added a CPU request to every
CNPG cluster, which rolls every database instance. The new database pods could not attach their volumes,
and `forgejo-db` going down took Forgejo (git over SSH and HTTP, Flux's only source) with it.

## Impact

- 08:41 → 09:11: no Longhorn attach, detach, rebuild or UI. Running volumes kept serving I/O.
- ~09:04 → 09:18: seven databases restarting without storage, including forgejo-db (Forgejo and Flux
  source down), litellm-db, backstage-db, n8n-db and grafana-db. `ntfy` and `grafana` Kustomizations
  failed their dry-runs and needed a retry.

## Timeline (UTC)

| Time | Event |
| --- | --- |
| 08:39 | Push of `94b460b2` (1.11.3) and `c446fc92` (a no-rollback setting that turned out to be inert). |
| 08:41:00 | New managers log `parse CA private key ... use ParseECPrivateKey instead`, then `Regenerating webhook CA and leaf`; secrets `longhorn-webhook-ca`/`-tls` rewritten. |
| 08:44:59 | `Upgrade failed: ... failed calling webhook "mutator.longhorn.io" ... tls: bad certificate`; managers exit. |
| 08:45 | Helm upgrade times out; Flux starts a rollback despite `retries: 0` in the release's own spec. |
| 08:50–09:05 | Rollback to 1.11.2 also times out; its managers crash on the same webhook call. HelmRelease suspended by an agent. |
| 09:04 | `6287d0d4` (CPU request on every CNPG cluster) pushed by a concurrent session; databases start rolling. |
| ~09:08 | Human deletes both Longhorn webhook configurations and the manager pods. |
| 09:11 | 6/6 managers Ready; webhook caBundle matches the new CA. |
| 09:12 | All 62 attached volumes healthy; detach backlog cleared. |
| 09:18 | All application databases healthy; Forgejo and Flux sources back. |

## Root cause

An upstream regression in Longhorn 1.11.3. The release backports in-process bootstrap and rotation of
the webhook TLS secrets (longhorn/longhorn#13116, parent #13012). Its CA parser
(`webhook/cert/bootstrap.go`, `parseCASecret`) accepts only a PKCS8 RSA key, while installs from 1.11.2
and earlier hold a rancher dynamiclistener CA with an ECDSA P-256 key. Every first upgrade from such an
install therefore regenerates the CA. The daemon rewrites the CA secret before the webhook server starts,
and the caBundle is only refreshed later by an asynchronous Secret handler. The upgrade step meanwhile
writes Longhorn resources through the `Fail` webhooks, so the managers exit before that handler runs.
No upstream issue existed at the time; 1.12.x and master carry the same parser.

Contributing, on our side:

- The cluster-wide HelmRelease patch in `kubernetes/flux/cluster/ks.yaml` forced
  `RemediateOnFailure` with two retries and a rollback onto every release, overriding Longhorn's own
  setting. The change was verified by rendering the app, not by reading the live HelmRelease.
- A database-rolling change was pushed during a storage outage by a second session.

Nothing else in the estate contributed: the webhook configurations are owned by `longhorn-manager`
alone, the chart ships no webhook configuration templates, and no Kyverno policy matches Secrets or
webhook configurations in `longhorn-system`.

## Resolution

1. Human, break-glass: delete `mutatingwebhookconfiguration/longhorn-webhook-mutator` and
   `validatingwebhookconfiguration/longhorn-webhook-validator`, then delete the manager pods. The
   managers re-register both configurations with the new CA.
2. `af7d89d9`: the remediation part of the cluster-wide patch skips HelmReleases labelled
   `helm.webgrip.io/fix-forward`; Longhorn carries the label.
3. Longhorn's HelmRelease uses `upgrade.strategy: RetryOnFailure`: a failed upgrade is retried, never
   rolled back.

## What went well

- The data path never stopped; no volume degraded.
- The failed upgrade had not migrated anything (`current-longhorn-version` stayed `v1.11.2`), so the
  rollback was harmless.

## Lessons and follow-ups

- Verify a remediation or upgrade-policy change on the live object (`kubectl get hr -o
  jsonpath='{.spec.upgrade}'`) before the rollout that depends on it.
- Releases for which a rollback is harmful (downgrade-refusing charts, one-way database migrations)
  carry `helm.webgrip.io/fix-forward`.
- One core change at a time: storage, admission, network, Flux, DNS, secrets, databases and nodes are
  not changed while another of them is mid-rollout.
- Before a Longhorn upgrade, compare the webhook caBundle with `longhorn-webhook-ca` and keep the
  break-glass commands ready. The retry of 1.11.3 is expected to take the "leave as is" path, because
  the CA is now RSA.
- File the ECDSA-to-RSA CA handover bug upstream.
