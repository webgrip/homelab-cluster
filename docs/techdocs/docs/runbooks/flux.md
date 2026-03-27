# Runbook: Flux

Use this when Flux alerts are firing (for example `FluxKustomizationNotReady` or `FluxHelmReleaseNotReady`) or when “GitOps isn’t applying what you expect”.

## Fast triage

1) Check reconciliation status

- `flux get kustomizations -A`
- `flux get helmreleases -A`

Look for:

- `Ready: False`
- Stalled resources
- Reconciliation errors in the `Message` column

2) Inspect controller logs

- Kustomize:
  - `kubectl -n flux-system logs deploy/kustomize-controller --tail=200`
- Helm:
  - `kubectl -n flux-system logs deploy/helm-controller --tail=200`
- Source controller (if it can’t fetch Git/Helm repos):
  - `kubectl -n flux-system logs deploy/source-controller --tail=200`

3) Validate the underlying Kubernetes primitives

- `kubectl get ns`
- `kubectl get events -A --sort-by=.lastTimestamp | tail -n 50`

## Common root causes

- Bad manifest (schema/validation error) blocks apply.
- Helm chart upgrade failure.
- Missing CRDs (a chart expects CRDs that aren’t installed yet).
- Image pull failures.
- Secret not present (especially if it’s a SOPS-managed secret that wasn’t created yet).

## Fix workflow (GitOps-first)

- Make the minimal manifest change in Git.
- Let Flux reconcile, then confirm the resource becomes `Ready`.
- Avoid one-off manual `kubectl apply` changes unless it’s an emergency; if you must, record it and convert it to GitOps.
