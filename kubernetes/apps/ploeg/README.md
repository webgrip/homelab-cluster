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
Requires in this namespace: `agent-litellm-master` + `agent-builder-token` ExternalSecrets and
egress to `ai:4000` + `forgejo:3000`. The plane is daemonless (ADR-0053): every team runs
`dind: false` via the executor-level harness default, no pod is privileged, and the old
`exception-ploeg-worker-privileged` Kyverno waiver + PSA carve-out are gone — gates that need
containers run in CI, in CI's own images.

### What a Run can reach

A worker pod (`app.kubernetes.io/name: ploeg-worker`) reaches DNS, the pods in `ploeg`, LiteLLM
(`ai:4000`), in-cluster Forgejo (`forgejo:3000`) and the Vikunja API (`vikunja:3456`). It has no
route to the public gateway, the LAN or the internet: `allow-gateway-egress` (from
`components/gateway-egress`, patched in `de-vloer/app/kustomization.yaml`) selects only `de-vloer`
and `ploeg` (ploegd). `worker-egress-probe` checks both halves as a worker-labelled Job; rerun it
by changing its `PROBED_POLICY` value.

- Workers clone, push and call the PR API through `executor.forgejo.url`, the in-cluster
  service. ploegd keeps the public `https://forgejo.<domain>` through a post-render env patch,
  because it checks De Vloer's https repository URL against its own forge URL. Glide VIK-1298
  asks the chart for a separate value so the patch can go.
- `forgeTokenIsolation: proxy` and `litellm.keyIsolation: proxy` (Glide ADR-0034) keep the forge
  token and the per-Run LiteLLM key in `ploeg-worker`; OpenHands gets placeholders and loopback
  URLs.

Failure-mode drills and the full e2e runbook live in the executor PR description.
