# Incident 2026-09-25 — Kyverno denies the CNPG primary relabel → empty `-rw` services → GitOps deadlock

**Severity:** SEV2 (in-cluster git and the image proxy down; Flux's only source down with them, so no fix could reconcile)
**Duration:** 2026-09-25 22:20 → 22:47 UTC (27 min). A second, capacity-driven outage of Authentik and Forgejo ran 2026-09-26 07:01 → 07:37 UTC.
**Data loss:** none.

## Summary

A node drain during the Talos v1.13.10 rollout recreated the single-instance CNPG primaries on
`fringe-workstation`. Each came up `Running`, but its `<cluster>-rw` Service stayed without
endpoints: the operator's `Setting primary label` PATCH was denied by the Kyverno ValidatingPolicy
`image-supply-chain-digest-pinned` ("Images should be pinned by digest"). The pods are listed by
name in PolicyException `security/exception-cnpg-pods-resources-cel`, which admitted their creation
minutes earlier but not the label update. Forgejo lost its database, so Flux's only GitRepository
(`forgejo-http`) went not-Ready, and neither a git fix nor a push could land.

## Impact

- Forgejo (git, CI, Flux source), Harbor (pull-through proxy), FreshRSS and Ploeg without a database.
- Harbor `jobservice` and `exporter` crash-looped; image pulls through the proxy failed.
- `grafana-db` recovered normally: `observability` is in the policy's namespace exclusion list, as is
  `security` (guac, dependency-track).

## Timeline (UTC)

| Time | Event |
| --- | --- |
| 21:42–21:55 | The soyo upgrades restart all three Kyverno admission replicas; the new leader re-initialises the policy at 21:53:54. |
| 22:17 | `fringe-workstation` drained (`--disable-eviction`, instance-managers excluded). |
| 22:20:38 | `forgejo-db-1` recreated on worker-1 — creation admitted. |
| 22:31–22:32 | CNPG relabel PATCHes for ploeg, harbor and forgejo denied by `vpol.validate.kyverno.svc-fail`. |
| 22:44 | Break-glass by a human: `validationActions: [Audit]` on the policy, then `rollout restart deploy/cloudnative-pg`. Endpoints return within 20 s. |
| 22:45:23 | Flux restores `Deny` (kustomize-controller). Labels persist, services stay up. |
| 22:47 | Flux GitRepository Ready again. |

## Root cause

Not proven. After the policy object was re-applied, 72 of 72 server-side dry-run label updates on all
eight covered pods, across all three admission replicas, were admitted, and the same probe passed
54/54 and 63/63 before the worker drains the next morning, which relabelled without a single denial.
The leading hypothesis is a Kyverno startup race: the replicas had just restarted, and the
policy-to-exception binding stayed stale until the policy object changed. The standing weakness is
certain either way: every CNPG failover or reschedule in a non-excluded namespace depends on a
name-matched exception holding up under UPDATE.

## Second outage — N-1 capacity (2026-09-26)

With `worker-1` drained, `authentik-db-1`, `backstage-db-1` and `guac-db-1` stayed `Pending` for 30
minutes (insufficient memory on the two remaining workers; soyos excluded by the worker-pool
selector). `authentik-server` crash-looped without its database, and Forgejo's `configure-gitea` init
container, which syncs the Authentik OIDC provider, failed on the discovery URL's 503. So an SSO
outage took down the GitOps source. Everything recovered unaided within five minutes of the node's
return.

## Recovery

Break-glass (human only; Claude's guard hook blocks it):

```sh
kubectl patch vpol image-supply-chain-digest-pinned --type=merge -p '{"spec":{"validationActions":["Audit"]}}'
kubectl -n cnpg-system rollout restart deploy/cloudnative-pg
```

Flux reverts the patch on its next reconcile; that is intended.

## Follow-ups

1. Digest-pin the three images every CNPG pod runs (postgres `imageName`, the operator image behind
   the `bootstrap-controller` init container, the barman-cloud sidecar) and drop the CNPG entries
   from the exception.
2. Reproduce the exception miss: restart one admission replica, then run the dry-run probe
   against it.
3. Forgejo must start without Authentik: its init container should not hard-fail on the OIDC
   discovery URL.
4. Size the workers for N-1: one worker out must not leave CNPG primaries `Pending`.
5. Detect it: alert on a CNPG cluster whose `-rw` Service has no ready endpoints.

## Lessons

- Probe admission before a drain, not after: a server dry run of the exact UPDATE the operator will
  send costs nothing and persists nothing
  ([rolling-upgrade runbook](../runbooks/talos-rolling-upgrade.md#workers-pre-drain)).
- A pod that is `Running` with an empty Service is invisible to "are the pods up" checks; check the
  EndpointSlice.

## Related

- [2026-07-17 — forgejo netpol identity trap → GitOps deadlock](2026-07-17-forgejo-netpol-wal-gitops-deadlock.md)
- [ADR-0032 — Kyverno enforce promotion](../adr/adr-0032-kyverno-enforce-promotion-policy.md)
