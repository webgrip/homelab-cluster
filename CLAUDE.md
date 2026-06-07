# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

GitOps homelab: Flux + HelmRelease + Kustomize, Talos nodes, SOPS secrets. Versions/nodes live in `talos/talenv.yaml`, `talos/talconfig.yaml`, `.mise.toml` — README/techdocs version numbers are stale, don't trust them.

## Rules

- **GitOps-first.** Every change is a manifest edit reconciled by Flux. Avoid imperative `kubectl apply/delete/patch` (hooks block the dangerous ones). Keep diffs minimal and reversible.
- **Secrets need a human.** Never edit `*.sops.yaml` or print decoded values (hooks/permissions block this). Wire the non-secret parts, leave a `*.template.yaml`, and document Secret name/namespace/keys + external setup. Prefer `existingSecret`/`extraEnvFrom`/`envFromSecret`.
- **Run tooling via mise** — `mise exec -- <cmd>`; PATH binaries aren't configured for this cluster.
- **Validate before commit:** `./scripts/run-flux-local-test.sh`. Commit with `git -c commit.gpgsign=false commit`; if the `format-yaml` hook reformats, `git add -A` and recommit.
- **Editing manifests:** Flux reconciles 3 layers — root `kubernetes/flux/cluster/ks.yaml` → per-app `kubernetes/apps/<ns>/<app>/ks.yaml` (wiring: `dependsOn`, `targetNamespace`, `postBuild.substituteFrom`) → `<app>/app/` (resources). Escape runtime shell vars in manifests as `$${...}`.

## Don't break things

- **Talos apply always reboots here** → `task talos:apply-node-safe IP=<ip> HOSTNAME=<name>` (drains first), never `apply-node`. talosconfig = `talos/clusterconfig/talosconfig`; address soyo-3 by IP `10.0.0.22`.
- **Control-plane nodes soyo-1/2/3** (`10.0.0.20`–`.22`) share one disk for etcd + everything. Schedule write-heavy workloads on the worker **`fringe-workstation`** (`10.0.0.23`) via hard `requiredDuringScheduling` nodeAffinity `node-role.kubernetes.io/control-plane DoesNotExist`.

## Where things are

- **Task recipes → skills** (auto-load when relevant): `add-app`, `grafana-dashboard`, `cnpg-database`, `authentik-oidc`, `flux-validate`.
- **Debug/health → `cluster-health` subagent**; trigger Renovate → `renovate-trigger` subagent.
- **Live cluster (read-only) → MCP** (in-cluster, Flux-managed, connect over HTTP; committed `.mcp.json`): `grafana` (Prom/Loki/Tempo/Mimir) + `kubernetes` (read-only `view` role). LAN-only; see `.claude/README.md`.
- **Safety is enforced** by hooks + permissions in `.claude/` (block SOPS edits, plaintext secrets, destructive cluster commands; validate manifests on edit).
- **Deep docs → `docs/techdocs/docs/`** (+ `runbooks/`). Endpoints: API VIP `10.0.0.25`, envoy-internal `10.0.0.27` (LAN), envoy-external `10.0.0.28` (public), k8s-gateway `10.0.0.26`, Garage S3 `10.0.0.110:3900`. Hostnames template as `<app>.${SECRET_DOMAIN}` (literal is SOPS-encrypted; docs disagree — don't hardcode it).
