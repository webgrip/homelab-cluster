# Alerting principles

This cluster uses Prometheus + Alertmanager (kube-prometheus-stack) to evaluate and route alerts.

The goal is simple: when an alert fires, the recipient should be able to answer **“What's broken, What's the impact, and what should I do next?”** in under 60 seconds.

## The decision framework (how to design an alert)

Before writing an alert, answer these questions in order:

1. **What action is expected?**
   - If there's no clear action, don't alert. Use a dashboard or a recording rule instead.

2. **Who is the audience?**
   - **Chat (Discord)**: fast triage, quick links, minimal noise.
   - **Page (if you add paging later)**: only user-impacting or data-loss risks; must be immediately actionable.

3. **Is it a symptom alert or a cause alert?**
   - **Symptoms** are preferred for paging (SLO burn, availability, “data is stale”, “ingestion is failing”).
   - **Causes** are useful for chat/investigation (pod crashloop, PVC filling, 5xx rate, queue backlog).

4. **What's the scope + blast radius?**
   - “One pod” vs “whole namespace” vs “cluster-wide”.
   - Put that into labels/annotations so routing + triage are fast.

5. **What makes this alert safe from noise?**
   - Use a meaningful `for:` period.
   - Prefer ratios and burn rates over raw counters.
   - Avoid low thresholds on spiky signals.

## What every alert should contain

These are the minimum requirements for PrometheusRule alerts.

### Labels (machine-facing)

Labels are for routing, grouping, inhibiting, and deduplication.

- `severity`: one of `info`, `warning`, `critical`
- `namespace`: if it's scoped to a namespace
- `cluster`: already applied as an external label in Prometheus

Strongly recommended (this unlocks good routing + clean silences):

- `owner`: who is responsible (e.g. `platform`)
- `service`: the owning subsystem (e.g. `mimir`, `flux`, `longhorn`, `cert-manager`, `apps`)

Principles:

- Keep label cardinality low (labels multiply alert instances).
- Include only labels that change who should respond or what they should do.

### Annotations (human-facing)

Annotations are the “message”. Keep them concise and action-oriented.

Required:

- `summary`: 1 line, name the failure + key scope. Example: “Prometheus remote_write backlog (mimir)”
- `description`: 3–8 lines:
  - What's happening
  - why it matters / impact
  - top 2–4 likely causes
  - first checks
- `runbook_url`: the *first click* should land on a runbook section with commands

Strongly recommended:

- `dashboard_url`: the *second click* should land on the right Grafana dashboard

### Golden dashboards (preferred targets)

Avoid “random dashboard links”. Prefer a small, curated set of dashboards that cover the majority of incidents.

- Observability stack overview: `https://grafana.${SECRET_DOMAIN}/d/obs-stack-overview/observability-stack-overview`
- LGTM+P health (Mimir/Loki/Tempo/Prometheus): `https://grafana.${SECRET_DOMAIN}/d/obs-lgtmp-health/observability-lgtmp-health`
- Kubernetes cluster health: `https://grafana.${SECRET_DOMAIN}/d/k8s-cluster-health/kubernetes-cluster-health`
- Kubernetes workloads & capacity: `https://grafana.${SECRET_DOMAIN}/d/k8s-workloads-capacity/kubernetes-workloads-capacity`
- PVC usage (Longhorn): `https://grafana.${SECRET_DOMAIN}/d/storage-pvc-usage/storage-pvc-longhorn`
- Longhorn health: `https://grafana.${SECRET_DOMAIN}/d/storage-longhorn-health/longhorn-storage-health`
- Flux health: `https://grafana.${SECRET_DOMAIN}/d/gitops-flux-health/flux-gitops-health`
- cert-manager certificates: `https://grafana.${SECRET_DOMAIN}/d/security-cert-manager/cert-manager-certificates`
- Synthetic blackbox: `https://grafana.${SECRET_DOMAIN}/d/synthetic-blackbox/synthetic-blackbox`
- Synthetic k6 canaries: `https://grafana.${SECRET_DOMAIN}/d/synthetic-k6-canaries/synthetic-k6-canaries`

Optional (add when you have a good target):

- `logs_url`: link to Loki search or a curated logs dashboard
- `silence_url`: pre-filled silence creation link

## Notification formatting principles (Discord)

A Discord alert message should prioritize:

1. **Signal**: alertname + severity + scope
2. **Next action**: first 2 checks to run
3. **Links**: runbook + dashboard + Alertmanager

Avoid:

- dumping all labels
- internal-only service DNS names in links
- long walls of text

## Alert communication template (gold standard)

This is the template for what an alert should communicate.

It is intentionally *structured* so that:

- the receiver can decide “do I act now?” quickly
- the first clicks always land somewhere useful
- silencing is safe and scoped
- the alert remains stable (no label explosions)

### The mental model

Every alert message should answer, in this order:

1. **What is failing?** (component + symptom)
2. **What is the impact / risk?** (user impact, data loss, degraded state)
3. **How urgent is it?** (severity)
4. **What scope is affected?** (cluster/namespace/service/remote)
5. **What should I do next?** (first 2–4 checks)
6. **Where do I click?** (runbook → dashboard → alert context → silence)

### Required labels (routing/dedup)

These labels are *machine-facing*. They should be stable, low-cardinality, and help routing/grouping.

- `severity`: `info` | `warning` | `critical`
- `owner`: who owns remediation (e.g. `platform`)
- `service`: the subsystem (e.g. `mimir`, `flux`, `longhorn`, `cert-manager`, `apps`, `synthetics`)

Conditional:

- `namespace`: only when it changes who responds or what to do next
- `remote_name`: only if the alert is truly per-remote (remote_write, etc)

Never label on:

- `pod`, `container`, `instance`, `endpoint`, high-churn IDs

### Required annotations (human-facing)

These annotations are *human-facing* and should be optimized for reading in chat.

Required:

- `summary`: one line, includes the key scope
- `description`: short paragraph + bullet triage
- `runbook_url`: first click
- `dashboard_url`: second click

Optional (only if the link is stable and useful):

- `logs_url`: Loki Explore link / log dashboard for the owning service
- `silence_url`: pre-filled silence creation link (prefer generating via Alertmanager template)
- `ticket_url`: link to a ticket/runbook workflow if you have one

### Message structure (recommended)

For chat targets (Discord), the message should be formatted like this:

#### Header (always shown)

- Status, alert name, and severity
- Cluster + owner + service
- The key scope dimension (namespace / remote / endpoint) only if it changes the action

#### Body (compact, consistent)

1) Summary (1 line)

2) Impact (1–2 lines)

3) Likely causes (2–4 bullets)

4) First actions (2–4 bullets)

5) Links:

- Runbook
- Dashboard
- Alert context (Alertmanager)
- Silence

### YAML template (copy/paste)

Use this for new PrometheusRule alerts.

```yaml
- alert: <PascalCaseName>
   expr: |
      <promql>
   for: <duration>
   labels:
      severity: <info|warning|critical>
      owner: <platform|...>
      service: <mimir|flux|longhorn|cert-manager|apps|synthetics|...>
      # namespace: <only if it changes routing/action>
      # remote_name: <only if truly per-remote>
   annotations:
      summary: "<What is failing> (<scope>)"
      description: |
         What's happening:
         - <one line describing the symptom in plain English>

         Impact/risk:
         - <one line describing the impact>

         Likely causes:
         - <cause 1>
         - <cause 2>
         - <cause 3 (optional)>

         First actions:
         - <check 1>
         - <check 2>
         - <check 3 (optional)>
      runbook_url: "https://backstage.${SECRET_DOMAIN}/docs/default/component/homelab-cluster/runbooks/#<anchor>"
      dashboard_url: "https://grafana.${SECRET_DOMAIN}/d/<uid>/<slug>"
      # logs_url: "https://grafana.${SECRET_DOMAIN}/explore?..."
```

### How to choose `severity` (only what makes sense)

Use severities to communicate **urgency**, not “how bad it feels”.

- `critical`: ongoing user impact, active data loss (e.g. dropping metrics/traces/logs), or imminent, high-confidence outage (e.g. cert expires <24h)
- `warning`: degradation, elevated risk, or near-term action needed, but not currently catastrophic
- `info`: informational events that should not wake anyone up

If you can't defend a `critical` as “act now or regret it”, it's `warning`.

### Scope rules (how specific to be)

Good scope enables fast triage without creating alert floods.

- Prefer **one alert per service/namespace** over one per pod.
- Prefer **one alert per remote_name** when debugging remote write.
- Only include high-cardinality labels in the *message body* (via the `GeneratorURL`/query link), not as labels.

### Worked examples (what “good” looks like)

#### Example A: backlog (warning)

- `summary`: “Prometheus remote_write backlog (mimir)”
- `impact`: “Long-term metrics may become delayed; drops indicate loss.”
- `first actions`: “Check dropped/failed samples; check Mimir gateway health; check Prometheus logs for 429/5xx.”

#### Example B: data loss (critical)

- `summary`: “Prometheus remote_write is dropping samples (mimir)”
- `impact`: “Long-term metrics are incomplete right now.”
- `first actions`: “Treat as Mimir ingestion incident first; verify gateway errors/overload; verify network/DNS.”

## Ownership + maintenance

- Every alert should have an owner (team/component) even if it's just “platform”.
- Every alert should be reviewed after the first real incident:
  - Was it timely?
  - Was it actionable?
  - Did it have the right links?
  - Did it page/chat the right people?

## Alert quality checklist

An alert is “good enough to ship” if:

- It indicates a real failure mode, not normal variance.
- It has a clear next action.
- It includes a runbook link.
- It won't flap (appropriate `for:` and stable signal).
- It's scoped correctly (not one alert per pod unless that's required).
