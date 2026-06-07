# CLAUDE.md

GitOps homelab: Flux + HelmRelease + Kustomize, Talos nodes, SOPS secrets.

## Rules

- **GitOps-first.** Every change is a manifest edit reconciled by Flux. Avoid imperative `kubectl apply/delete/patch` (hooks block the dangerous ones). Keep diffs minimal and reversible.
- **Secrets need a human.** Never edit `*.sops.yaml` or print decoded values (hooks/permissions block this). Wire the non-secret parts, leave a `*.template.yaml`, and document Secret name/namespace/keys + external setup. Prefer `existingSecret`/`extraEnvFrom`/`envFromSecret`.
- **Run tooling via mise** — `mise exec -- <cmd>`; PATH binaries aren't configured for this cluster.
- **Validate before commit:** `./scripts/run-flux-local-test.sh`. Commit with `git -c commit.gpgsign=false commit`; if the `format-yaml` hook reformats, `git add -A` and recommit.
- **Work trunk-based on `main`.** Commit and push changes directly to `main` — do NOT create feature branches or open PRs (the owner works directly on `main`, which is unprotected). Still validate first; keep commits scoped and reversible.
- **Editing manifests:** Flux reconciles 3 layers — root `kubernetes/flux/cluster/ks.yaml` → per-app `kubernetes/apps/<ns>/<app>/ks.yaml` (wiring: `dependsOn`, `targetNamespace`, `postBuild.substituteFrom`) → `<app>/app/` (resources). Escape runtime shell vars in manifests as `$${...}`.

## Where things are

- **Task recipes → skills** (auto-load when relevant): `add-app`, `grafana-dashboard`, `cnpg-database`, `authentik-oidc`, `flux-validate`, `talos` (node ops, upgrades, scheduling/topology).
- **Debug/health → `cluster-health` subagent**; trigger Renovate → `renovate-trigger` subagent.
- **Live cluster (read-only) → MCP** (in-cluster, Flux-managed, connect over HTTP; committed `.mcp.json`): `grafana` (Prom/Loki/Tempo/Mimir) + `kubernetes` (read-only `view` role). LAN-only; see `.claude/README.md`.
- **Safety is enforced** by hooks + permissions in `.claude/` (block SOPS edits, plaintext secrets, destructive cluster commands; validate manifests on edit).
- **Deep docs → `docs/techdocs/docs/`** (+ `runbooks/`). Endpoints: API VIP `10.0.0.25`, envoy-internal `10.0.0.27` (LAN), envoy-external `10.0.0.28` (public), k8s-gateway `10.0.0.26`, Garage S3 `10.0.0.110:3900`. Hostnames template as `<app>.${SECRET_DOMAIN}` (literal is SOPS-encrypted; docs disagree — don't hardcode it).
