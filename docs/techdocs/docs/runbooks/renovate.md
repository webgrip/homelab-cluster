# Runbook: Renovate

Use this when Renovate alerts are firing (for example `RenovateOperatorDeploymentUnavailable`, `RenovateProjectRunFailed`, `RenovateProjectDependencyIssues`) or Renovate PRs stop appearing.

## Fast triage

1) Check the operator / controller

- `kubectl -n renovate get pods -o wide`
- `kubectl -n renovate logs deploy/renovate --tail=200` (adjust deployment name if different)

2) Check the Dependency Dashboard (GitHub)

- Look for authentication errors, rate limiting, or failing managers.

3) Check Flux status (if Renovate is deployed via GitOps)

- See the Flux runbook: [docs/techdocs/docs/runbooks/flux.md](flux.md)

## Common causes

- Token expired / revoked (GitHub app token / PAT).
- Repository permissions changed.
- Renovate image updated but config incompatible.
- Cluster resource pressure causing restarts.

## More detail

- Full Renovate docs/config: [docs/techdocs/docs/renovate.md](../renovate.md)
