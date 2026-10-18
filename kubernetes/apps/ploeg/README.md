# ploeg — dispatch plane

[webgrip/ploeg](https://forgejo.webgrip.dev/webgrip/ploeg) turns Vikunja assignment webhooks
into leased, audited agent runs — the event-driven replacement for ADR-0048's poll dispatcher.
Chart: `oci://harbor.webgrip.dev/webgrip/charts/ploeg`; image `webgrip/ploegd` (same version,
kept in lockstep by the release train).

## Releases

Renovate moves Ploeg and Unfold together, in one `renovate/ploeg-unfold-release` PR that merges
itself: the Ploeg chart, the ploegd image (daemon and ploeg-mcp) and the claude-runner image, and
the Unfold chart, image and workspace image. `scripts/check_release_lockstep.py` keeps that PR red
while a release's own pins disagree, and, with `--certified-pair` on pull requests, while the Ploeg
pin is not the release the pinned Unfold names in its `.gitmodules` at tag `unfold-v<version>`
(the pair Unfold tested). The PR is exempt from the repository's branch and PR concurrency limits.
The [Unfold release train RFC](../../../docs/techdocs/docs/rfc/rfc-unfold-release-train.md)
proposes replacing this with a manifest-driven bump.

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

A worker pod (`app.kubernetes.io/name: ploeg-worker`) reaches DNS, ploegd on 8080, the LiteLLM pods
on 4000, the Forgejo pods on 3000 and Alloy on 4318, through `ploeg-worker-egress`
([ADR-0071](../../../docs/techdocs/docs/adr/adr-0071-agent-egress-reaches-only-what-it-needs.md)).
It has no route to the database, Unfold, ploeg-mcp or any other pod in `ploeg`, to Vikunja or
Omnigraph, to the public gateway, the LAN or the internet: `ploeg-allow-egress` leaves out
`ploeg-worker`, `ploeg-sandbox-launcher` and `claude-runner`, and `allow-gateway-egress` (from
`components/gateway-egress`, patched in `unfold/app/kustomization.yaml`) selects only `unfold`
and `ploeg` (ploegd). A sandbox launcher reaches only ploegd and the API server.
`worker-egress-probe` checks both halves as a worker-labelled Job; rerun it by changing its
`PROBED_POLICY` value.

The Claude runner (`app.kubernetes.io/name: claude-runner`, Kata) is left out of `ploeg-allow-egress`. It reaches only DNS, `api.anthropic.com:443`, ploegd on 8080 (the checkout and post-session hooks), the public gateway on 10443 (it clones `https://forgejo.<domain>`), and Alloy on 4318: no LiteLLM, no database, no other pod in `ploeg`.

- Workers clone, push and call the PR API through `executor.forgejo.url`, the in-cluster
  service. ploegd keeps the public `https://forgejo.<domain>` through a post-render env patch,
  because it checks Unfold's https repository URL against its own forge URL. Glide VIK-1298
  asks the chart for a separate value so the patch can go.
- `forgeTokenIsolation: proxy` and `litellm.keyIsolation: proxy` (Glide ADR-0034) keep the forge
  token and the per-Run LiteLLM key in `ploeg-worker`; OpenHands gets placeholders and loopback
  URLs.

Failure-mode drills and the full e2e runbook live in the executor PR description.

## ploeg-mcp over HTTPS

`ploeg-mcp` (`app/mcp/`) serves Ploeg's read-only MCP tools at `https://mcp-ploeg.<domain>/mcp` on
envoy-internal, LAN and VPN only. Clients sign in through the Authentik application `ploeg-mcp`
(public client, PKCE, 10-minute access tokens, scope `ploeg:read`), and only members of
`ploeg-readers` (capability `ploeg-read`) get in. ploeg-mcp checks the token itself and calls ploegd
with the `mcp-reader` operator consumer's token from `ploeg/mcp-reader`, never the person's token.
Its image is the ploegd image and moves with the Ploeg release; `check_release_lockstep.py` fails
while they differ. Client setup:
[Serve Ploeg's MCP tools over HTTPS](https://github.com/ploeg-hq/ploeg/blob/development/docs/how-to/serve-ploeg-mcp-over-https.md).
