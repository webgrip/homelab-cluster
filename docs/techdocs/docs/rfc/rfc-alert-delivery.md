# RFC: Alert delivery — no alert currently reaches a human

> Status: **Proposed** · Date: 2026-07-02 · Part of the [decision-landscape gap register](../adr/landscape.md)

> **TL;DR.** Both alerting planes terminate in the void. VMAlertmanager's only receiver is
> **`"null"`** ("no paging wired up yet" — its own comment); Grafana has **zero contact points**,
> so its SLO alerts render only in the UI. Everything upstream — rule shape, lint, meta-monitoring,
> the Watchdog deadman — was fixed by the [alerting-reliability RFC](rfc-observability-alerting-reliability.md),
> which explicitly left routing out of scope. This RFC closes the last leg: pick a channel, wire
> both planes into it, and close the deadman loop end-to-end.

## Why

The 3-week silent alert outage (2026-05-30 → 06-21) taught the cluster to watch its watchers:
ADR-0035 linted the rule shape, ADR-0036 added the page-on-failure meta-rule. But "page" is
figurative — verified 2026-07-02:

- **VMAlertmanager** (`victoria-metrics/app/vmalertmanager.yaml`): a single `"null"` receiver;
  every route, including the `Watchdog` deadman that ADR-0034 carefully re-fed, delivers nowhere.
- **Grafana**: no `GrafanaContactPoint` or `GrafanaNotificationPolicy` exists in the repo; the
  16 SLO rules — including `slo-grafana-alert-rule-eval-failing`, the meta-rule designed to page —
  fall through to Grafana's unconfigured default contact point.

So a Longhorn volume fault, a CNPG cluster down, a full disk, or a repeat of the alert-evaluation
outage would today be discovered the same way the last one was: by someone happening to look.
Every alerting investment upstream is stranded on this missing last mile. The
[alerting-principles doc](../general/alerting-principles.md) already defines severities, labels,
and message templates *for* a delivery layer that doesn't exist.

## Proposal

1. **Pick one notification channel, self-hosted, phone-capable** (new ADR). The weighing:
   - **ntfy (self-hosted, in-cluster)** — aligns with the sovereignty program, great mobile app,
     trivially wired to both planes via webhook/HTTP. One wrinkle to solve honestly: an
     *in-cluster* notifier can't report the cluster's own death — mitigated by the deadman leg
     below, or by hosting ntfy on the Garage box instead of in-cluster.
   - **Pushover / Telegram / e-mail** — zero-ops external channels; less sovereign, fine as a
     fallback leg.
   Recommendation: self-hosted ntfy as primary, plus one external leg for `severity: critical`
   (dual-channel only where it matters).
2. **Wire both planes** (same ADR): VMAlertmanager `configRawYaml` gains real receivers with
   routing by the `severity` label per alerting-principles (critical → both legs; warning →
   ntfy; info → nowhere by design); Grafana gets `GrafanaContactPoint` +
   `GrafanaNotificationPolicy` CRs targeting the same endpoints — one delivery decision, two
   consumers. Long-term the two planes could consolidate (VMAlert evaluating everything), but
   that is deliberately *not* this RFC.
3. **Close the deadman end-to-end** (new ADR): the `Watchdog` alert routes to an **external
   heartbeat service** (healthchecks.io free tier, or self-hosted uptime-kuma on the Garage box) —
   silence for >N minutes means the cluster, its alerting, or its network is gone, and the *absence*
   pages. This is the only alert class that must not depend on any in-cluster component.
4. **Acceptance is a real page**: a synthetic `severity: critical` alert fired from each plane
   must reach the phone; the Watchdog heartbeat must page when deliberately silenced. (The
   alerting-reliability RFC's lesson: render success proves nothing — only the end-to-end signal
   counts.)

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Notification channel(s) + severity routing, wired to both alerting planes (new) |
| candidate | — | External deadman heartbeat for the Watchdog (new) |

## Out of scope

- Alert rule content, shape, health — done ([ADR-0035](../adr/adr-0035-grafana-threshold-rule-shape.md)/[0031](../adr/adr-0036-meta-monitoring-alert-rule-health.md)).
- Consolidating the two alerting planes into one — worth considering *after* delivery exists.
- Paging schedules/escalation (single-operator homelab: everything routes to the same human).

## References

- [alerting-principles](../general/alerting-principles.md) — severity/label taxonomy this RFC routes by
- [RFC: observability alerting reliability](rfc-observability-alerting-reliability.md) — explicitly
  deferred delivery here
- [ADR-0034](../adr/adr-0034-victoriametrics-metrics-backend.md) — restored the Watchdog feeding alert
