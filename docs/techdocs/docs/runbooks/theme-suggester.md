# Theme suggester

An hourly CronJob (`vikunja/theme-suggester`) that asks the in-cluster Laya classifier
(`ai/laya`) which `theme/*` label a ticket belongs to. It speaks the Jev API, runs on CPU, and
sends no ticket text outside the cluster. Background: [Laya spike](../rfc/spike-laya-classifier.md),
[ticket sizing RFC](../rfc/rfc-jev-ticket-sizing.md) §11, VIK-1448.

## Load

Laya runs on a high-CPU worker (required affinity `node.webgrip.io/cpu: high`, never
fringe-workstation) at about 2–4 s per ticket on 4 threads. Each hourly run evaluates one
rotating slice of tickets (`ticket id % ROTATION == UTC hour % ROTATION`, default 6) capped at
`MAX_EVALUATIONS` (default 60), so a full shadow pass takes `ROTATION` hours and no run nears
the 45-minute deadline. The first shadow run on 2026-09-29 made 200 calls on a 4-core worker at
13 s each and was killed at its deadline; that is what the slice and the placement prevent.

## Modes

| `MODE` | What it does |
| --- | --- |
| `shadow` (default) | Reads the boards and predicts the theme of every open ticket created in the last `LOOKBACK_DAYS` that a human already themed. Writes nothing. Logs one `shadow` line per ticket and a `summary` line with agreement and, per confidence threshold, coverage and precision. |
| `apply` | Also handles open tickets without a theme: above `APPLY_THRESHOLD` it sets the label and comments; below it, it comments the top three. Each ticket is handled once (marker `theme-suggester:v1` in the comment). |

Switch to `apply` only after shadow data shows the chosen threshold holds (owner decision,
2026-09-29: apply the label when very sure, after a shadow period).

## Identity

It uses the owner's existing API token from OpenBao (`vikunja/mcp`, property `api_token`), the
same token the Vikunja MCP server, Ploeg and the agent runner use. No extra Vikunja account is
needed (owner decision, 2026-09-29). Its writes therefore appear as the owner; every comment it
writes carries the `theme-suggester:v1` marker. A dedicated bot user is a one-line change of the
ExternalSecret's `remoteRef` if that is ever wanted.

## Read the shadow results

VictoriaLogs, LogsQL:

```text
kubernetes.namespace:vikunja kubernetes.container:suggest event:summary
```

Pick the lowest threshold whose `precision` meets the target (0.95 for automatic labels) with a
useful `coverage`, set `APPLY_THRESHOLD` to it and `MODE: apply` in
`kubernetes/apps/vikunja/theme-suggester/app/cronjob.yaml`.

## Failures

| Log event | Meaning | Fix |
| --- | --- | --- |
| `no_vikunja_token` | The token file is empty or absent | Restore `vikunja/mcp` `api_token` in OpenBao |
| `control_failed` | Laya answered the built-in control question wrongly | Check `kubectl -n ai logs deploy/laya`; a new image or checkpoint may be broken, so roll back the image pin |
| `empty_scan` | The boards returned no tasks | The token is revoked or the boards are not shared with the bot user |
| `board_skipped` | A board has fewer than two themes with `MIN_THEME_TICKETS` tickets | Expected on small boards |

The `ThemeSuggesterStale` alert fires after 3 h without a successful run.
