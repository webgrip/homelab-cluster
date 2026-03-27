# Runbook: k6 canaries

Use this when k6 canary results look bad (errors/latency) in dashboards.

## Fast triage

1) Check whether the CronJob is running

- `kubectl -n observability get cronjob k6-ingress-canary -o wide`

2) Check recent Jobs

- `kubectl -n observability get jobs --sort-by=.metadata.creationTimestamp | tail`

3) Check recent TestRuns

- `kubectl -n observability get testruns.k6.io --sort-by=.metadata.creationTimestamp | tail`

## Where it’s configured

- [kubernetes/apps/observability/k6-canaries](../../../kubernetes/apps/observability/k6-canaries)
