# ploeg — dispatch plane

[webgrip/ploeg](https://forgejo.webgrip.dev/webgrip/ploeg) turns Vikunja assignment webhooks
into leased, audited agent runs — the event-driven replacement for ADR-0048's poll dispatcher.
Chart: `oci://harbor.webgrip.dev/webgrip/charts/ploeg`; image `webgrip/ploegd` (same version,
kept in lockstep by the release train).

## One-time setup after first deploy (ingest)

1. Read the generated webhook secret:

   ```sh
   kubectl -n ploeg get secret ploeg-webhook-secret -o jsonpath='{.data.PLOEG_VIKUNJA_SECRET}' | base64 -d
   ```

2. In Vikunja, on the dedicated **Ploeg Test** project → Settings → Webhooks, add:
   - Target URL: `http://ploeg.ploeg.svc.cluster.local:8080/webhooks/tracker/vikunja`
   - Events: `task.assignee.created` (queues work), plus `task.assignee.deleted`, `task.updated`
   - Secret: the value from step 1 (raw-body HMAC-SHA256, `X-Vikunja-Signature`)

3. Verify ingest: assign a task to anyone, then

   ```sh
   kubectl -n ploeg logs deploy/ploeg | grep "work item queued"
   kubectl -n ploeg exec ploeg-db-1 -c postgres -- psql -U postgres app \
     -c "select id,team,state,title from work_items order by id desc limit 5;"
   ```

## Executor (phase 3, `executor.enabled: true`)

Per-team KEDA ScaledJobs run OpenHands (agent-runner image) against LiteLLM with a per-run
budgeted key; work lands as `agent/vik-<id>` branches + PRs by the `agent-builder` bot.
Requires in this namespace: `agent-litellm-master` + `agent-builder-token` ExternalSecrets,
the `exception-ploeg-worker-privileged` Kyverno exception (privileged DinD sidecar), and
egress to `ai:4000` + `forgejo:3000`.

Failure-mode drills and the full e2e runbook live in the executor PR description.
