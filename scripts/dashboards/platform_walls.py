from __future__ import annotations

import alerts
from lib import (AMBER, CAT, GREEN, NEUTRAL, SKY, VERMILLION, alarm_at, bars, col, color_overrides, dashboard,
                 doc_link, grid_pos, kiosk_steps, link, low_is_bad, number, sql, stat, table, target, timeseries)

FOLDER = "walls"
DOC = "docs/techdocs/docs/general/information-radiators.md"
KSM = 'job="kube-state-metrics"'
HOUR = 3600
DAY = 86400
BACKUP_LATE = 26 * HOUR
BACKUP_CRONJOBS = 'cronjob=~".*(backup|snapshot).*"'
VIKUNJA = {"type": "grafana-postgresql-datasource", "uid": "vikunja-db"}
BOARD_PROJECTS = {3: "Homelab Roadmap", 6: "Vellum", 9: "CI/CD", 10: "Unfold"}


def place(placed):
    panels = []
    for panel, x, y, w, h in placed:
        panel["gridPos"] = grid_pos(x, y, w, h)
        panels.append(panel)
    return number(panels)


def wall(uid, title, placed, *, description, links=None, refresh="1m", time_from="now-24h"):
    return dashboard(uid, title, place(placed), tags=["wall"], kiosk=True, refresh=refresh, time_from=time_from,
                     description=description, links=(links or []) + [doc_link("Information radiators", DOC)])


def flux_not_ready():
    return stat("Flux not ready", 'count(flux_resource_info{ready="False", suspended="False"}) or on() vector(0)',
                decimals=0, thresholds=alarm_at(vermillion=1),
                desc="Flux objects (Kustomizations, HelmReleases, sources) reporting Ready=False. Git is no longer "
                     "what runs. `flux get all -A --status-selector ready=false` names them and the reason.")


def nodes_not_ready():
    total = f"count(kube_node_info{{{KSM}}})"
    ready = f'sum(kube_node_status_condition{{{KSM}, condition="Ready", status="true"}})'
    return stat("Nodes not ready", f"{total} - {ready}", decimals=0, thresholds=alarm_at(vermillion=1),
                desc="Kubernetes nodes whose Ready condition is not true. Anything on them is being evicted or is "
                     "already gone; the Talos node-drain playbook covers the recovery.")


def probes_failing():
    return stat("Endpoints down", "count(probe_success == 0) or on() vector(0)", decimals=0,
                thresholds=alarm_at(vermillion=1),
                desc="Blackbox probes whose last check failed: an endpoint unreachable end to end, through the "
                     "gateway and TLS. This is the one tile that means a person using the service sees it broken.")


def storage_health():
    degraded = 'count(longhorn_volume_robustness{state="degraded"} == 1) or on() vector(0)'
    faulted = 'count(longhorn_volume_robustness{state="faulted"} == 1) or on() vector(0)'
    panel = stat("Longhorn volumes", None, decimals=0, text_mode="value_and_name", fixed_color=NEUTRAL,
                 targets=[target(faulted, "A", "faulted", instant=True),
                          target(degraded, "B", "degraded", instant=True)],
                 desc="Longhorn volumes by robustness. Faulted is a volume with no healthy replica, data at risk "
                      "now, vermillion from one. Degraded is running on fewer replicas than asked for and "
                      "rebuilding, amber from one: normal for minutes after a node restart, a problem for hours.")
    panel["fieldConfig"]["overrides"] = [col("faulted", thresholds=alarm_at(vermillion=1)),
                                         col("degraded", thresholds=alarm_at(amber=1))]
    return panel


def backups_late():
    cnpg = (f"count(max by (namespace) (time() - barman_cloud_cloudnative_pg_io_last_available_backup_timestamp) "
            f"> {BACKUP_LATE})")
    cron = (f"count(time() - max by (exported_namespace, cronjob) (kube_cronjob_status_last_successful_time{{{KSM}, "
            f"{BACKUP_CRONJOBS}}}) > {BACKUP_LATE})")
    return stat("Backups late", f"(({cnpg}) or on() vector(0)) + (({cron}) or on() vector(0))", decimals=0,
                thresholds=alarm_at(amber=1, vermillion=3),
                desc="CloudNativePG clusters whose newest base backup, and backup or snapshot CronJobs whose last "
                     "success, is older than 26 hours. Everything here runs daily, so late means a night was "
                     "missed. The Data wall names which.")


def slo_worst():
    return stat("Worst SLO error budget", "min(100 * slo:period_error_budget_remaining:ratio)", unit="percent",
                decimals=0, thresholds=low_is_bad(10, 50),
                desc="The smallest remaining error budget across every Sloth SLO, this period. Amber under half, "
                     "vermillion under a tenth; below zero the SLO is broken for the period.")


def cert_soonest():
    return stat("Certificate expires in", "min(certmanager_certificate_expiration_timestamp_seconds - time())",
                unit="s", decimals=0, thresholds=low_is_bad(DAY, 20 * DAY),
                desc="Time until the first cert-manager certificate expires. Let's Encrypt renews at 30 days left, "
                     "so under 20 means renewal is stuck (amber); under a day, vermillion.")


def firing_now_compact(group):
    panel = alerts.firing(group)
    panel["title"] = "Firing now, not silenced"
    return panel


def slo_budgets():
    return bars("SLO error budget left", [target(
        "100 * max by (sloth_service, sloth_slo) (slo:period_error_budget_remaining:ratio)", "A",
        "{{sloth_service}} · {{sloth_slo}}", instant=True)],
        unit="percent", decimals=0, thresholds=low_is_bad(10, 50), maximum=100,
        desc="Remaining error budget per SLO this period, lowest first to read. Amber under half, vermillion under "
             "a tenth.")


def now_wall():
    everything = alerts.GROUPS[0]
    return wall("wall-now", "Wall · Homelab now", [
        (alerts.critical(everything), 0, 0, 4, 5), (alerts.warning(everything), 4, 0, 4, 5),
        (flux_not_ready(), 8, 0, 4, 5), (nodes_not_ready(), 12, 0, 4, 5), (probes_failing(), 16, 0, 4, 5),
        (alerts.heartbeat(), 20, 0, 4, 5),
        (storage_health(), 0, 5, 6, 5), (backups_late(), 6, 5, 6, 5), (slo_worst(), 12, 5, 6, 5),
        (cert_soonest(), 18, 5, 6, 5),
        (firing_now_compact(everything), 0, 10, 15, 14), (slo_budgets(), 15, 10, 9, 14),
    ], refresh="30s", description="The homelab in one screen: what is firing, whether git is what runs, whether "
                                  "nodes, endpoints, storage and backups are whole, and the error budgets.",
        links=[link("Alerts · Everything", "/d/alerts-all")])


def gitops_wall():
    behind = ('count(flux_resource_info{kind="Kustomization", suspended="False"} unless on (revision) '
              'flux_resource_info{kind="GitRepository", name="flux-system"}) or on() vector(0)')
    since_run = ("time() - max by (renovate_job) (max_over_time((timestamp(increase("
                 'renovate_operator_project_executions_total{status="completed"}[5m]) > 0))[2d:5m]))')
    not_ready = ('max by (kind, exported_namespace, name, reason) (flux_resource_info{ready="False"})')
    issues = "sum by (project) (renovate_operator_dependency_issues) > 0"
    renovate_last = stat(
        "Renovate, since its last completed project", None, unit="s", decimals=0, text_mode="value_and_name",
        targets=[target(since_run, "A", "{{renovate_job}}", instant=True)], thresholds=alarm_at(amber=7 * HOUR,
                                                                                                 vermillion=13 * HOUR),
        desc="Time since each RenovateJob last completed a project run. The forgejo job runs hourly and gitops "
             "every six hours, so amber from seven hours and vermillion from thirteen: a whole cycle missed.")
    return wall("wall-gitops", "Wall · GitOps and Renovate", [
        (flux_not_ready(), 0, 0, 4, 5),
        (stat("Flux suspended", 'count(flux_resource_info{suspended="True"}) or on() vector(0)', decimals=0,
              thresholds=alarm_at(amber=1),
              desc="Flux objects someone suspended. A suspension is a deliberate hold that is easy to forget: "
                   "amber from one until it is resumed."), 4, 0, 4, 5),
        (stat("Kustomizations behind git", behind, decimals=0, thresholds=alarm_at(amber=1, vermillion=5),
              desc="Kustomizations whose applied revision is not the revision flux-system last fetched. A few for "
                   "a minute after a push is Flux working; the same ones for an hour are stuck behind a "
                   "dependsOn."), 8, 0, 4, 5),
        (stat("Flux reconcile errors · 15 min",
              'sum(increase(controller_runtime_reconcile_errors_total{namespace="flux-system"}[15m])) or on() vector(0)',
              decimals=0, thresholds=alarm_at(amber=1, vermillion=10),
              desc="Reconcile errors across the Flux controllers in the last 15 minutes."), 12, 0, 4, 5),
        (stat("Renovate projects failed", "sum(renovate_operator_run_failed) or on() vector(0)", decimals=0,
              thresholds=alarm_at(vermillion=1),
              desc="Projects whose last Renovate run failed. Dependency pull requests stop for them; the "
                   "renovate-debug skill maps the failure signatures."), 16, 0, 4, 5),
        (stat("Renovate ticks awaiting approval", "sum(renovate_operator_approvals_needed)", decimals=0,
              fixed_color=NEUTRAL,
              desc="Dependency dashboard items waiting for someone to tick them. Grey: it is a backlog to work "
                   "down, not an outage."), 20, 0, 4, 5),
        (table("Flux objects not ready", [target(not_ready, "A", instant=True, fmt="table")],
               rename={"kind": "Kind", "exported_namespace": "Namespace", "name": "Name", "reason": "Reason"},
               order=["Kind", "Namespace", "Name", "Reason"], hide=["Value"], no_value="Everything Flux manages is ready.",
               cell_height="md", desc="Every Flux object reporting Ready=False and the reason it gives."), 0, 5, 12, 10),
        (renovate_last, 12, 5, 12, 5),
        (bars("Renovate dependency issues per project", [target(issues, "A", "{{project}}", instant=True)],
              decimals=0, fixed_color=AMBER, no_value="No project has dependency issues.",
              desc="Dependencies Renovate could not look up or update, per project. Each is a package that will "
                   "silently stop getting updates."), 12, 10, 12, 14),
        (timeseries("Flux objects by readiness", [target('count by (ready) (flux_resource_info)', "A", "ready {{ready}}")],
                    unit="short", decimals=0,
                    overrides=color_overrides([("ready True", NEUTRAL), ("ready False", VERMILLION),
                                               ("ready Unknown", AMBER)]),
                    desc="Flux objects by readiness over the day. Unknown spikes are reconciles in progress."),
         0, 15, 12, 9),
    ], description="Is git what runs, and is Renovate still moving dependencies.",
        links=[link("Flux", "/d/flux-gitops-health"), link("Renovate", "/d/platform-renovate-operator")])


def nodes_wall():
    def requests(resource):
        return (f'sum by (node) (kube_pod_container_resource_requests{{{KSM}, resource="{resource}"}} * on (uid) '
                f'group_left() (max by (uid) (kube_pod_status_phase{{{KSM}, phase=~"Running|Pending"}}) == 1)) '
                f'/ on (node) sum by (node) (kube_node_status_allocatable{{{KSM}, resource="{resource}"}})')

    outside = 'max by (instance) (container_memory_rss{id="/"} - on (instance) container_memory_rss{id="/kubepods"})'
    pending = (f'count((min_over_time(kube_pod_status_phase{{{KSM}, phase="Pending"}}[15m]) == 1) and on (uid) '
               f'(kube_pod_created{{{KSM}}} < time() - 900)) or on() vector(0)')
    cpu_used = ('1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) '
                '* on (instance) group_left(nodename) node_uname_info')
    return wall("wall-nodes", "Wall · Nodes", [
        (nodes_not_ready(), 0, 0, 4, 5),
        (stat("Node pressure conditions",
              f'sum(kube_node_status_condition{{{KSM}, condition=~"MemoryPressure|DiskPressure|PIDPressure", '
              f'status="true"}}) or on() vector(0)', decimals=0, thresholds=alarm_at(vermillion=1),
              desc="Memory, disk or PID pressure conditions set by a kubelet. The kubelet evicts pods while one "
                   "is set."), 4, 0, 4, 5),
        (stat("Pods pending over 15 min", pending, decimals=0, thresholds=alarm_at(amber=1, vermillion=3),
              desc="Pods created more than 15 minutes ago that have been Pending the whole time. CI runner pods "
                   "flicker through Pending for seconds, which is why the window is 15 minutes. Usually a node "
                   "out of requestable memory: see the bars below."), 8, 0, 4, 5),
        (stat("Container restarts · 1 h", f"sum(increase(kube_pod_container_status_restarts_total{{{KSM}}}[1h]))",
              decimals=0, thresholds=alarm_at(amber=5, vermillion=25),
              desc="Container restarts across the cluster in the last hour. A healthy hour is zero."), 12, 0, 4, 5),
        (stat("Scrape targets down", "count(up == 0) or on() vector(0)", decimals=0, thresholds=alarm_at(amber=1),
              desc="Metric targets vmagent cannot scrape. Whatever they measure is blind on every board."),
         16, 0, 4, 5),
        (stat("Memory outside kubepods, worst node", f"max({outside})", unit="bytes", decimals=1,
              thresholds=alarm_at(amber=3.5 * 2**30, vermillion=5 * 2**30),
              desc="Resident memory on a node that no pod accounts for. Above 5 GiB for an hour is the dind "
                   "cgroup escape NodeMemoryOutsideKubepods fires on: pod restarts do not free it, a node reboot "
                   "does."), 20, 0, 4, 5),
        (bars("Memory requested, per node", [target(requests("memory"), "A", "{{node}}", instant=True)],
              unit="percentunit", decimals=0, maximum=1, thresholds=alarm_at(amber=0.9, vermillion=0.98),
              desc="Memory requests of running and pending pods as a share of each node's allocatable memory. The "
                   "scheduler places by requests, not usage: at 98 % a node takes no new pod that asks for real "
                   "memory, which is what leaves CI runners and Glide workers Pending."), 0, 5, 8, 10),
        (bars("CPU requested, per node", [target(requests("cpu"), "A", "{{node}}", instant=True)],
              unit="percentunit", decimals=0, maximum=1, thresholds=alarm_at(amber=0.9, vermillion=0.98),
              desc="CPU requests as a share of each node's allocatable CPU."), 8, 5, 8, 10),
        (bars("Memory outside kubepods, per node", [target(outside, "A", "{{instance}}", instant=True)],
              unit="bytes", decimals=1, thresholds=alarm_at(amber=3.5 * 2**30, vermillion=5 * 2**30),
              desc="The same measure per node."), 16, 5, 8, 10),
        (timeseries("CPU used per node", [target(cpu_used, "A", "{{nodename}}")], unit="percentunit",
                    desc="Share of each node's CPU in use, five-minute rate."), 0, 15, 12, 9),
        (timeseries("I/O pressure per node", [target(
            "max by (nodename) (rate(node_pressure_io_waiting_seconds_total[5m]) * on (instance) group_left(nodename) "
            "node_uname_info)", "A", "{{nodename}}")], unit="percentunit", thresholds=alarm_at(amber=0.2, vermillion=0.5),
            desc="Share of time tasks waited on I/O (PSI). CI and Longhorn rebuilds are what drive it here."),
         12, 15, 12, 9),
    ], description="Are the Talos nodes whole and do they have room.")


def data_wall():
    cnpg_age = "max by (namespace) (time() - barman_cloud_cloudnative_pg_io_last_available_backup_timestamp)"
    cron_age = (f"max by (exported_namespace, cronjob) (time() - kube_cronjob_status_last_successful_time{{{KSM}, "
                f"{BACKUP_CRONJOBS}}})")
    failing = ("count(barman_cloud_cloudnative_pg_io_last_failed_backup_timestamp > 0 and "
               "barman_cloud_cloudnative_pg_io_last_failed_backup_timestamp >= "
               "barman_cloud_cloudnative_pg_io_last_available_backup_timestamp) or on() vector(0)")
    return wall("wall-data", "Wall · Data and backups", [
        (storage_health(), 0, 0, 6, 5),
        (stat("Longhorn free, worst node",
              "min(1 - longhorn_node_storage_usage_bytes / longhorn_node_storage_capacity_bytes)", unit="percentunit",
              decimals=0, thresholds=low_is_bad(0.15, 0.25),
              desc="Free share of the fullest Longhorn node's disks. Amber under a quarter, vermillion under 15 %, "
                   "where Longhorn stops scheduling replicas there."), 6, 0, 4, 5),
        (stat("CNPG backups failing", failing, decimals=0, thresholds=alarm_at(vermillion=1),
              desc="Postgres clusters whose newest backup attempt failed after their last good one."), 10, 0, 4, 5),
        (stat("CNPG replica lag, worst",
              'max(cnpg_pg_replication_lag{pod!~"cnpg-disaster-recovery.*"}) or on() vector(0)', unit="s",
              decimals=0, thresholds=alarm_at(amber=60, vermillion=300),
              desc="The largest streaming replica lag. The disaster-recovery check pods are left out: they replay "
                   "an old backup and report hours of lag by design."), 14, 0, 4, 5),
        (stat("Garage healthy", 'min(cluster_healthy{job="garage-s3"})', decimals=0,
              thresholds=kiosk_steps((VERMILLION, 0), (NEUTRAL, 1)),
              mappings=[{"type": "value", "options": {"0": {"text": "no"}, "1": {"text": "yes"}}}],
              desc="Garage's own cluster health. Every backup in this cluster lands in Garage S3."), 18, 0, 3, 5),
        (stat("Garage free", "min(garage_local_disk_avail / garage_local_disk_total)", unit="percentunit", decimals=0,
              thresholds=low_is_bad(0.1, 0.25), desc="Free share of Garage's fullest disk."), 21, 0, 3, 5),
        (bars("Postgres base backup age", [target(cnpg_age, "A", "{{namespace}}", instant=True)], unit="s",
              decimals=0, thresholds=alarm_at(amber=BACKUP_LATE, vermillion=50 * HOUR),
              desc="Age of each CloudNativePG cluster's newest available base backup. Daily schedule: amber past "
                   "26 hours, vermillion past 50."), 0, 5, 12, 12),
        (bars("Backup and snapshot CronJobs, since last success", [target(
            cron_age, "A", "{{exported_namespace}}/{{cronjob}}", instant=True)], unit="s", decimals=0,
            thresholds=alarm_at(amber=BACKUP_LATE, vermillion=48 * HOUR),
            desc="Time since each backup or snapshot CronJob last succeeded, OpenBao's included."), 12, 5, 12, 12),
        (timeseries("Longhorn volumes not healthy", [target(
            'count by (state) (longhorn_volume_robustness{state=~"degraded|faulted"} == 1)', "A", "{{state}}")],
            unit="short", decimals=0, overrides=color_overrides([("degraded", AMBER), ("faulted", VERMILLION)]),
            desc="Degraded and faulted volumes over the range. A wave of degraded volumes after a node restart "
                 "that drains within the hour is a rebuild; one that plateaus is the rebuild wedge the longhorn "
                 "skill describes."), 0, 17, 12, 7),
        (timeseries("Garage S3 error ratio", [target(
            "sum(rate(api_s3_error_counter[15m])) / sum(rate(api_s3_request_counter[15m]))", "A", "errors")],
            unit="percentunit", thresholds=alarm_at(amber=0.1, vermillion=0.25),
            overrides=color_overrides([("errors", CAT[1])]),
            desc="Share of S3 requests Garage answered with an error. About 5 % is the baseline of 404 probes "
                 "from backup tools; above 10 % something is failing writes."), 12, 17, 12, 7),
    ], description="Are volumes whole, did last night's backups land, and does Garage have room.",
        links=[link("Longhorn", "/d/longhorn-storage-health"), link("CNPG backups", "/d/cnpg-backups-dr")])


def edge_security_wall():
    ratio = ('sum(rate(envoy_http_downstream_rq_xx{namespace="network", envoy_response_code_class="5", '
             'envoy_http_conn_manager_prefix="https-10443"}[5m])) / sum(rate(envoy_http_downstream_rq_total'
             '{namespace="network", envoy_http_conn_manager_prefix="https-10443"}[5m]))')
    down = ('label_replace(probe_success == 0, "probe", "$1", "job", "probe/[^/]+/blackbox-(.+)")')
    eso = ('max by (exported_namespace, name) (externalsecret_status_condition{condition="Ready", status="False"}) '
           "== 1")
    push = ('max by (exported_namespace, name) (pushsecret_status_condition{condition="Ready", status="False"}) '
            "== 1")
    return wall("wall-edge", "Wall · Edge and security", [
        (probes_failing(), 0, 0, 4, 5),
        (stat("Gateway 5xx share", ratio, unit="percentunit", decimals=2, spark=True,
              thresholds=alarm_at(amber=0.02, vermillion=0.05),
              desc="Share of HTTPS requests through Envoy Gateway answered 5xx, five-minute rate. The 7-day p99 "
                   "was 2.5 % when this board was written, so amber from 2 %, vermillion from 5 %."), 4, 0, 5, 5),
        (cert_soonest(), 9, 0, 5, 5),
        (stat("Secrets not syncing",
              f"(count({eso}) or on() vector(0)) + (count({push}) or on() vector(0))", decimals=0,
              thresholds=alarm_at(vermillion=1),
              desc="ExternalSecrets and PushSecrets whose Ready condition is False: an app is running on a stale "
                   "secret or the vault copy is missing. The table below names them."), 14, 0, 5, 5),
        (stat("Kyverno enforce blocks · 1 h",
              'sum(increase(kyverno_policy_results_total{rule_result="fail", policy_validation_mode="enforce"}[1h])) '
              "or on() vector(0)", decimals=0, thresholds=alarm_at(amber=1, vermillion=10),
              desc="Admission requests an Enforce policy rejected in the last hour. A burst after a push is a "
                   "manifest Flux cannot apply."), 19, 0, 5, 5),
        (table("Endpoints down", [target(down, "A", instant=True, fmt="table")],
               rename={"probe": "Probe", "instance": "Target"}, order=["Probe", "Target"],
               hide=["Value", "job", "__name__", "cluster", "prometheus", "namespace", "endpoint", "container",
                     "pod", "service"],
               no_value="Every probed endpoint answers.", cell_height="md",
               desc="Each blackbox probe that failed its last check and the URL it probes."), 0, 5, 12, 9),
        (table("Secrets not syncing", [target(
            f'label_replace({eso}, "kind", "ExternalSecret", "", "") or label_replace({push}, "kind", "PushSecret", "", "")',
            "A", instant=True, fmt="table")],
               rename={"kind": "Kind", "exported_namespace": "Namespace", "name": "Name"},
               order=["Kind", "Namespace", "Name"], hide=["Value"],
               no_value="Every ExternalSecret and PushSecret is ready.", cell_height="md",
               desc="ExternalSecrets and PushSecrets that are not Ready. The fix is almost always the OpenBao path "
                    "or the store: `kubectl describe` the object for the message."), 12, 5, 12, 9),
        (stat("Trivy exposed secrets", "sum(trivy_image_exposedsecrets) or on() vector(0)", decimals=0,
              thresholds=alarm_at(vermillion=1),
              desc="Secrets Trivy found baked into running images. Rotate the secret, then rebuild the image."),
         0, 14, 6, 5),
        (stat("Trivy critical CVEs", 'sum(trivy_image_vulnerabilities{severity="Critical"})', decimals=0,
              spark=True, fixed_color=NEUTRAL,
              desc="Critical vulnerabilities across running images. Grey with a trend line: the number matters "
                   "less than whether it is going down."), 0, 19, 6, 5),
        (timeseries("Gateway requests by response class", [target(
            'sum by (envoy_response_code_class) (rate(envoy_http_downstream_rq_xx{namespace="network", '
            'envoy_http_conn_manager_prefix="https-10443"}[5m]))', "A", "{{envoy_response_code_class}}xx")],
            unit="reqps", overrides=color_overrides([("2xx", NEUTRAL), ("3xx", SKY), ("4xx", AMBER),
                                                     ("5xx", VERMILLION)]),
            desc="HTTPS requests per second through Envoy Gateway by response class."), 6, 14, 18, 10),
    ], description="Can people reach the services, is TLS current, are secrets syncing, is anything leaking.",
        links=[link("Envoy Gateway", "/d/envoy-gateway-traffic"), link("Security", "/d/security-overview")])


def roadmap_sql(where):
    return f"""
        SELECT count(DISTINCT t.id) AS n
        FROM tasks t
        JOIN label_tasks lt ON lt.task_id = t.id
        JOIN labels l ON l.id = lt.label_id
        WHERE NOT t.done AND t.project_id IN ({", ".join(str(p) for p in BOARD_PROJECTS)}) AND {where}
    """


def roadmap_wall():
    names = " ".join(f"WHEN {pid} THEN '{name}'" for pid, name in BOARD_PROJECTS.items())
    ids = ", ".join(str(p) for p in BOARD_PROJECTS)
    per_project = f"""
        SELECT CASE t.project_id {names} END AS project,
          count(DISTINCT t.id) FILTER (WHERE l.title = 'do-next') AS do_next,
          count(DISTINCT t.id) FILTER (WHERE l.title = 'ready') AS ready,
          count(DISTINCT t.id) FILTER (WHERE l.title LIKE 'agent/%') AS doing,
          count(DISTINCT t.id) FILTER (WHERE l.title = 'review') AS reviewing,
          count(DISTINCT t.id) FILTER (WHERE l.title = 'needs-refinement') AS refine
        FROM tasks t
        LEFT JOIN label_tasks lt ON lt.task_id = t.id
        LEFT JOIN labels l ON l.id = lt.label_id
        WHERE NOT t.done AND t.project_id IN ({ids})
        GROUP BY t.project_id ORDER BY t.project_id
    """
    in_review = f"""
        SELECT t.id AS ticket, t.title, CASE t.project_id {names} END AS project, t.updated AS since
        FROM tasks t
        JOIN label_tasks lt ON lt.task_id = t.id
        JOIN labels l ON l.id = lt.label_id
        WHERE NOT t.done AND l.title = 'review' AND t.project_id IN ({ids})
        ORDER BY t.updated ASC LIMIT 12
    """
    done_week = f"""
        SELECT count(*) AS n FROM tasks t
        WHERE t.done AND t.done_at > now() - interval '7 days' AND t.project_id IN ({ids})
    """
    done_per_day = f"""
        SELECT date_trunc('day', t.done_at) AS time, count(*) AS done
        FROM tasks t
        WHERE t.done AND $__timeFilter(t.done_at) AND t.project_id IN ({ids})
        GROUP BY 1 ORDER BY 1
    """

    def sql_stat(title, raw, thresholds, desc):
        return stat(title, None, decimals=0, targets=[sql(VIKUNJA, raw)], thresholds=thresholds, desc=desc,
                    value_size=56, no_value="0")

    reviewing = table("Waiting for review, oldest first", [sql(VIKUNJA, in_review)],
                      rename={"ticket": "VIK", "title": "Ticket", "project": "Board", "since": "Since"},
                      order=["VIK", "Ticket", "Board", "Since"], no_value="Nothing is waiting for review.",
                      cell_height="md", overrides=[col("VIK", width=70), col("Board", width=150),
                                                   col("Since", unit="dateTimeFromNow", width=130)],
                      desc="Tickets with the review label: an agent or a person finished and the owner accepts. "
                           "Oldest first, because a review that waits is work already paid for and not yet "
                           "shipped.")
    projects = table("Stages per board", [sql(VIKUNJA, per_project)],
                     rename={"project": "Board", "do_next": "do-next", "ready": "To do", "doing": "Doing",
                             "reviewing": "Reviewing", "refine": "Needs refinement"},
                     order=["Board", "do-next", "To do", "Doing", "Reviewing", "Needs refinement"], cell_height="md",
                     overrides=[col("do-next", thresholds=alarm_at(amber=11), colour_text=True),
                                col("Reviewing", thresholds=alarm_at(amber=5), colour_text=True)],
                     desc="Open tickets per board by derived stage (ADR-0043): do-next is the top of the stack and "
                          "is capped at ten, so amber from eleven; Doing is an agent/* claim; Reviewing is the "
                          "review label, amber from five, the review-capacity limit.")
    trend = timeseries("Tickets closed per day", [sql(VIKUNJA, done_per_day, fmt="time_series")], unit="short",
                       draw="bars", decimals=0, overrides=color_overrides([("done", NEUTRAL)]),
                       desc="Tickets closed per day across the listed boards.")
    return wall("wall-roadmap", "Wall · Roadmap", [
        (sql_stat("do-next", roadmap_sql("l.title = 'do-next'"), alarm_at(amber=11),
                  "Open do-next tickets across the boards. The contract caps it at ten per board."), 0, 0, 5, 5),
        (sql_stat("Doing", roadmap_sql("l.title LIKE 'agent/%'"), kiosk_steps((SKY, 1)),
                  "Open tickets an agent has claimed (an agent/* label)."), 5, 0, 5, 5),
        (sql_stat("Reviewing", roadmap_sql("l.title = 'review'"), alarm_at(amber=5),
                  "Open tickets with the review label, waiting for the owner. Amber from five."), 10, 0, 5, 5),
        (sql_stat("Closed · 7 days", done_week, kiosk_steps(),
                  "Tickets closed across the boards in the last seven days."), 15, 0, 4, 5),
        (sql_stat("Needs refinement", roadmap_sql("l.title = 'needs-refinement'"), kiosk_steps(),
                  "Open tickets not yet refined to the Definition of Ready."), 19, 0, 5, 5),
        (projects, 0, 5, 12, 8), (reviewing, 12, 5, 12, 19), (trend, 0, 13, 12, 11),
    ], time_from="now-30d",
        description="What the boards on Vikunja say: the top of the stack, what agents hold, what waits for review.",
        links=[link("Vikunja", "https://vikunja.${SECRET_DOMAIN}", icon="external link", blank=True)])


def boards():
    return [(b, FOLDER) for b in (now_wall(), gitops_wall(), nodes_wall(), data_wall(), edge_security_wall(),
                                  roadmap_wall())]
