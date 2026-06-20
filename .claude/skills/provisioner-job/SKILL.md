---
name: provisioner-job
description: Build an in-cluster provisioner Job/CronJob that hits an admin API or writes a Secret/ConfigMap — least-privilege RBAC + a hardened, idempotent pod.
when_to_use: Use when an app needs a bootstrap or reconcile Job/CronJob that calls the k8s/an admin API or creates a Secret/ConfigMap (e.g. forgejo-ci-provisioner, cosign-pubkey, a renovate provisioner).
---

# In-cluster provisioner Job/CronJob

For a Job/CronJob that hits an admin API or writes a Secret/ConfigMap. Copy a real one:
`kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-ci-provisioner.job.yaml` (one-shot bootstrap,
mints a token into a Secret) · `kubernetes/apps/security/cosign-pubkey/app/publish.cronjob.yaml` (periodic
reconcile into a ConfigMap) · gate it with a Flux ks like
`kubernetes/apps/renovate/renovate-operator/ks-forgejo-provisioner.yaml` (`dependsOn` + `force: true`).

## Rules

- **Least-privilege RBAC.** If it only `kubectl get` + `kubectl apply`s ONE object, scope `get,update,patch`
  with `resourceNames: [<that-object>]`, and put `create` in a **separate** rule (RBAC can't scope `create`
  by name). Never blanket `secrets`/`configmaps`.
- **`secretKeyRef` env is injected by the kubelet, not the SA** — consuming a Secret via env needs **zero**
  RBAC; only direct API calls (`kubectl`) do. Set `automountServiceAccountToken: false` if it never calls
  the k8s API.
- **Fail-soft + idempotent.** Mark inputs `optional: true`, guard missing values (`exit 0`, retry next
  tick), and make writes create-or-update so re-runs converge.
- **Harden the pod:** `runAsNonRoot`, `seccompProfile: {type: RuntimeDefault}`, `readOnlyRootFilesystem:
  true`, `capabilities: {drop: [ALL]}`.
- **Secrets** the job consumes/produces → the `external-secrets` skill (ESO+OpenBao, never SOPS).

## Validate
`./scripts/run-flux-local-test.sh`.
