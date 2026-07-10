# VictoriaLogs replaces Loki as the logging backend

* Status: accepted
* Date: 2026-07-10

Technical Story: [rfc-observability-pipeline](../rfc/rfc-observability-pipeline.md) — which
recorded VictoriaLogs as the natural post-ADR-0034 candidate for the log backend; also subsumes
the retroactive "Loki as log backend" ADR that roadmap item #71 asked for, by documenting the
Loki-era context here.

## Context and Problem Statement

Metrics moved to VictoriaMetrics ([ADR-0034](adr-0034-victoriametrics-metrics-backend.md)), but
logs still flowed to Loki: a SingleBinary deployment with 30d retention on Garage S3
(`loki-chunks`/`loki-ruler`/`loki-admin` buckets), a 10Gi Longhorn WAL/scratch PVC, an nginx
`loki-gateway` hop, and ~200m/512Mi–2CPU/1.5Gi of resources. The RFC flagged it as unauthenticated
and single-replica, and its S3 dependency put Garage on the logging path's critical chain — when
Garage was down, logging was down. Should logs move onto the VictoriaMetrics stack too?

## Decision Drivers

* One operator (vm-operator, already at chart 0.65.1 / operator v0.72.0, which serves the
  `VLSingle` CRD) instead of a second Helm-managed log stack.
* Remove Garage S3 from the logging path (availability) and the loki-gateway hop (simplicity).
* Resource pressure on the small worker pool — VictoriaLogs runs in roughly half of Loki's
  footprint for this ingest volume (~21 KB/s ≈ 1.8 GB/day raw, measured over 7d).
* VictoriaLogs natively ingests the Loki push protocol, so both Alloy shippers keep their
  `loki.write` pipelines — only the endpoint URL changes; no collector migration.
* Cost: query language changes from LogQL to LogsQL — every log panel (63 targets across 14
  dashboards) needs translation, and the Grafana MCP server's Loki query tools stop working.

## Considered Options

* VictoriaLogs (VLSingle via vm-operator), swap with a read-only Loki grace period
* Keep Loki SingleBinary as-is
* Dual-write parallel run with gradual dashboard migration

## Decision Outcome

Chosen option: "VictoriaLogs with a read-only Loki grace period", because it unifies observability
on the operator already running, removes the Garage and gateway dependencies, halves the resource
bill, and the Loki-protocol ingest makes the shipper cutover a one-line URL change — while the
grace period keeps the existing 30d of history queryable until it ages out.

Load-bearing specifics:

* `kubernetes/apps/observability/victorialogs/` — `VLSingle` (apiVersion
  `operator.victoriametrics.com/v1`, **not** v1beta1 like VMSingle), `retentionPeriod: 30d`
  matching Loki's 720h, 20Gi Longhorn PVC (measured 30d volume compresses to ~2–6 GB; safety
  valve `retention.maxDiskSpaceUsageBytes: 18GiB`), worker-pool placement. Endpoint
  `vlsingle-victorialogs.observability.svc:9428`; vmui exposed at `victorialogs.<domain>`
  (LAN-only). Alerts in `app/prometheusrule-victorialogs.yaml` (down / **no-ingest tripwire** /
  disk / http errors; metric names verified against live `/metrics`).
* Shippers: `alloy-agent` and `alloy-gateway` `loki.write` URLs → VictoriaLogs
  `/insert/loki/api/v1/push?_stream_fields=…` (per-pipeline stream-field lists pin the previous
  Loki stream shape; VictoriaLogs' default — all labels — is the identical fallback).
* Grafana: `victoriametrics-logs-datasource` plugin (via `GF_INSTALL_PLUGINS`), new
  `GrafanaDatasource` uid `victorialogs`; all 14 LogQL dashboards rewritten to LogsQL
  (queryType mapping: logs→`instant`, `[$__range]` aggregations→`stats`,
  `[$__interval]`→`statsRange`).
* MCP: `kubernetes/apps/observability/mcp-victorialogs/` (official
  `ghcr.io/victoriametrics/mcp-victorialogs`, streamable HTTP `/mcp`, wired into `.mcp.json`)
  replaces the Grafana MCP Loki tools as Claude's log-query path.
* Grace period: Loki stays deployed **read-only** (no new writes) with its `loki` Grafana
  datasource until ~**2026-08-07** (~4 weeks), then a removal commit deletes
  `kubernetes/apps/observability/loki/`, the loki datasource, and repoints Tempo's
  `tracesToLogsV2` to `victorialogs` (custom LogsQL query — the auto-builder is Loki-only);
  out-of-repo cleanup: PVC `storage-loki-0` and the three Garage buckets. The shared
  `observability-s3` component **stays** (suspended Tempo consumes it).

### Positive Consequences

* Garage S3 and loki-gateway are off the logging critical path; logs keep flowing during object
  storage incidents.
* One CRD-driven observability stack; scrape + dashboards + alerts follow the existing VM pattern
  (the operator auto-created the `VMServiceScrape`).
* ~½ the CPU/memory reservation, no S3 storage growth; 30d of logs fits in single-digit GiB.
* First-class log access for agents via mcp-victorialogs (LogsQL, field/stream discovery APIs).

### Negative Consequences

* LogsQL ≠ LogQL: word-tokenized phrase filters can silently change panel semantics vs LogQL
  substring filters (mitigated by using regex filters where token alignment was unclear, and by
  live-verifying every translated query); `or vector(0)` has no equivalent (panels use
  `noValue: "0"`).
* History gap by design: rewritten dashboards only show data from cutover (2026-07-10 03:45Z);
  older history is Explore-only via the Loki datasource until removal.
* Local-PVC-only storage: log durability now rides on Longhorn replication instead of S3.
* Grafana MCP's `loki` tools go dead at Loki removal (replaced by mcp-victorialogs).

## Pros and Cons of the Options

### Keep Loki SingleBinary

* Good, because zero migration effort and LogQL is widely documented.
* Bad, because it keeps Garage + gateway on the critical path, a second stack to operate, and
  ~2× the resource bill.

### Dual-write parallel run

* Good, because dashboards migrate with zero pressure and continuous back-to-back comparison.
* Bad, because weeks of double resource usage and double failure surface for a one-person lab;
  the grace-period swap gets the same safety with none of the dual-write complexity.

## Links

* Refines [ADR-0034](adr-0034-victoriametrics-metrics-backend.md) — extends the VictoriaMetrics
  consolidation from metrics to logs
* [rfc-observability-pipeline](../rfc/rfc-observability-pipeline.md) — pipeline inventory that
  named this alternative
* Runbook: [victorialogs](../runbooks/victorialogs.md)
* 2026-07-10 — VLSingle deployed alongside Loki (e3fafc74)
* 2026-07-10 — alloy ingest cut over; Loki read-only, grace period until ~2026-08-07 (699325db)
* 2026-07-10 — accepted; datasource, mcp-victorialogs, dashboard rewrites landed (this change)
