# AGENTS.md

This repo is GitOps-managed (Flux + HelmRelease + Kustomize) and uses SOPS for secrets.

## How to work in this repo (broad strokes)

When you (the agent) are asked to make changes here, the intent is usually:

- Make the change in GitOps manifests (HelmRelease/Kustomize/Flux Kustomization) so Flux applies it.
- Keep changes minimal, reversible, and consistent with existing patterns.
- Prefer “wire it up” changes over bespoke YAML (reuse chart features like `existingSecret`, `extraEnvFrom`, `envFromSecret`).

When unsure, optimize for:

- Clear ownership of where config lives (one obvious file to edit).
- No secrets in Git history.
- Simple rollback (revert commit).

## SOPS / secrets policy

SOPS secrets require human action.

- Do not add or modify `*.sops.yaml` files automatically.
- If a change needs a secret, implement the non-secret wiring, and then document:
  - Secret name + namespace
  - required keys
  - a plaintext YAML template the human should encrypt with SOPS
  - any external setup steps (OAuth apps, DNS, API tokens)

Preferred secret wiring patterns:

- Helm values: `existingSecret`, `extraEnvFrom`, `envFromSecret` / `envFromSecrets`.
- Avoid embedding secret values in HelmRelease values.

## Diagnosing cluster issues (how to think)

Treat incidents as a dependency chain and debug from “control plane / GitOps” outward.

1) Confirm Flux is applying what you think it is

- Check Flux reconciliation first: Kustomization/HelmRelease Ready states, recent errors.
- If the manifests aren’t being applied, everything else is downstream noise.

1) Confirm the Kubernetes primitives are healthy

- Namespace exists, pods scheduled, deployments progressing, events make sense.
- Look for obvious scheduling blockers: image pulls, missing PVCs, affinity/taints, invalid configs.

1) Confirm storage + network basics

- Storage: PVC bound, Longhorn volumes healthy, no multi-attach loops.
- Network: DNS works from inside cluster, Gateway/HTTPRoute Accepted, services resolve.

1) Confirm app-specific signals

- Logs/traces/metrics: use the observability stack to spot where failure begins.
- Prefer answering: “what changed?” and “what dependency is failing?”

1) Make fixes GitOps-first

- If the fix is configuration, change manifests and let Flux reconcile.
- If a one-off action is unavoidable (e.g., emergency secret creation), record it and convert it to GitOps afterward.

## Guardrails

- If a change requires a secret, document:
  - the Secret name/namespace
  - the required keys
  - a plaintext YAML template the human should encrypt with SOPS
  - any external setup steps (OAuth app config, DNS, etc.)
- Prefer wiring secrets into workloads via Helm values such as `existingSecret`, `extraEnvFrom`, or `envFromSecret`.

