# Information radiators: walls, boards and playlists

What goes on a screen that nobody is looking at directly, why each tile earns its place, and how
to change one. The pattern comes from code14's staging cluster, adapted to what this cluster
actually runs: Forgejo CI, Glide, Flux, Talos, Longhorn, CloudNativePG and the Vikunja roadmap.

## Glossary

| Term | Meaning here |
| --- | --- |
| **Wall** | A one-screen dashboard for a TV: exactly 24 grid rows, at most 12 panels, no rows, no scrolling, no variables to pick. Uid `wall-*` or `alerts-*`, folder **Walls**. |
| **Board** | A desk dashboard someone opens on purpose: a first screen of at most 12 panels, then collapsed rows with the detail. Folder **Boards**. |
| **Playlist** | Grafana's own rotation of dashboards on a timer. Every item is a wall. |
| **Kiosk** | Grafana's full-screen mode (`?kiosk`): no menus, no time picker. |
| **Neutral** | The grey `#898781` every tile shows when things are normal. |
| **Business Text** | The Grafana panel plugin `marcusolsson-dynamictext-panel`. It renders an HTML template over query results after running a JavaScript view model, so one panel can draw a whole designed screen. The Today wall is one. |

## The rules

1. **Grey is normal. Colour means someone acts.** Amber `#e69f00` is "someone should look today",
   vermillion `#d55e00` is "someone acts now". Green `#009e73` appears only where a stated goal is
   met. This is the ISA-101 control-room rule: a grey base is what makes an alarm visible in
   peripheral vision.
2. **Never red against green.** About one man in twelve cannot tell them apart. The palette is
   Okabe-Ito, and the builders refuse any other colour on a kiosk threshold
   ([`scripts/dashboards/lib/tokens.py`](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/scripts/dashboards/lib/tokens.py)).
3. **Colour is never the only channel.** Every tile also carries a number or a word.
4. **Every tile has an action.** Its description says what red means and what to do. A tile
   nobody would act on comes off.
5. **One screen per wall.** The generator refuses a wall taller than 24 rows, with more than 12
   panels, or with overlapping panels, and refuses a playlist item that is not a wall.
6. **Dead sources get no tiles.** Falco, Tetragon and the k6 canaries are suspended, so no wall
   reads them.

## What is on the walls

| Wall | Uid | Answers |
| --- | --- | --- |
| Today | `today` | What landed on the trunks this week, where the work on each board is, wins, and what could use a hand |
| Homelab now | `wall-now` | What is firing, is git what runs, are nodes, endpoints, volumes and backups whole, error budgets |
| Forgejo CI | `wall-ci` | Runner capacity, queue wait, red trunks, running jobs against their usual time, builders, pulls around Harbor |
| Glide | `wall-glide` | Runs and workers, what waits on a person, oldest queued Work Item, failed Runs with cost, model health |
| GitOps and Renovate | `wall-gitops` | Flux readiness, suspensions, drift behind git, Renovate freshness and failures |
| Nodes | `wall-nodes` | Node readiness, pressure, Pending pods, memory and CPU **requested** per node, memory outside kubepods |
| Data and backups | `wall-data` | Longhorn robustness and free space, CNPG backup age and lag, Garage health, backup CronJobs |
| Edge and security | `wall-edge` | Endpoints down, gateway 5xx, certificate expiry, secrets not syncing, Kyverno blocks, Trivy |
| Roadmap | `wall-roadmap` | Vikunja stages per board, do-next, reviews waiting |
| Alerts · Everything and per group | `alerts-all`, `alerts-platform`, `alerts-delivery`, `alerts-data`, `alerts-security`, `alerts-ai` | What is firing that nobody silenced |

The Forgejo CI and Glide walls are the **first screens** of the desk boards `forgejo-ci` and
`glide-plant`, built from the same panel functions, so a wall and its board can never disagree.

## The Today wall

`/d/today` is one Business Text panel across all 24 rows, ported from code14's Team C wall: the
same night-blue ground, typefaces and layout, drawn from this cluster's sources. It answers three
questions for whoever writes code here: what landed, where the work is and how fast it flows, what
the machine did, and what needs a hand.

| Band | Shows | Source |
| --- | --- | --- |
| Top | `Week N · Mon – Sun · day N of 7`, commits landed on default branches this week, repositories, merged pull requests, releases, commits by bot accounts, and last week's count **up to the same moment** of the week. A push of more than 100 commits is a history import: it is named on its own and kept out of both counts | Forgejo database (`action`) |
| Where the work is | One track per board: Backlog → To do → Doing → Reviewing → Done this week, stages derived from labels as ADR-0043 defines them. Under the board name: tickets in and out this week (amber when arrivals are more than twice the closes), and the lead time 85 % of closed tickets met over 28 days, created to done. Under Doing and Reviewing: how long the oldest ticket has held that stage's label, amber once it is past the board's 85th percentile | Vikunja database (`tasks`, `label_tasks`) |
| Wins this week | Longest run of green trunk runs per workflow (shown from two), agent pull requests merged with the latest title, tickets closed per board | Forgejo `action_run`, `pull_request`, Vikunja |
| The machine this week | **CI now**: jobs running, jobs queued (KEDA), runner pods and Pending runner pods. **Agents**: Unfold Runs this week by role, running, work items, pull requests `agent-builder` opened and merged, and the share of its closed pull requests that merged over 28 days. **AI spend**: LiteLLM spend and tokens this week and today, split per project (Unfold per target repository, Omnigraph, Brain tools). **Error rates**: CI jobs failed (7 days), agent Runs failed or stuck, model calls failed with the worst consumer of at least 20 calls | forgejo-ci-exporter, KEDA, kube-state-metrics, Ploeg database, LiteLLM ledger, Forgejo |
| Just landed | The last six commits on default branches: time, initials, conventional-commit type, title, repository and scope, and the trunk CI verdict of that commit. ✦ marks a push by a bot account | Forgejo `action`, `action_run`, `user` |
| Could use a hand | At most five: critical alerts, red trunks, Flux not ready, Unfold work waiting on a human, board reviews waiting, open pull requests, pull-request pipelines red, bot pull requests | Alertmanager, forgejo-ci-exporter, Flux, ploeg exporter, Vikunja, Forgejo |
| Footer | Whether the Forgejo database answered, CI exporter data age, blackbox probes, Flux | Prometheus |

Things that read wrong if you do not know them:

- **A CI pill on only some feed rows.** Forgejo runs workflows on the last commit of a push.
  Earlier commits in the same push read `in a push`; a commit with no run at all reads `no CI`.
  A run cancelled because a newer push superseded it is skipped when an older run of the same
  commit finished.
- **✦ is not "written with Claude".** Forgejo's activity feed stores only the first line of each
  commit message, so `Co-Authored-By` trailers never reach the database. The mark means the
  pusher is a bot account (Forgejo bot type, or a login matching `AGENT_LOGINS` in
  `scripts/dashboards/today.py`). Claude Code sessions push as the owner and are not marked.
- **AI spend is LiteLLM's ledger, not a bill.** Every agent model call goes through LiteLLM, which
  prices it from its own model table. Each Unfold Run has its own key, `ploeg-` and the first 12
  characters of its run token, so the wall joins LiteLLM's spend per key to Ploeg's Run records to
  name the repository. A key whose Run started before this week reads `Unfold · earlier Run`.
  Claude Code sessions billed by subscription cost nothing in the ledger and are left off the bars.
- **Lead time is created to done**, because Vikunja deletes a label row when the label comes off:
  how long a ticket sat in a stage it has left cannot be read back, only how long the current
  stage has held. Lead times are bimodal here (half the Homelab Roadmap closes within a day, the
  85th percentile is about 70 days), which is why the wall shows the 85th percentile and no average.
- **Warnings alone never make an ask.** Only critical alerts interrupt the wall (rule 1); the
  alert walls show warnings.

How it is built: `scripts/dashboards/today.py` embeds `today_wall/wall.hbs` (template),
`wall.css` (styles) and `wall.js` (view model) into the panel. The generator refuses a `$` in any
of them, because Grafana reads `$` as a dashboard variable, and refuses to build unless
`GF_INSTALL_PLUGINS` in `grafana-instance.yaml` installs the exact plugin version the panel pins.
`node --test scripts/dashboards/today_wall/wall.test.mjs` runs the view model as it ships (read
out of the generated CR) over frames recorded from a Forgejo 15 and Vikunja 2.6 instance; CI's
Lint job runs it.

The Ploeg and LiteLLM numbers come from the `ploeg-db` and `litellm-db` datasources (read-only
roles that already existed). The Forgejo numbers come from the `forgejo-db` Grafana datasource,
logged in as `grafana_ro`.
That role is **not** `pg_read_all_data`: the Forgejo database holds password hashes and runner
tokens, so an hourly CronJob in the `forgejo` namespace grants SELECT on exactly the columns the
wall reads (`grafana-ro-grants.cronjob.yaml`). It runs hourly because a Forgejo migration that
recreates a table drops its grants. A panel that reads "The Forgejo database did not answer"
means the datasource, the role or the grants are missing.

## Playlists and kiosk URLs

| Playlist | For | Rotation | Turns every |
| --- | --- | --- | --- |
| **Wall · Homelab** | the default TV | now, Today, alerts, CI, now, Glide, GitOps, now, data, nodes | 1 minute |
| **Wall · Delivery** | a TV next to where code gets written | Today, CI, Glide, Today, delivery alerts, GitOps, AI alerts | 1 minute |
| **Incident · Platform** | any TV during an incident | alerts, now, nodes, edge, data | 30 seconds |
| **Weekly · Review** | the weekly look back | Today, roadmap, CI, Glide, GitOps, data, edge, nodes, security alerts | 2 minutes |

Homelab now appears three times in its loop, so the board that says whether anything is wrong
is never more than two boards away. Rotation removes information before it is read (engagement
falls from about 40 % on the first carousel item to 11 % on the last), and the weighting is the
mitigation.

The uid of each playlist is set in git, so the URLs never change:

```text
https://grafana.<domain>/playlists/play/wall-homelab?kiosk
https://grafana.<domain>/playlists/play/wall-delivery?kiosk
https://grafana.<domain>/playlists/play/incident?kiosk
https://grafana.<domain>/playlists/play/weekly-review?kiosk
```

A single wall plays at `https://grafana.<domain>/d/<uid>?kiosk`.

Grafana requires a login (Authentik). A TV signs in once as a `homelab-users` member and keeps
the session.

## How it works

Everything is generated by one script from Python panel builders:

```sh
python3 scripts/dashboards/generate.py          # write every generated file
python3 scripts/dashboards/generate.py --check  # fail when a committed file is stale
```

| Path | What |
| --- | --- |
| `scripts/dashboards/lib/` | Palette, panel builders, grid layout, the `GrafanaDashboard` emitter and `$$` escaping |
| `scripts/dashboards/forgejo_ci.py` | The Forgejo CI board and its wall |
| `scripts/dashboards/glide.py` | The Glide plant board and its wall |
| `scripts/dashboards/platform_walls.py` | Now, GitOps, nodes, data, edge and roadmap walls |
| `scripts/dashboards/alerts.py` | The alert walls |
| `scripts/dashboards/today.py`, `today_wall/` | The Today wall: queries, and the Business Text template, styles and view model |
| `scripts/dashboards/playlists.py` | The four playlists |
| `kubernetes/apps/observability/grafana/app/dashboards/*.generated.yaml` | Output: `GrafanaDashboard` CRs |
| `kubernetes/apps/observability/grafana/app/playlists/playlists.generated.yaml` | Output: one `GrafanaManifest` per playlist |

**Playlists are `GrafanaManifest` CRs.** Grafana 13 serves playlists as an App Platform kind
(`playlist.grafana.app/v1`), and grafana-operator 5.24's `GrafanaManifest` applies any App
Platform object. So a playlist is reconciled like every other Grafana resource, Flux prunes it
when it leaves git, and its uid (`metadata.name` of the template) is chosen here. code14's
staging cluster uses an hourly CronJob with an Editor token instead, because its operator
predates `GrafanaManifest`.

**Alert walls read Alertmanager, not `ALERTS`.** The live counts and the Firing now table come
from Alertmanager's API through the Infinity datasource `alertmanager-api`, with
`silenced=false&inhibited=false`, so a silence clears every wall at the next refresh. Grouping
happens in the JSONata root selector: an alert belongs to a group by its `service` label
(vmalert rules) or its `grafana_folder` label (Grafana-managed SLO rules). Two kinds of alert are
dropped everywhere: the Watchdog heartbeat, which has its own tile, and copies whose
`job="opencost"`. OpenCost re-exports kube-state-metrics series, so every `KubeJobFailed` fires
twice.

**The CI capacity numbers come from git.** The runner ceiling and warm floor on the CI board are
read from the `forgejo-runner` ScaledJob manifest at generation time, because no metric exposes
them. The pre-commit hook re-runs `--check` when that manifest changes.

## Changing a panel

1. Edit the builder in `scripts/dashboards/`, never the generated YAML. Write plain Grafana
   tokens (`$repo`, `$__range`): the emitter doubles every `$` for Flux's envsubst, and passes
   `${SECRET_DOMAIN}` through untouched.
2. Run `python3 scripts/dashboards/generate.py`. It refuses a wall that is not one screen.
3. Run every new query once against the live backend, and once more against a moment when it
   must return rows (an inverted condition, or a past incident). An empty panel is not proof
   that the query works.
4. Commit the builder and the generated files together. CI's Lint job runs `--check`.

## When a tile looks wrong

| Symptom | Likely cause |
| --- | --- |
| Every alert count is 0 but alerts are firing | A JSONata comparison against a missing label is false, not true. Guard absent labels with `$not($exists(...))` |
| A KSM-based tile is empty | kube-state-metrics series carry the real namespace in `exported_namespace`, and OpenCost duplicates some of them. Pin `job="kube-state-metrics"` |
| A node join returns nothing | cAdvisor's `instance` is the node name, node-exporter's is `IP:9100`. Join cAdvisor on `node`, node-exporter through `node_uname_info` |
| A panel shows "No data" after a Flux reconcile | A single `$` was blanked by envsubst. Regenerate; never hand-edit the YAML |
| The Glide "ploegd gauges" row says "ploegd not scraped" | The ploeg chart's ServiceMonitor is off, or its scrape is failing |
| Run wall-clock looks worse than time to green | It is every run, every outcome and event: the exporter's histogram has no status label |

## Known gaps

- **No per-job queue wait or failure reason for Forgejo CI.** Forgejo stamps a task with its
  run's start time and records no failure reason. The `forgejo-db` datasource reads `action_run`
  for the Today wall; granting `action_run_job` and `action_task` as well would add flaky jobs,
  retries and per-job queue wait.
- **No BuildKit cache hit ratio.** Job step output never reaches VictoriaLogs, and the BuildKit
  daemons export no metrics.
- **Claude Code telemetry has not arrived since 2026-09-26**, so there is no Claude Code wall yet.
- **The Roadmap wall is SQL against Vikunja** and was written against Vikunja's schema without a
  live run. Check it in the browser after a schema change.

## Related

- [Forgejo CI telemetry](forgejo-ci-telemetry.md): where every CI number comes from
- [Observability](observability.md): the metrics, logs and traces stack
- [Alerting principles](alerting-principles.md)
