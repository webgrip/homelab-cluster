---
name: flux-validate
description: Validate and diff Flux/Kustomize/HelmRelease manifests before committing or merging. Use when asked to validate, lint, render, or dry-run manifests, or to check what a change will do.
allowed-tools: Bash(./scripts/run-flux-local-test.sh*), Bash(./scripts/run-flux-local-diff.sh*), Bash(just *), Bash(mise exec -- *)
---

# Validate manifests

CI runs the same checks — run before committing.

- **Primary gate (offline render):** `./scripts/run-flux-local-test.sh` — renders every Kustomization + HelmRelease via flux-local in Docker; fails on broken builds. Needs Docker.
- **Single Kustomization, manually** (faster than the full gate when iterating on one app): copy the repo **including `.git`** to a workspace, `chmod -R a+rwX`, then
  `docker run --rm -e HOME=/tmp -v "$WS:/github/workspace" --entrypoint sh <flux-local image+digest from scripts/lib/flux-local.sh> -lc "git config --global --add safe.directory /github/workspace >/dev/null && flux-local build ks <name> -n <ns> --path /github/workspace/kubernetes/flux/cluster"`.
  Without `.git` it fails with the misleading `Unable to find input path` (2026-07-12). The `dependsOn with invalid names` stderr is whitelisted noise (`scripts/lib/flux-local.sh`).
- **Render ≠ apply — a real blind spot.** flux-local, `helm template`, and kubeconform *render* manifests; they never *install* them, so they miss install-time failures. A chart that creates a CR of its own not-yet-registered CRD (classic: an operator's own `serviceMonitor`) renders clean but fails `helm install` with `no matches for kind …`. Verify operators by their **live HelmRelease `Ready` status after merge**, not just the render.
- **Diff vs live:** `./scripts/run-flux-local-diff.sh <pull-dir> <default-dir> <output-file>`.
- **Policy/supply-chain:** `just kyverno-test` · `just kyverno-chainsaw` (KinD) · `just verify-oci-digests`.
- **New chart registry?** `verify-oci-digests` resolves each `OCIRepository` digest against the registry. A host that needs auth must have a per-host token case in `scripts/lib/oci.sh` — `ghcr.io`, `docker.io`, `code.forgejo.org` are handled; anonymous registries (`quay.io`, `gcr.io`, `mirror.gcr.io`) need none. Symptom of a missing case: `FAIL … could not resolve registry digest` (a 401 the script treats as permanent). Add a case mirroring the existing ones — the token URL comes from the registry's `WWW-Authenticate: Bearer realm=…` header.
- **After merge:** `just reconcile` then `mise exec -- flux get kustomizations -A` (READY=False = failure; SUSPENDED=False is normal).
- **`${SECRET_DOMAIN}` in HTTPRoute hostnames:** the Edit/Write hook (`validate-manifest.sh`) runs kubeconform against the datreeio CRDs-catalog **pre-substitution**, so the Flux postBuild var fails the hostname regex — a false positive on a correct manifest. Make hostname-bearing edits via `sed`/Bash (the hook fires only on Edit/Write); `./scripts/run-flux-local-test.sh` substitutes and is the real gate.

Per-file `kubeconform`/`yamllint` + skill guards run automatically on Edit/Write via the PostToolUse hooks; this skill is the whole-repo render the hooks skip (too slow per-edit). All tooling via `mise exec --`.
