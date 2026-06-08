---
description: Delta-aware cluster watch — report only what CHANGED since the last tick. Great under /loop while deploying.
allowed-tools: Bash(mise exec -- kubectl get*), Bash(mise exec -- flux get*)
---

Report only what **changed** since the previous tick — designed to run under `/loop` while a deploy/upgrade rolls out. Be terse.

State is cached at `/tmp/claude-watch-deploys.json`. Each tick:

1. Capture current state:
   ```bash
   mise exec -- kubectl get kustomizations,helmreleases -A -o json \
     | mise exec -- jq -c '[.items[]|{k:(.kind+"/"+.metadata.namespace+"/"+.metadata.name), ready:(any(.status.conditions[]?; .type=="Ready" and .status=="True")), susp:(.spec.suspend==true), rev:(.status.lastAppliedRevision // "")}] | sort_by(.k)'
   ```
2. Diff against `/tmp/claude-watch-deploys.json` (prior tick). Report:
   - ✅ **recovered**: was not-ready → now ready
   - 🔴 **broke**: was ready → now not-ready (include the Ready condition message via `kubectl get <kind> -n <ns> <name>`)
   - 🔄 **rolled**: `rev` changed (new revision applied)
   - ⏸️ **suspended/resumed**: `susp` flipped
   - 🆕/🗑️ resources added/removed
3. Also surface Warning events newer than the last tick:
   `mise exec -- kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp -o json | jq` — only show ones since the last run.
4. Write the fresh state back to `/tmp/claude-watch-deploys.json`.
5. If **nothing changed**, output a single line: `· no change (<N> ready, <M> not-ready, <S> suspended)`. Do not repeat unchanged status.

First run (no cache): just record state and print the baseline counts. Never mutate the cluster.
