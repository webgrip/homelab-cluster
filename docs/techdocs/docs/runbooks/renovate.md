# Runbook: Renovate

Use this when Renovate alerts are firing (for example `RenovateOperatorDeploymentUnavailable`, `RenovateProjectRunFailed`, `RenovateProjectDependencyIssues`) or Renovate PRs stop appearing.

## Fast triage

1) Check the operator / controller

- `kubectl -n renovate get pods -o wide`
- `kubectl -n renovate logs deploy/renovate-operator --tail=200`

2) Check the Dependency Dashboard — Renovate runs against **both forges** (GitHub + Forgejo), each repo has its own dashboard issue

- Look for authentication errors, rate limiting, or failing managers.

3) Check Flux status (if Renovate is deployed via GitOps)

- See the Flux runbook: [docs/techdocs/docs/runbooks/flux.md](flux.md)

## Common causes

- Token expired / revoked (GitHub app token / PAT).
- Repository permissions changed.
- Renovate image updated but config incompatible.
- Cluster resource pressure causing restarts.

## Forgejo path gotchas

The in-cluster Renovate also runs against Forgejo (`webgrip-forgejo` RenovateJob). Two failure modes are silent — Renovate keeps running, it just quietly does nothing for the affected repos.

- **Un-mirrored repos have the Pull Requests unit OFF, so Renovate skips them.** Converting a `gitea-mirror` pull-mirror to a regular repo leaves `has_pull_requests=false` (mirrors are read-only). Renovate then logs `Skipping repository <r> because pull requests are disabled` and excludes it — the repo is *discovered but skipped*. Also note autodiscovery **can only seed `status.projects` on the cron** (`47 */6`); the per-project webhook path can't add a *new* project mid-cron. Fix / restore PR-unit parity for every de-mirrored repo:

  ```bash
  scripts/forgejo-sync.sh --all --only prs --apply
  ```

- **The webhook `authorization_header` must be a TOP-LEVEL field, not a `config` key.** On the Forgejo hook API, `authorization_header` is top-level; Forgejo silently drops unknown `config` keys, so nesting it sends NO `Authorization` header and the operator receiver 401s. Diagnose via the hook's UI "Recent Deliveries" (it shows the sent headers + response code). The per-repo webhook is registered by `scripts/forgejo-sync.sh --only webhook` and points at the internal Service (`http://renovate-operator.renovate.svc.cluster.local:8082/webhook/v1/forgejo?…`), not the envoy-external hairpin.

Debugging trick for "which repos are skipped and why": `renovate --autodiscover --write-discovered-repos` with `LOG_LEVEL=debug`.

## More detail

- Full Renovate docs/config: [docs/techdocs/docs/renovate.md](../general/renovate.md)
- Forgejo migration design: [RFC — Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md)
