---
description: Accumulated learnings from past sessions — non-obvious pitfalls and constraints specific to this repository.
---

# Repository Learnings

## GrafanaDashboard folder resolution is namespace-scoped

`folderRef: <crd-name>` and `folder: "Title"` both look for `GrafanaFolder` CRDs in the **same namespace** as the `GrafanaDashboard`. `allowCrossNamespaceImport: true` does NOT help with folder lookup — it only makes the dashboard visible to a cross-namespace Grafana instance.

**Symptom:** `NoMatchingFolder` error on dashboards deployed to non-`observability` namespaces even though GrafanaFolder CRDs exist in `observability`.

**Fix:** All `GrafanaDashboard` files must live in `kubernetes/apps/observability/grafana/app/dashboards/`. Do NOT co-locate dashboards with their service in other namespaces. Use `folder: "Title"` (not `folderRef:` or `folderUID:`). Add entries to `observability/grafana/app/kustomization.yaml`.

## GUAC blob-store must be set explicitly when MinIO is disabled

When `minio.enabled: false` in the GUAC chart, the default `blob-addr` still points to the MinIO service (`s3://guac?endpoint=http://security-minio...`). The chart does NOT auto-update it.

**Symptom:** `cd/osv-certifier` CrashLoopBackOff with S3 connection errors to the disabled MinIO service.

**Fix:** Set `guac.blobAddr` explicitly in the HelmRelease values:
```yaml
guac:
  blobAddr: "s3://guac?endpoint=http://10.0.0.110:3900&region=garage&disableSSL=true&s3ForcePathStyle=true"
```

## Pre-commit hook may reformat YAML; re-stage before commit

`lefthook` runs `format-yaml` on staged files. If it modifies files, `git commit` exits non-zero with unstaged changes. Re-run `git add -A && git commit` to pick up the reformatted files.

## talosctl: soyo-3 must be addressed by IP, not hostname

`talosctl` cannot resolve `soyo-3` by hostname. Use the IP `10.0.0.22` directly for any `talosctl` operations targeting soyo-3.

## GPG signing is enabled; bypass for agent commits

The repo has `commit.gpgsign=true`. Use `git -c commit.gpgsign=false commit` when committing from the agent environment where GPG keys are not available.
