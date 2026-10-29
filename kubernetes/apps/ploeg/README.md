# ploeg — dispatch plane

[Ploeg](https://github.com/ploeg-hq/ploeg) turns Vikunja assignment webhooks
into leased, audited agent runs — the event-driven replacement for ADR-0048's poll dispatcher.
It runs inside the Unfold Helm release: homelab pins only the Unfold chart, and that chart brings
the Ploeg chart and the ploegd image digest it was tested with.

## Releases

Ploeg runs inside the Unfold Helm release (Unfold ADR-0043): the Unfold chart
(`unfold/app/ocirepository.yaml`) carries the Ploeg chart it was tested with as its `ploeg`
subchart, and that chart defaults the ploegd image to its release digest.
`unfold/app/helmrelease.yaml` holds Ploeg's values under `ploeg:`, with `fullnameOverride` and
`instanceOverride` set to `ploeg` so every object keeps the name and selector labels it had under the
standalone release. ploeg-mcp is rendered by the chart; its route, network policies and Secrets stay
in `ploeg/app/`.

Renovate moves the Unfold chart, image and workspace image in one `renovate/ploeg-unfold-release`
PR that merges itself: Forgejo merges it once `main`'s required `e2e /` checks pass. Renovate finds a
new release on its hourly run. `scripts/check_release_lockstep.py` keeps that PR red while those pins
disagree, and fails if a standalone `ploeg/app/helmrelease.yaml` comes back, because two Helm releases
would then fight over Ploeg's objects. The standalone release was retired on 2026-10-20: its Flux
finalizer was removed before the HelmRelease and its Helm storage Secrets were deleted, so nothing was
uninstalled.

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

## Executor (phase 3, `ploeg.executor.enabled: true`)

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
`ploeg-worker` and `ploeg-sandbox-launcher`, and `allow-gateway-egress` (from
`components/gateway-egress`, patched in `unfold/app/kustomization.yaml`) selects only `unfold`
and `ploeg` (ploegd). A sandbox launcher reaches only ploegd and the API server.
`worker-egress-probe` checks both halves as a worker-labelled Job; rerun it by changing its
`PROBED_POLICY` value.

Two more worker-labelled Jobs qualify Ploeg's profile P1 (ploeg-hq/ploeg #16 and #17). Each is deleted
seven days after it finishes and Flux recreates it, so both rerun about weekly; a failure fires
`KubeJobFailed`:

- `worker-boundary-probe` runs Ploeg's `scripts/worker-boundary-probe.sh` (copied from ploeg-hq/ploeg
  PR #291 into [`worker-boundary-probe/`](ploeg/app/worker-boundary-probe/)) in a Kata pod with the
  `ploeg-worker` service account: no root, no capabilities, seccomp on, no service-account token, no host
  paths or runtime sockets, no metadata endpoint, no Kubernetes API, no egress beyond ploegd, LiteLLM and
  Forgejo.
- `forge-revocation-probe` mints a Forgejo token for `agent-builder` with the bot password ploegd's
  forge broker uses, proves it works, revokes it, and replays it five times against the API and git
  discovery; every replay must answer 401. The password stays in the pod's environment and the token is
  never printed; an exit trap revokes the token if the probe stops early.

- Workers clone, push and call the PR API through `ploeg.executor.forgejo.url`, the in-cluster
  service. ploegd keeps the public `https://forgejo.<domain>` through a post-render env patch in
  [`unfold/app/kustomization.yaml`](unfold/app/kustomization.yaml),
  because it checks Unfold's https repository URL against its own forge URL. Glide VIK-1298
  asks the chart for a separate value so the patch can go.
- `ploeg.executor.forgeTokenIsolation: proxy` and `ploeg.executor.litellm.keyIsolation: proxy`
  ([Ploeg ADR-0034](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0034-the-harness-gets-placeholders-the-worker-keeps-credentials.md))
  keep the forge token and the per-Run LiteLLM key in `ploeg-worker`; OpenHands gets placeholders
  and loopback URLs.

Failure-mode drills and the full e2e runbook live in the executor PR description.

## ploeg-mcp over HTTPS

`ploeg-mcp` (the chart's `mcp` values, with its route and policies in `app/mcp/`) serves Ploeg's read-only MCP tools at `https://mcp-ploeg.<domain>/mcp` on
envoy-internal, LAN and VPN only. Clients sign in through the Authentik application `ploeg-mcp`
(public client, PKCE, 10-minute access tokens, scope `ploeg:read`), and only members of
`ploeg-readers` (capability `ploeg-read`) get in. ploeg-mcp checks the token itself and calls ploegd
with the `mcp-reader` operator consumer's token from `ploeg/mcp-reader`, never the person's token.
Its image is the ploegd image of the Ploeg release the Unfold chart carries. Client setup:
[Serve Ploeg's MCP tools over HTTPS](https://github.com/ploeg-hq/ploeg/blob/development/docs/how-to/serve-ploeg-mcp-over-https.md).

### Confirming an action (login mode, 2026-10-25)

Members of `ploeg-operators` (capability `ploeg-operate`) may also act: add a note, approve, retry,
stop. ploeg-mcp runs with `PLOEG_MCP_CONFIRMATION_MODE=login` (Ploeg ADR-0153). An action answers
the client with a link to `https://mcp-ploeg.<domain>/confirmations/<token>`; the page shows the
action, its arguments and the person, and the action runs only after **Sign in to confirm** completes
in the same browser, through the confidential Authentik client `ploeg-mcp-confirm` (secret generated
in `authentik/app/ploeg-mcp-confirm-oidc-client.*`, read from `authentik/ploeg-mcp-confirm-oidc` by
`unfold/app/ploeg-mcp-confirmation-client.externalsecret.yaml`).

What it proves: the person approved in their own browser and Authentik session, so an MCP client
can no longer approve its own action. What it does not prove: a fresh security-key touch. Login is
Google-only (ADR-0057); Authentik's Google source forwards neither `prompt` nor `max_age`, and Google
reports neither `auth_time` nor `amr`, so `PLOEG_MCP_CONFIRMATION_AMR` stays unset. A real
presence check needs an Authentik WebAuthn stage for this one client and an ADR amending ADR-0057.

Client support: on 2026-10-25 Claude Code declined the link (MCP URL elicitation) without showing
it, so every action returned "Not done: you did not confirm" and nothing changed. Reading works.
The owner chose to keep login mode on until clients show the link rather than fall back to the
in-client yes/no form, which a client can answer by itself (F-08). To fall back anyway, set
`PLOEG_MCP_CONFIRMATION_MODE: elicitation` in `unfold/app/helmrelease.yaml`.

## Why the Ploeg values are set this way

Ploeg's values sit under `ploeg:` in [`unfold/app/helmrelease.yaml`](unfold/app/helmrelease.yaml),
without comments. This section keeps the reasons, by key path. Ploeg ADRs are in
[ploeg-hq/ploeg](https://github.com/ploeg-hq/ploeg/tree/development/docs/adrs), Unfold ADRs in
[webgrip/unfold](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/docs/adr/).

### ploegd's environment

- `ploeg.env.PLOEG_DEFAULT_TEAM: copper`: an assignee no team lists falls through to the default
  team. copper's exec harness makes no model call, opens no pull request, prints nothing and ends
  `stuck` with "copper only runs canary items", so a person assigned by mistake on a board with the
  ploegd webhook costs $0 instead of a live Run against a real repository, and the item waits for
  a person instead of closing. Refusing to route (`PLOEG_TARGET_STRICT`,
  old Ploeg backlog #108) would be better and replaces this when it ships. Until then, do not
  assign an unmapped person on a webhook board unless a copper no-op is what you want.
- There is no `PLOEG_TEAM_MAP`, `PLOEG_TARGET_MAP` or `PLOEG_TEAM_PLANS`. The roster and routing
  are `ploeg.config` (mounted as `/etc/ploeg/ploeg.yaml`); an env copy of the roster drifted from
  the file before it was removed.

### `ploeg.knowledgeGraph`

ploegd writes the learnings a Run keeps to the `webgrip-notes` graph and briefs later Runs of
the same work from it
([Ploeg ADR-0088](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0088-a-run-writes-work-item-notes-without-review-and-a-wider-scope-is-a-promotion-a-person-accepts.md)),
and briefs each Run from the reviewed `webgrip-knowledge` concepts of its Tenant, Client and
repository
([Ploeg ADR-0087](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0087-ploegd-holds-a-tenants-knowledge-graphs-and-serves-a-run-only-its-work-items-scopes.md)).
Both ADRs were proposed when this was set. The network path is `ploegd-allow-omnigraph-egress`
in [`ploeg/app/networkpolicy.yaml`](ploeg/app/networkpolicy.yaml), which selects the daemon label
the chart puts on ploegd alone.

### Who reaches ploeg-db

[`ploeg/app/networkpolicy.yaml`](ploeg/app/networkpolicy.yaml) admits the `observability`
namespace only as vmagent, on the metrics ports 8080 and 9187, and `ploeg-db-allow-grafana` lets
the Grafana pod (`app: grafana`) reach ploeg-db on 5432 for the "Ploeg Dispatch DB" datasource.
Every other pod there, the cluster-reading MCP servers included, has no path to the database. The
KEDA operator keeps 5432 from the `keda` namespace, the CNPG operator 5432 and 8000 from
`cnpg-system`, and ploegd and the exporter reach it from inside `ploeg`.

### `ploeg.operator`

- `consumers[mcp-operator]` is ploeg-mcp acting for a person in Authentik's `ploeg-operators`
  group, after that person confirms each action
  ([Ploeg ADR-0108](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0108-every-operator-action-names-its-person-and-channel-and-an-mcp-action-needs-the-persons-confirmation.md)).
- `consumers[unfold-verifier]` is Unfold's trusted verifier: it records delivery candidates,
  receipts and publication status for the `unfold` team, and never executes or approves.
- `deliveryPolicies`: one policy per delivery repository. `policySha256` is Unfold's
  `policyDigest` of the matching `delivery.policies` entry as the Unfold chart renders it (Helm
  sorts object keys). Change both together.

### `ploeg.config.trackers.vikunja.projects`

- One entry per board, without a `team:` key, so the board decides the repository whoever is
  assigned. When the team picked the repository instead, a ticket asking for an erfbeeld README
  change was assigned to silver and the agent edited the wrong repository's README
  (webgrip/ploeg#30 (that repository is gone; Ploeg moved to ploeg-hq/ploeg), 2026-07-30). Ploeg Test
  is the exception: it pins its tickets to the `unfold` team (see the
  [Ploeg ↔ Unfold test runbook](../../../docs/techdocs/docs/runbooks/ploeg-unfold-test.md)).
- Boards are resolved by name at boot: ploegd logs what it resolved and refuses to start when a
  name matches nothing, so no bare project number says nothing about which board it is. Three are
  pinned by `id` as well: Ploeg Test (11); Unfold (10, the board the earlier Unfold boards merged
  into on 2026-09-29), so a rename cannot fail ploegd's boot; and Ploeg Bench (49), because the
  empty project 48 has the same name.
- Unfold routes by default to `unfold` and allows `homelab-cluster`: a ticket's `repo/*` label
  selects among registered `ploeg.config.targets` and never constructs a route, because tracker
  text is untrusted input
  ([Ploeg ADR-0015](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0015-routing-is-core-policy-over-provider-opaque-scopes.md),
  [Ploeg ADR-0038](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0038-a-repo-label-selects-among-registered-targets-and-the-board-default-is-the-fallback.md)).
  Other boards that touch several repositories, such as CI/CD, take the repository they touch most.
- Not routed on purpose: Forgejo Migration (irreducibly multi-repository, so any default is wrong
  more often than right), Vellum and Inbox (triage only).
- `forge: forgejo` is on every entry rather than left to the default. Leaving it out broke review
  publishing: ploegd read the forge setting twice, with a default for the forge registry and none
  for the target resolver, so every target carried an empty forge and the lookup missed. A
  reviewer approved [webgrip/erfbeeld#9](https://forgejo.webgrip.dev/webgrip/erfbeeld/pulls/9) on
  2026-07-30 and the pull request never heard about it. ploegd 0.2.0-rc.16 and later resolve an
  empty forge to the default; the value stays explicit so it is visible here.
- A board entry alone does not make assignment fire. Each routed board also needs the ploegd
  webhook registered on it and its team users shared in with read access, or assignment answers
  403 and nothing happens. twente.dev was routed on 2026-08-28 for its agent-ready tickets (first
  VIK-686, axe-core in CI); its webhook and share rollout is VIK-779.
- Ploeg Bench is the Mode A benchmark board: a bronze assignment there runs bronze's plan against
  the PB-01 world in `webgrip/ploeg-bench-world`, not erfbeeld. Its branch is the task's pre-fix
  base; the graded suites live in hidden branches the agent never sees. Use one fresh ticket per
  trial: reusing a ticket exercises the re-dispatch path and measures the wrong thing.

### `ploeg.config.teams`

- The board only sees team users. Roles (builder, reviewer, ...) live inside a Shift under
  `ploeg.executor.teams[].plan` and are not assignable. An assignee listed under two teams used to
  resolve by Go map order, sending one person's tickets to different teams on different boots;
  ploegd 0.2.0-rc.13 and later refuse to start on it instead.
- `bronze` and `silver` `forgeFollowUps`: a person's "request changes" on their pull request sends
  the Work Item back for a fix Round, and a failed check queues a bounded repair Follow-Up
  (`maxRepairs: 2`). Forgejo cannot deliver check events yet (Glide #1280).

### `ploeg.tracker`

Tracker write-backs are how a closed Shift reaches a person with the pull request link (old Ploeg
backlog #31). Without the URL and the token the provider stays a logging no-op: Runs still finish,
the board is just not updated.

### `ploeg.executor`

- `forgeTokenIsolation: proxy`: a writer's forge token stays inside `ploeg-worker`; the harness
  gets a placeholder and reaches only the Run's own repository through a loopback proxy
  ([Ploeg ADR-0034](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0034-the-harness-gets-placeholders-the-worker-keeps-credentials.md),
  Glide VIK-733). Every harness runs with `dind: false`, so none pushes from a sidecar that
  cannot reach the proxy.
- `harness.dind: false` is the estate default and overrides the chart's `dind: true`
  ([ADR-0053](../../../docs/techdocs/docs/adr/adr-0053-daemonless-agent-plane.md)). It is
  load-bearing: roles without a harness block of their own inherit it, and before it existed
  bronze's builder and silver ran privileged DinD sidecars nobody had written down. The namespace
  is back at PSA baseline and the privileged Kyverno waiver is deleted, so bringing a DinD sidecar
  back is a change that restores all three, not a values flip; gates that need containers run in
  CI, in CI's own images. `dindImage` is still set but no team uses it.
- `harness.idleTimeout: 45m`: native OpenHands prints nothing while it thinks and edits, and the
  idle watchdog counts only harness output. At the 15m default it killed bronze's builder on #555
  (Run 134, 2026-09-27) mid-work after US$0.24 of model calls. The harness timeout still bounds
  every Run.
- `harness.toolchains` and `harness.verify`: the kubelet mounts the Go toolchain read-only, so a
  Run can check its work without registry egress
  ([Ploeg ADR-0035](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0035-runs-get-ploeg-owned-skills-mounted-toolchains-and-worker-verification.md)).
  Module downloads stay blocked by the namespace's egress policy, so the check is gofmt-class
  only and runs only where `apps/ploeg/go.mod` exists; `ploeg-worker` re-runs it after a writer
  opens a pull request.
- `serviceAccountName` is deliberately unset. Workers run as `ploeg-worker`, which the chart
  creates; naming no account left them on `default`, which trips Kyverno's
  `require-non-default-serviceaccount`. Setting the key, even to `ploeg-worker`, tells the chart
  the account is managed elsewhere, so it stops creating it and every worker Job fails with
  `serviceaccount "ploeg-worker" not found`.
- `runnerImage` is pinned here because the chart default lags a release. Its history: 1.0.2 cut
  about five minutes of startup per Run (VIK-590), 1.2.0 was the first daemonless image
  (ADR-0053) on the DHI musl base with env-only key passing and an exit-trap key revoke.
  `ploeg-worker` is statically linked, so the musl base cannot break its init copy.
- `workerResources`: a Run mostly waits on the model. The CPU request is 100m so a Run plus Kata's
  overhead fits beside CI on the worker pool (2026-09-29); a full-core request fitted only
  fringe-workstation. The 1-CPU limit stays for bursts: the OpenHands CLI's single-threaded Python
  cold import took 2m20s at 500m (silver, 2026-07-27).
- `scaler.host` is the full service name because the KEDA operator resolves it from the `keda`
  namespace, where the chart's short default does not resolve.
- `pollingInterval: 5`: the chart's 30s was the largest slice of a cold dispatch (21s of 70s on the
  2026-08-26 silver smoke run). The trigger query is a `COUNT(*)` over the `agent_runs_claimable`
  partial index, so polling more often is free.

### `ploeg.executor.workerAuth.additionalLLMPolicies`

- `unfold`/`ask` and each team's `ask` policy: an Ask is one read-only call about a Work Item,
  paid from the team's monthly Ask Allowance (default US$2.00, US$0.02 per Ask)
  ([Unfold ADR-0031](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/docs/adr/adr-0031-people-ask-about-a-work-item-through-a-metered-read-only-ask-paid-from-a-monthly-allowance.md),
  [Ploeg ADR-0082](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0082-an-ask-is-a-read-only-run-outside-the-shift-paid-from-a-periodic-allowance.md)).
  GLM 5.3 Flash is the cheapest model the teams already use, about US$0.001 per Ask. A team
  without an ask policy cannot ask.
- `bronze`/`ask` also lists the Hetzner models: the Run health judge is an Ask that takes the first
  judge model the key offers and never falls back to a paid one
  ([Unfold application ADR-0046](https://forgejo.webgrip.dev/webgrip/unfold/src/branch/development/apps/unfold/docs/adrs/0046-a-running-runs-health-is-computed-from-its-own-facts-and-a-judge-only-advises.md)).
  Hetzner's experimental inference is free and EU-hosted; the Ask itself keeps the first model.

### `ploeg.executor.teams[bronze]`

- `budget` is the Shift pool all Rounds draw from, not a per-Run figure; the role `cap`s are the
  per-Run ceilings LiteLLM enforces. One writer, one reader and two fix Rounds of the same pair
  are six Runs, a worst case of US$7.20 (builder 2.00, reviewer 0.40). The shadow reviewer adds
  0.40 for each of its three possible review Rounds, so the pool is 9.20 and the shadow can never
  starve a fix Round or the reviewer. An overrun denies a Round rather than overspending the pool,
  and a Round denied for money looks like a stall.
- `repoName`/`baseBranch` are only a fallback: the board's routing rule wins, and every board pins
  its own branch. The base branch is explicit so a default-branch change cannot move the working
  tree (VIK-589).
- `maxFixRounds: 2` makes review a loop: a reviewer's `request_changes` reopens the writing Round
  with its findings, then re-reviews. It defaults to 0, which turns the loop off. The loop is
  bounded by money first, then this cap, then the verdict, and only a reading Role's verdict
  counts, so it cannot grade its own work
  ([Ploeg ADR-0017](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0017-the-review-loop-is-verdict-driven-and-capped.md)).
- One reader, not a fan-out: Rounds are sequential but a fan-out runs concurrently, and three
  readers at once do not fit the worker pool. The fan-out to reviewer and devops came off on
  2026-07-30 after both readers failed; the real causes were in ploegd (a reader got a shallow
  clone of the base, was not told about the pull request, and held a full push credential), fixed
  in 0.2.0-rc.14 (webgrip/ploeg#32).
- `harness.name: acp` with the `openhands` profile: over ACP the adapter sees every step as a
  protocol message, so its idle timer resets while the agent works and only a silent agent is
  stopped. Native headless OpenHands printed nothing until done, and the 45m watchdog killed 12
  busy Runs on 2026-09-29. `promptTimeout` bounds the whole Run.
- The reviewer's `harness` repeats `dind: false` on purpose, so a reading role can never regain a
  Docker daemon through an edit to the executor default.
- `shadow-reviewer` reviews the same pull request beside the reviewer and only records its verdict
  and findings; nothing acts on them
  ([Ploeg ADR-0096](https://github.com/ploeg-hq/ploeg/blob/development/docs/adrs/0096-a-shadow-reader-records-its-verdict-and-never-acts.md),
  VIK-2033). Claude Haiku is a third model family, to measure how often two families agree.

### `ploeg.executor.teams[copper]`

copper is the seam-smoke team. Its `exec` harness runs in the same agent-runner image without a
model call. For an ordinary ticket it writes a `stuck` outcome, "copper only runs canary items",
and prints nothing: the generated `taskspec.json` holds the description, findings and briefing,
and anything the harness prints lands in the pod log, VictoriaLogs and the Run's `stuck_reason`.
For a ticket titled `[canary]` it writes a `ploeg-canary-note`
Work Item Note, records whether earlier notes were briefed to it, and stops the Run as `stuck` so
the stop note is written. copper has no `plan`, so its `budget` is a per-Run ceiling, not a pool;
its `model` only scopes the key.
