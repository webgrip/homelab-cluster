---
name: flux-validate
description: Validate and diff Flux/Kustomize/HelmRelease manifests before committing or merging. Use when asked to validate, lint, render, or dry-run manifests, or to check what a change will do.
allowed-tools: Bash(./scripts/run-flux-local-test.sh*), Bash(./scripts/run-flux-local-diff.sh*), Bash(just *), Bash(mise exec -- *)
---

# Validate manifests

Run these before committing manifest changes (CI runs the same checks).

## Offline render + validate (primary gate)
```bash
./scripts/run-flux-local-test.sh
```
Renders every Flux Kustomization + HelmRelease the way the controllers would (via flux-local in Docker) and fails on broken builds. Requires Docker.

## Diff against the live cluster
```bash
./scripts/run-flux-local-diff.sh <pull-dir> <default-dir> <output-file>
```

## Policy / supply-chain checks
```bash
just kyverno-test         # Kyverno CLI policy regression (kubernetes/apps/kyverno/tests)
just kyverno-chainsaw     # Chainsaw admission tests in a disposable KinD cluster
just verify-oci-digests   # OCIRepository digest pins vs registry
```

## Force a reconcile after merge
```bash
just reconcile            # flux-system reconcile --with-source
mise exec -- flux get kustomizations -A    # READY=False = failure; SUSPENDED=False is normal
```

## Notes
- Per-file `kubeconform`/`yamllint` run automatically via the PostToolUse hook when those tools are installed (add them to `.mise.toml` to enable). This skill covers the whole-repo render which the hook intentionally doesn't do (too slow per-edit).
- All cluster tooling runs through `mise exec --`.
