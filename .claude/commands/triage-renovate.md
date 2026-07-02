---
description: Triage open Renovate PRs — classify risk and recommend merge/hold.
argument-hint: "[optional: PR number to focus on]"
allowed-tools: Bash(mise exec -- gh pr list*), Bash(mise exec -- gh pr view*), Bash(mise exec -- gh pr diff*), Bash(git diff*), Bash(git log*)
---

Triage Renovate dependency PRs in this repo. Read-only — do not merge or comment unless I explicitly ask.

Scope: $ARGUMENTS (if empty, all open Renovate PRs).

1. `mise exec -- gh pr list --author 'app/renovate' --state open --json number,title,labels,headRefName` (also try author `renovate[bot]`).
2. For each (or the focused PR), `gh pr diff` the manifest change. Classify the bump:
   - **patch/minor, no values change** → low risk, safe to merge.
   - **major chart/image bump** → check the upstream CHANGELOG for breaking changes, CRD/schema migrations, and whether a multi-major jump risks a Flux rollback (see `docs/techdocs/docs/runbooks/flux.md`, "Recover a stalled HelmRelease").
   - **CRD-bearing charts** (cnpg, grafana-operator, victoria-metrics-operator, etc.) → flag CRD upgrade ordering.
3. For anything touching observability: `release: kube-prometheus-stack` labels on ServiceMonitor/PrometheusRule are fully vestigial (nothing requires them; VM `selectAllByDefault` scrapes regardless — see the `victoriametrics` skill), so a chart bump adding or dropping them is a non-event.
4. Output a table: PR | bump | risk | recommendation | what to check. End with a suggested merge order (low-risk batch first).
