---
description: Read-only cluster health digest — Flux, nodes, recent events, storage.
allowed-tools: Bash(mise exec -- kubectl get*), Bash(mise exec -- kubectl describe*), Bash(mise exec -- flux get*), Bash(mise exec -- flux check*)
---

Produce a concise, read-only health digest of the cluster. Do NOT mutate anything.

1. `mise exec -- flux get kustomizations -A --status-selector ready=false` and the same for `helmreleases` — list anything not Ready with its message.
2. `mise exec -- flux get all -A` filtered to suspended resources.
3. `mise exec -- kubectl get nodes -o wide` — flag any not Ready / pressure conditions.
4. `mise exec -- kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded` — non-running pods (CrashLoopBackOff, Pending, ImagePullBackOff…).
5. Recent warning events: `mise exec -- kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -20`.
6. Longhorn/Garage capacity if relevant (see the `longhorn` skill / `docs/techdocs/docs/runbooks/cnpg-backups.md`).

Summarize as: 🟢 healthy / 🟡 degraded / 🔴 broken, then a short bulleted list of anything needing attention with the file/resource to look at. If a deeper dependency-chain audit is needed, hand off to the `cluster-health` subagent.
