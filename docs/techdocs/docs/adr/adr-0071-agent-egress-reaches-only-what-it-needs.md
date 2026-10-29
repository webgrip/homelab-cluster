---
status: accepted
date: 2026-10-29
decision-makers: Ryan Grippeling
---

# Agent egress reaches only what it needs: DNS, the model gateway, the forge and its own control plane

Technical Story: the 2026-10-18 hardening audit of the agent plane. Builds on
[ADR-0006](adr-0006-default-deny-network-policies.md) (opt-in default-deny),
[ADR-0005](adr-0005-cilium-gateway-egress-for-oidc.md) (identity-based gateway egress) and
[ADR-0053](adr-0053-daemonless-agent-plane.md) (the daemonless agent plane). The Unfold side is
Unfold ADR 0050 (`apps/unfold/docs/adrs/0050-agent-workspaces-reach-the-forge-in-cluster-never-through-a-gateway.md`
in `webgrip/unfold`).

## Context and Problem Statement

Agent pods run code a model chose. If a prompt injection in an issue, a dependency or a web page
takes over that code, the pod's network policy is what decides what it can touch next. The audit
of 2026-10-18 found three places where that policy was much wider than the work needs.

1. **Unfold workspaces** (namespace `unfold-workspaces`). Unfold writes one NetworkPolicy per
   session from the `workspaceEgress` value. The homelab value allowed Unfold on 4080, the whole
   `ai` namespace on 4000, the whole `forgejo` namespace on 3000, and
   `{to: [{namespaceSelector: network}]}` with no port. The `network` namespace holds
   envoy-internal, envoy-external, envoy-gateway, k8s-gateway, cloudflare-tunnel and
   cloudflare-dns. Through envoy-internal alone a workspace reached 39 route hostnames, among them
   Grafana, Prometheus, Alertmanager, Harbor, OpenBao, Longhorn, Vikunja, k8s-mcp and LiteLLM's UI,
   plus every port of every pod in that namespace. The rule existed because repositories are cloned
   from `https://forgejo.<domain>/...`, which resolves to envoy-internal.
2. **Ploeg workers** (namespace `ploeg`, `app.kubernetes.io/name: ploeg-worker`, both KEDA jobs and
   the Kata sandbox pods). `ploeg-allow-egress` selected every pod except `claude-runner`, so a
   worker reached every pod in `ploeg` on every port (the Ploeg database on 5432, Unfold on 4080,
   ploeg-mcp, the exporter) and the whole Vikunja namespace on 3456, which only ploegd uses. The
   worker itself talks to ploegd, LiteLLM, the forge and Alloy (`PLOEG_API_URL`, `LLM_BASE_URL`,
   `FORGE_URL`, telemetry) and nothing else. The sandbox launcher talks to the API server and
   ploegd.
3. **The Claude runner** (`claude-runner`, Ploeg ADR-0084) reaches envoy-external on 10443,
   because it clones `https://forgejo.<domain>` and the in-cluster Forgejo Service has no HTTPS.

The Unfold delivery verifier's check pods (`unfold-verifier`) already sit under a deny-all policy
that the verifier checks and probes before each run; they need no change.

What should an agent-executing pod be able to reach?

## Decision Drivers

* An agent pod reaches DNS, the model gateway, the forge and its own control plane (ploegd, or
  Unfold's relay), each by pod identity and port, and nothing else.
* No route from an agent pod to anything behind an ingress gateway: a gateway serves every
  application, not only the one the agent needs.
* Cilium enforces egress on the backend identity after Service translation
  ([ADR-0005](adr-0005-cilium-gateway-egress-for-oidc.md)), so rules name pods, never CIDRs.
* Running agent work keeps working through the change, and a probe proves both what is reachable
  and what is not.

## Considered Options

* Per-role egress by pod identity, and the forge through its in-cluster Service
* Keep namespace-wide rules, add a deny list for sensitive targets
* Route agent traffic through an egress proxy with a host allow-list

## Decision Outcome

Chosen option: "Per-role egress by pod identity, and the forge through its in-cluster Service",
because it states exactly what each agent role needs in the policy that selects it, and because
reaching the forge in the cluster removes the only reason a gateway was open to agents.

* **Unfold workspaces.** `workspaceEgress` allows the Unfold pod on 4080 (the relay), the LiteLLM
  pods (`app.kubernetes.io/name: litellm`) on 4000 and the Forgejo pods
  (`app.kubernetes.io/name: forgejo`) on 3000. The `network` rule goes. `workspaceGitRewrites`
  sets git's `url.http://forgejo-http.forgejo.svc.cluster.local:3000/.insteadOf
  https://forgejo.<domain>/` in the clone and agent containers (Unfold ADR 0050), so clones keep
  their public URL and travel to the in-cluster Service. The rewrite and the removal ship together,
  after the Unfold release that understands the value.
* **Ploeg workers.** `ploeg-allow-egress` leaves out `ploeg-worker` and `ploeg-sandbox-launcher` as
  it already left out `claude-runner`. `ploeg-worker-egress` allows ploegd
  (`ploeg.webgrip.dev/component: daemon`) on 8080, the LiteLLM pods on 4000, the Forgejo pods on
  3000 and alloy-gateway on 4318. Team pewter's workers keep their Anthropic FQDN policy.
  `ploeg-sandbox-launcher-egress` allows ploegd on 8080; its API-server rule is unchanged.
* **The Claude runner** keeps envoy-external on 10443 for now. Only the nine public routes sit
  behind envoy-external, all of which the internet already reaches, and the runner cannot clone over
  plain HTTP. Moving it to the in-cluster forge needs either HTTPS on the Forgejo Service or a
  runner option to clone over HTTP; that is follow-up work, not part of this record.
* Pods that run no model code (ploegd, Unfold, ploeg-mcp, the exporter, the tracker wiring) keep
  their policies.

### Consequences

* Good, because a hijacked workspace or Run can no longer reach Grafana, OpenBao, Harbor, the
  Ploeg database, Unfold's API or any other application behind the gateways.
* Good, because each rule names the pod and port it is for, so the policy reads as the list of
  what a Run talks to.
* Good, because the forge clone stays inside the cluster: no hairpin through a gateway.
* Bad, because the in-cluster Forgejo Service is plain HTTP, so a workspace's clone credential
  crosses the cluster network unencrypted, as Ploeg's workers' already does. Cilium's WireGuard
  encryption between nodes ([ADR-0004](adr-0004-cilium-wireguard-encryption.md)) covers the wire
  between nodes.
* Bad, because the selectors name labels set by the LiteLLM and Forgejo charts; a chart that
  renames them silently cuts agents off. The worker probe catches this for workers; for
  workspaces the first failing clone does.
* Bad, because the Claude runner still reaches envoy-external's public routes from inside the
  cluster, without Cloudflare in front.

### Confirmation

* `worker-egress-probe` (policy `worker-scoped`) runs as a worker-labelled Job: ploegd, LiteLLM and
  Forgejo answer; the Ploeg database, Unfold, ploeg-mcp, Vikunja, Omnigraph, the LiteLLM and
  Forgejo databases, the public hostnames, the LAN gateway addresses and the internet time out.
* `kubectl get networkpolicy -n unfold-workspaces -l app.kubernetes.io/name=unfold-agent -o yaml`
  shows no `network` namespace rule on a session policy created after the change, and that
  session's `clone` init container completes.
* `kubectl get networkpolicy -n ploeg ploeg-allow-egress -o jsonpath='{.spec.podSelector}'` lists
  `claude-runner`, `ploeg-worker` and `ploeg-sandbox-launcher` under `NotIn`.

## Pros and Cons of the Options

### Keep namespace-wide rules, add a deny list

* Good, because it is the smallest change.
* Bad, because Kubernetes NetworkPolicy has no deny rule; it needs Cilium deny policies, and a deny
  list is always one new application behind.

### An egress proxy with a host allow-list

* Good, because it could allow the forge by host name while keeping the public URL on the wire.
* Bad, because it is a new component on the hot path of every clone, model call and push, for a
  problem the git rewrite solves without one.

## More Information

* Unfold change: `kubernetes.gitRewrites` / chart value `workspaceGitRewrites` (Unfold ADR 0050).
* The workspace part ships in two steps: the pod selectors for LiteLLM and Forgejo now, the git
  rewrite and the removal of the `network` rule once an Unfold release with `workspaceGitRewrites`
  is pinned.
* 2026-10-18 — accepted by Ryan Grippeling as part of the agent-plane hardening.
* 2026-10-29 — the claude-runner with its envoy-external egress, the residual risk above, and team
  pewter's Anthropic egress are removed by
  [ADR-0088](adr-0088-no-stored-personal-claude-logins-in-the-cluster.md).
