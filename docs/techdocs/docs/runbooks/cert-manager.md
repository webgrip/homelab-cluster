# Runbook: cert-manager

Use this when certificates are expiring soon, aren’t being issued, or controllers error.

## Fast triage

1) Check cert-manager pods

- `kubectl -n cert-manager get pods -o wide`
- `kubectl -n cert-manager logs deploy/cert-manager --tail=200`

2) Inspect certificate resources

- `kubectl get certificates,certificaterequests,orders,challenges -A`

3) If using ACME DNS01

- Validate DNS provider credentials (often a Secret) exist and are correct.
- Confirm the expected TXT challenge records exist.

## Common causes

- Missing/incorrect DNS credentials.
- DNS provider API rate limiting.
- Clock skew or DNS propagation delays.
