# Runbook: Flux

Use this when Flux alerts are firing (for example `FluxKustomizationNotReady`, `FluxHelmReleaseNotReady`, or `FluxResourceDriftDetected`) or when “GitOps isn’t applying what you expect”.

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
- Runtime drift from manual `kubectl`/`helm` changes or controller-side mutation outside Git.

## Recover a stalled HelmRelease

When a HelmRelease is stuck `Stalled` / `RetriesExceeded` (install retries
exhausted — for example it failed because an `existingSecret` didn't exist yet,
then remediation uninstalled it), the usual imperative recovery commands are
**blocked in this repo** (GitOps-only): `flux reconcile --force`,
`flux suspend`/`flux resume`, and `kubectl patch/apply/delete` are all denied.
The in-cluster `kubernetes` MCP is read-only `view`, so it can't remediate
either.

To un-stall it, make helm-controller reset the failure count and re-attempt the
release by **incrementing the HR's generation via a committed spec change**:

- Edit the HelmRelease with a benign, useful spec field bump — e.g. add or
  change `spec.maxHistory: 3` — and commit + push to `main`. Flux applies the
  new generation and helm-controller retries the release.
- **Fixing the underlying cause alone does NOT un-stall it.** Adding the missing
  Secret (or otherwise correcting the failure) leaves the HR generation
  unchanged, so helm-controller does not retry. You still need the generation
  bump.

Seen during the Forgejo bring-up: admin/oidc secrets were committed but the HR
stayed stalled until a `spec.maxHistory` bump forced the retry.

## Runtime drift

When `FluxResourceDriftDetected` fires:

- Inspect the affected resource:
  - `flux get all -A`
  - `kubectl -n <namespace> describe <kind> <name>`
- Check whether the difference was intentional manual work or unintended mutation.
- If intentional, make the same change in Git and let Flux reconcile it.
- If unintentional, revert the live change or force a Flux reconcile after confirming the Git state is still correct.

### Known benign drift: spegel

A global `driftDetection` patch with `mode: warn` is set on every HelmRelease in
`kubernetes/flux/cluster/ks.yaml` — Flux detects and logs drift but never
remediates it (so it doesn't fight Kyverno mutate webhooks or controller-side
defaulting). The notable, persistent drift we've seen is **spegel**: its chart
renders a DaemonSet that omits fields the API server then defaults
(`spec.revisionHistoryLimit`, `spec.updateStrategy.rollingUpdate.maxSurge`), so
it logs drift on every reconcile and never converges. This is benign noise on
`FluxResourceDriftDetected`. A per-HR `ignore` for spegel's server-side
DaemonSet defaults is proposed but **not yet applied** (roadmap item 75).

## Fix workflow (GitOps-first)

- Make the minimal manifest change in Git.
- Let Flux reconcile, then confirm the resource becomes `Ready`.
- Avoid one-off manual `kubectl apply` changes unless it’s an emergency; if you must, record it and convert it to GitOps.
