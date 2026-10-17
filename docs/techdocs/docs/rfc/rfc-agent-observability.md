# RFC: Observability for the agent estate — one key, three questions, no silent sources

> Status: **Proposed** · Date: 2026-10-17 · Builds on Ploeg
> [ADR-0076](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0076-run-health-is-observable-by-team-and-role-through-one-correlation-key.md),
> [LiteLLM feature adoption](rfc-litellm-feature-adoption.md) W1.4 and the
> [observability pipeline](rfc-observability-pipeline.md)

> **TL;DR.** Claude Code, Cowork, Ploeg, Unfold and LiteLLM all report into one Alloy gateway,
> but they cannot be read together and nothing notices when one goes quiet. Claude Code sent
> nothing for at least 20 days and no alert fired. Adopt Ploeg's Run alias `ploeg-<12hex>` as
> the one correlation key across the estate, put it on every signal that belongs to a Run, and
> add an absence alert per source. Five tickets do it; three already existed.

## Why

On 2026-10-17 the Claude org's Cowork monitoring was pointed at the homelab and the question
"do we already send things there" turned up:

- **Claude Code had never exported.** Claude Code ignores `CLAUDE_CODE_ENABLE_TELEMETRY` and
  `OTEL_EXPORTER_OTLP_*` in a repository's `.claude/settings.json`
  ([docs](https://code.claude.com/docs/en/settings-reference#variables-claude-code-ignores-in-env)).
  The alloy-gateway pod, 20 days up, had accepted 0 OTLP log records and 0 metric points. Three
  Claude Code dashboards were empty and looked like "nobody used it".
- **Each source speaks for itself.** LiteLLM exports spans and metrics keyed by `key_alias`.
  Ploeg exposes Prometheus metrics with Team and Role but no OTLP. Unfold sends error logs and
  Faro events with `work_item.id` and `shift.id` but no Run. Nothing joins a Cowork session, a
  Ploeg Run and the LiteLLM calls it paid for.
- **Silence reads as health.** `absent()` coverage exists for seven jobs, none of them in the
  agent estate. The dark-factory SLO alerts set `noDataState: OK`.

## What flows where (2026-10-17)

| Source | Signal | Path in | Lands in |
|---|---|---|---|
| Claude Code (owner) | metrics, events | `otlp.${SECRET_DOMAIN}` (LAN, no auth) | VictoriaMetrics, VictoriaLogs |
| Claude Code (org members), Cowork, Office Agents | metrics, events | `otlp-ingest.${SECRET_DOMAIN}` (public, `x-otlp-token`) | VictoriaMetrics, VictoriaLogs |
| LiteLLM | spans | alloy-gateway :4317 in-cluster | VictoriaTraces (+ span metrics) |
| LiteLLM | metrics | scrape :4001 + SQL exporter | VictoriaMetrics |
| Ploeg | metrics | scrape `/metrics` + SQL exporter | VictoriaMetrics |
| Ploeg | logs | stdout → alloy-agent (logfmt fields) | VictoriaLogs |
| Unfold | error reports | alloy-gateway :4318 in-cluster | VictoriaLogs |
| Unfold | insight events | alloy-gateway Faro :12347 | VictoriaLogs |

Endpoint mechanics: [observability → Claude Code and Cowork telemetry](../general/observability.md#claude-code-and-cowork-telemetry).

## The three questions

Every signal earns its place by answering one of these.

1. **What did this piece of work cost, and where did the money go?** A Run, a Cowork session or
   a Claude Code session to its model calls and their spend.
2. **Where does a Run get stuck or slow?** Phases, waits and failures per Team and Role.
3. **Is every source still reporting?** A source that goes quiet pages before a dashboard
   misleads someone.

## Decision

### Correlation key

The Run alias `ploeg-<first 12 hex of run_token>` is the estate's correlation key for agent
work. It already is LiteLLM's `key_alias`, the SQL exporters' join and Ploeg's log `trace`
field (ADR-0076). Each signal that belongs to a Run carries it under one name per signal type:

| Signal | Field |
|---|---|
| Ploeg logs | `trace` (logfmt) → VictoriaLogs `trace_id` |
| LiteLLM spend and spans | `key_alias`; `x-litellm-trace-id` when Ploeg's proxy sends it |
| Ploeg spans | attribute `ploeg.run.alias` |
| Unfold events | attribute `ploeg.run.alias` |

The full `run_token` never leaves Ploeg. Claude Code and Cowork sessions are not Runs. They join
on `session.id` and `organization.id`, which Claude Code already sets.

### Silence

Each source gets an `absent_over_time` warning on a signal that always flows while it is alive,
with a window matched to how bursty it is: minutes for the gateway's intake, hours for LiteLLM
spans, days for usage-driven Claude Code. SLO rules alert on no data rather than reading it as OK.

### What stays out

- **Prompt content org-wide.** The org's managed settings export usage, cost and tool events,
  not `OTEL_LOG_USER_PROMPTS`. Collecting colleagues' prompts is a privacy decision (GDPR, and
  possibly the works council), not a default.
- **Harness environment.** Ploeg's worker passes the agent an allowlisted environment
  (`pkg/worker/environment.go`), so telemetry for OpenHands, opencode and Claude Code under Ploeg
  needs a Ploeg setting (VIK-2148), not pod env. opencode has no native OTLP export.
- **A tracing SDK in the Ploeg worker.** ADR-0076 keeps sandbox egress closed; worker spans
  relay through ploegd.
- **Retention, profiles, Kepler.** These stay with the [pipeline RFC](rfc-observability-pipeline.md).

## Work

| Question | Ticket | Repo | State |
|---|---|---|---|
| 3 | [VIK-2133](https://vikunja.webgrip.dev/tasks/2133) absence alerts per source, SLO no-data | homelab-cluster | new |
| 1 | [VIK-2134](https://vikunja.webgrip.dev/tasks/2134) Claude Code dashboards on live data | homelab-cluster | new |
| 1, 2 | [VIK-2135](https://vikunja.webgrip.dev/tasks/2135) map Ploeg's `run` log key | homelab-cluster | new |
| 1 | [VIK-2136](https://vikunja.webgrip.dev/tasks/2136) Run alias on Unfold events | unfold | new |
| 1 | [VIK-1273](https://vikunja.webgrip.dev/tasks/1273) LiteLLM call tags from Ploeg's proxy | ploeg | existing |
| 2 | [VIK-1580](https://vikunja.webgrip.dev/tasks/1580) OTel spans per Run | ploeg | existing |
| 2 | [VIK-560](https://vikunja.webgrip.dev/tasks/560) epic: each Run readable as a trace | ploeg | existing |
| 1 | [VIK-2053](https://vikunja.webgrip.dev/tasks/2053) public OTLP ingest for org telemetry | homelab-cluster | deployed, in review |
| 1, 2 | [VIK-2148](https://vikunja.webgrip.dev/tasks/2148) harness telemetry as a setting per team, role and harness | ploeg | new |
| 1, 2 | [VIK-2149](https://vikunja.webgrip.dev/tasks/2149) the chart deploys the Claude runner, every limit a setting | ploeg | new |
| 1, 2 | claude-runner sessions export metrics, logs and traces, in a Kata VM (3550fcef, f0d2e8d2, a56e8b10) | homelab-cluster | deployed |

VIK-1273 is labelled `repo/unfold` and points at `apps/ploeg` in `webgrip/unfold`. Ploeg's
active trunk is [ploeg-hq/ploeg](https://github.com/ploeg-hq/ploeg) `development`, so its label
needs the owner's call before an agent picks it up.

## Confirmation

- Each absence rule is mutation-tested: it fires over a window where its source is known absent
  (Claude Code before 2026-10-17) and stays quiet over one where it reports.
- One Ploeg Run can be followed by alias from a VictoriaLogs query, through LiteLLM spend rows,
  to a VictoriaTraces trace, in a single Grafana run-explorer view.
- The `blackbox-alloy-gateway-otlp-ingest` probe stays green; it fails when the public route or
  its token gate disappears.
