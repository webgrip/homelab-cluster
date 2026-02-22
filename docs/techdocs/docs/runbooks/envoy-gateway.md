# Runbook: Envoy Gateway

Use this when ingress fails, `EnvoyProxyDown` fires, or routes stop being accepted.

## Fast triage

1) Check network namespace pods

- `kubectl -n network get pods -o wide`

2) Check services

- `kubectl -n network get svc envoy-internal envoy-external -o wide`

3) Check HTTPRoutes

- `kubectl get httproute -A`

Look for `Accepted` conditions and route status.

## Common causes

- Gateway controller pods restarting.
- Misconfigured listeners/hostnames.
- DNS/cert issues that present as “ingress down”.

## Related

- If TLS/certs are failing, see cert-manager runbook:
  - [docs/techdocs/docs/runbooks/cert-manager.md](cert-manager.md)
