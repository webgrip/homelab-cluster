---
status: proposed
date: 2026-09-27
---

# kagent acts only for the person asking: their broker token passes through, and machine principals keep only what pass-through cannot carry

Technical Story: VIK-1229 (kagent 1.0 pilot). Fires the D10 trigger of
[RFC: The access plane](../rfc/rfc-access-plane.md) for an in-cluster agent that needs the API,
and applies the pass-through answer
[RFC: MCP endpoints carry the caller's identity](../rfc/rfc-mcp-identity.md) gives `k8s-mcp`.

## Context and Problem Statement

The owner has settled the pilot's shape: wait for kagent 1.0 on Kubernetes 1.37, read the cluster
through the bundled kagent-tools in read-only mode, reach Grafana and VictoriaLogs through the
LiteLLM MCP gateway ([ADR-0044](adr-0044-metered-inference-plane-litellm.md)), and put the UI
behind gateway OIDC ([ADR-0060](adr-0060-gateway-oidc-for-apps-without-a-login.md)). The open
question was who kagent *is* when it calls the Kubernetes API, LiteLLM and the MCP gateway.

On 2026-09-27 the owner answered it: kagent never runs unattended. An agent acts only on behalf
of the person asking, interactively, with that person's identity passed through. There are no
alert-triggered or scheduled runs. That is D10's own default ("agents run under the human's own
credential"), so the first draft of this record, a standing machine identity for unattended
runs, is rejected.

kagent 1.0 is not the 0.10 architecture the ticket was researched on. At the latest tag,
[`v1.0.0-alpha4`](https://github.com/kagent-dev/kagent/tree/v1.0.0-alpha4) (2026-09-25; no GA
yet), the facts that shape identity are:

| Component | Identity it presents | Default reach | Source |
| --- | --- | --- | --- |
| Controller | ServiceAccount `kagent-controller` | Cluster-wide `get/list/watch` on core `*` (Secrets included) and `create/update/patch/delete` on core `*`, `apps/*`, `batch/*`, `gateway.networking.k8s.io/*`; `rbac.namespaces` turns every ClusterRole into per-namespace Roles | [getter-role](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/helm/kagent/templates/rbac/getter-role.yaml), [writer-role](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/helm/kagent/templates/rbac/writer-role.yaml), [values](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/helm/kagent/values.yaml) |
| kagent-tools 0.3.0 | Its own ServiceAccount, or the caller's bearer | `*/*/*` plus non-resource `*` unless `rbac.readOnly: true`, which renders get/list/watch on pods, pods/log, services, endpoints, configmaps, serviceaccounts, PVCs, namespaces, events, apps, batch, ingresses, networkpolicies, HPAs; Secrets only with `rbac.allowSecrets`; `--read-only` drops write tools including `shell`; `tools.k8s.tokenPassthrough` (`TOKEN_PASSTHROUGH=true`) hands the incoming `Authorization` bearer to kubectl and refuses a call that has none | [clusterrole](https://github.com/kagent-dev/tools/blob/v0.3.0/helm/kagent-tools/templates/clusterrole.yaml), [cmd/main.go](https://github.com/kagent-dev/tools/blob/v0.3.0/cmd/main.go), [pkg/k8s/k8s.go](https://github.com/kagent-dev/tools/blob/v0.3.0/pkg/k8s/k8s.go) |
| Agents | Not pods of their own: a `Harness` × `AgentTemplate` pair compiles to a Substrate Actor in a gVisor sandbox on a shared `WorkerPool` | No Kubernetes RBAC of their own | [architecture README](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/docs/architecture/README.md), [configuration-and-compilation](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/docs/architecture/configuration-and-compilation.md) |
| Substrate 0.2.0-beta5 (`ate-system`) | Pod identities from `PodCertificateRequest` signer `podidentity.podcert.ate.dev/identity`, trust via `ClusterTrustBundle`, actor JWTs from `actor-id-jwt-pool`, SA tokens with audience `api.ate-system.svc` to its API | Credential provider: cluster-wide Secret `get`; ate-controller: cluster-wide Secret `list/watch`; `atelet` DaemonSet is privileged with hostPath `/dev`; the PCR signer runs as the `default` SA | [setup-cluster.sh](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/scripts/setup-cluster/setup-cluster.sh), [kind-config](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/scripts/kind/kind-config.yaml), `helm template` of `oci://ghcr.io/kagent-dev/substrate/helm/substrate:0.2.0-beta5` |
| Credentials to models and MCP | Substrate's egress gateway injects the header from a Kubernetes Secret per destination hostname; the actor only sees a placeholder. Two different credentials for the same hostname and header are rejected, and a caller-token passthrough model cannot share a hostname with a static credential | Credential fetch is allowed per namespace by `credentialProvider.namespacePolicies` | [credential-injection](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/docs/architecture/credential-injection.md) |

### Identity pass-through in kagent 1.0

The chain exists in source at `v1.0.0-alpha4`; none of it is verified live:

1. **Gateway to UI and controller.** kagent's `trusted-proxy` auth mode takes the user from the
   `Authorization: Bearer <JWT>` an upstream proxy injects, with `--auth-user-id-claim` naming the
   claim. It does not check the signature; it trusts the proxy
   ([OIDC_PROXY_AUTH_ARCHITECTURE.md](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/docs/OIDC_PROXY_AUTH_ARCHITECTURE.md),
   [proxy_authn.go](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/internal/httpserver/auth/proxy_authn.go)).
   The upstream docs assume oauth2-proxy. Envoy Gateway's OIDC filter sends the broker's access
   token only with `oidc.forwardAccessToken: true`
   ([API reference](https://gateway.envoyproxy.io/docs/api/extension_types/#oidc)), which no
   `SecurityPolicy` in this repo sets today.
2. **Controller to actor.** The A2A gateway's `upstreamAuthInterceptor` copies the session's
   `Authorization` and `X-User-Id` onto every request to the private actor
   ([a2agateway/runtime.go](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/internal/a2agateway/runtime.go)).
   Instances are scoped to their creator
   ([a2agateway/gateway.go](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/internal/a2agateway/gateway.go)).
3. **Actor to MCP servers.** The kagent harness runtime forwards the incoming `Authorization` to
   every MCP server when `KAGENT_PROPAGATE_TOKEN=true`
   ([agent.go](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/adk/pkg/agent/agent.go),
   [mcp/registry.go](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/adk/pkg/mcp/registry.go)).
   The controller never sets that variable; `Harness.spec.env` can
   ([harness_types.go](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/api/v1alpha3/harness_types.go)).
4. **kagent-tools to the API server.** With `TOKEN_PASSTHROUGH=true` the tools server runs kubectl
   with the caller's bearer. The API server then validates the token itself, so the person's own
   RBAC applies and kagent's unverified parsing in step 1 cannot widen it.
5. **Actor to LiteLLM.** `ModelConfig.spec.apiKeyPassthrough` sends the caller's bearer as the
   model API key. LiteLLM OSS authenticates virtual keys; accepting a broker JWT is its
   [JWT auth](https://docs.litellm.ai/docs/proxy/token_auth), an Enterprise feature. The same
   holds for the MCP gateway, which is LiteLLM. Substrate's injected key would also overwrite a
   propagated `Authorization` on the LiteLLM hostname.

So a person's identity can reach the Kubernetes API through kagent. It cannot reach LiteLLM or
the LiteLLM MCP gateway in the OSS edition we run.

### Substrate prerequisites checked against 1.37

* **`PodCertificateRequest` is GA on Kubernetes 1.37 and on by default** (alpha 1.34, beta 1.35,
  GA 1.37, locked on in 1.38), as are `ClusterTrustBundle` and `ClusterTrustBundleProjection`
  ([kube_features.go at v1.37.0](https://github.com/kubernetes/kubernetes/blob/v1.37.0/pkg/features/kube_features.go),
  [KEP-4317](https://github.com/kubernetes/enhancements/issues/4317),
  [feature-gates reference](https://kubernetes.io/docs/reference/command-line-tools-reference/feature-gates/)).
  No feature-gate flag is needed. The API is served as `certificates.k8s.io/v1`. The beta
  `certificates.k8s.io/v1beta1` version stays off by default
  ([instance.go at v1.37.0](https://github.com/kubernetes/kubernetes/blob/v1.37.0/pkg/controlplane/instance.go)).
  Substrate `0.2.0-beta8` speaks only `v1beta1`. Substrate
  [`v0.3.0-alpha1`](https://github.com/kagent-dev/substrate/blob/v0.3.0-alpha1/cmd/podcertcontroller/internal/podcertificate/client.go)
  prefers `v1` for PodCertificateRequests but still reads and writes `ClusterTrustBundles` through
  `v1beta1`, so `--runtime-config=certificates.k8s.io/v1beta1=true` on the API server stays
  required until Substrate moves off it.
* **gVisor: Substrate cannot use the Talos gVisor extension.** The
  [siderolabs gvisor extension](https://github.com/siderolabs/extensions/tree/main/container-runtime/gvisor)
  installs `runsc` as a containerd runtime handler, used through a `RuntimeClass`. Substrate does
  not run actors that way. Its `ateom-gvisor` worker container calls `runsc` itself, from a
  binary atelet downloads, to create, checkpoint and restore sandboxes inside a normal runc pod
  ([architecture.md](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/docs/architecture.md),
  [ateom-gvisor/runsc.go](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/cmd/ateom-gvisor/runsc.go)).
  The binary is a `SandboxConfig` asset: a URL plus sha256, fetched from `gs://` anonymously or
  through atelet's own object-store client
  ([sandboxconfig_types.go](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/pkg/api/v1alpha1/sandboxconfig_types.go),
  [atelet/sandbox_assets.go](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/cmd/atelet/sandbox_assets.go)).
  There is no host-path asset and no `runtimeClassName` on a `WorkerPool`
  ([workerpool_types.go](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/pkg/api/v1alpha1/workerpool_types.go)).
  Running the worker pod under the extension's `RuntimeClass` would nest `runsc` inside gVisor,
  which Substrate does not support. The closest option that avoids a nightly is a pinned gVisor
  release tarball staged in the object store Substrate already uses, provided that release
  carries the `-allow-connected-on-save` flag Substrate passes
  ([gVisor flags.go](https://github.com/google/gvisor/blob/master/runsc/config/flags.go)). That
  is still a downloaded `runsc`, not the extension. The privileges stay either way: `atelet`
  runs `privileged: true`
  ([atelet.yaml](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/charts/substrate/templates/atelet.yaml)),
  and every worker pod runs as root with thirteen added capabilities (`SYS_ADMIN`, `NET_ADMIN`,
  `SYS_PTRACE` among them), seccomp and AppArmor `Unconfined`, and a hostPath
  ([workerpool_apply.go](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/cmd/atecontroller/internal/controllers/workerpool_apply.go)).
  Like the extension, it also needs the Talos `user.max_user_namespaces` sysctl raised from its
  hardened default. The pilot is blocked here until the owner decides.

## Decision Drivers

* An agent acts only for the person who asked, with that person's identity. No unattended,
  scheduled or alert-triggered runs.
* Nothing kagent runs may read a Secret outside its own namespace, or write anything outside it.
* Every call must land under a named principal in the audit log and the spend ledger.
* No credential in an actor's environment; revocation must be one edit.
* Reuse the existing patterns: the broker as the one identity source, a LiteLLM key minted
  in-cluster and registered by an idempotent Job, deny-by-default MCP grants.

## Considered Options

* **Token pass-through of the person's broker token for Kubernetes; namespaced controller; one budgeted LiteLLM key per agent**
* Own ServiceAccounts, read-only and Secret-free, as the executing identity (the rejected first draft)
* Route Kubernetes reads through `k8s-mcp` on the LiteLLM gateway
* Impersonation via the access plane's `act-as-human`
* One shared LiteLLM key for all of kagent

## Decision Outcome

Chosen option: **pass-through of the person's broker token for Kubernetes, with machine
principals kept only where pass-through cannot reach**, because the owner requires that an agent
acts only for the person asking, and the Kubernetes leg is the one where kagent 1.0 can carry
that identity end to end.

**(a) Who can start an agent**

* Only a person through the UI or kagent's `/mcp` endpoint, behind the gateway OIDC policy of
  ADR-0060. No scheduled runs, no alert hooks, no A2A callers from outside `kagent`.
* kagent runs `--auth-mode=trusted-proxy` with `--auth-user-id-claim=email`. Because it trusts
  the proxy without checking signatures, a NetworkPolicy admits the UI and controller ports from
  the Envoy gateway only.

**(b) Kubernetes API**

* The kagent `SecurityPolicy` sets `oidc.forwardAccessToken: true`, so the broker's access token
  (audience `kagent`) reaches kagent as `Authorization: Bearer`.
* The kagent harness sets `KAGENT_PROPAGATE_TOKEN=true` in `Harness.spec.env`.
* `kagent-tools`: `tools.k8s.tokenPassthrough: true`, `rbac.readOnly: true`,
  `rbac.allowSecrets: false`, `tools.args: [--read-only]`, `tools.enabledTools: [k8s]`. Helm is
  out: it reads release Secrets.
* The API server trusts the broker for audience `kagent` alongside `mcp`, in the structured
  authentication configuration of rfc-mcp-identity stage 3, with the same `oidc:` prefix on
  `email`. The person's own bindings apply.
* Read scope for a person using kagent is cluster-wide read of `pods/log` and `configmaps`, never
  Secrets. The owner accepted that on 2026-09-27.
* **Open, for the owner:** if the pilot shows pass-through does not survive the chain (for
  example, the Substrate egress path drops `Authorization` to `kagent-tools`, or the token
  expires mid-turn), the fallback is the first draft's read-only tools ServiceAccount as the
  executing identity: cluster-wide get/list/watch with no Secrets, no write verbs and no
  non-resource URLs. The person would then appear only in kagent's own session record, not in
  the API audit. This record does not choose the fallback.
* Controller: `rbac.namespaces: [kagent]`, so its write role and its Secret access become Roles
  in `kagent` only. `Harness`, `AgentTemplate`, `WorkerPool` and the key Secrets all live there.
* Actors: no Kubernetes identity. The `WorkerPool` template sets
  `automountServiceAccountToken: false`, if Substrate allows it.
* Substrate: the credential provider's cluster-wide Secret `get` is narrowed by a Kustomize patch
  to a RoleBinding in `kagent`, to match `namespacePolicies: [{atespace: kagent,
  allowedNamespaces: [kagent]}]`. The CA and JWT pools (`egress-mitm-ca-pool`,
  `actor-id-jwt-pool` and the pod-identity pools) are created by an idempotent in-cluster
  provisioner Job on the `provisioner-job` pattern, not by `kubectl-ate` from a laptop. Their
  keys exist only in the cluster.

**(c) LiteLLM**

* One virtual key per `AgentTemplate` (pilot: `kagent-k8s`, `kagent-observability`), in a LiteLLM
  team `kagent`. Each key allows one tool-calling model alias, with an RPM cap. Budgets, accepted
  by the owner on 2026-09-27: USD 5 per key and USD 10 for the team, per 30 days.
* The key is entropy, generated in-cluster and registered by an idempotent Job, the
  `omnigraph-embed-key` pattern ([runbook](../runbooks/omnigraph.md)). It sits in a Secret in
  `kagent` that the Substrate egress gateway injects. It never enters an actor.
* Because injection is keyed on hostname and header, an agent's model calls and its MCP calls to
  LiteLLM must use the same key.
* **Open, for the owner:** the spend ledger shows the agent key, not the person, because OSS
  LiteLLM cannot authenticate a broker token. Whether that is acceptable, or whether the
  person's identity should ride along as LiteLLM's end-user field, is undecided.

**(d) MCP gateway**

* A new access group `kagent-observability` on the `grafana` and `victorialogs` servers only. The
  `kagent-observability` key is granted that group. `kagent-k8s` gets no MCP grant. No kagent key
  gets `board` or `memory`.
* **Open, for the owner:** these calls carry the agent key, not the person. The alternative is
  to point the observability agent's `RemoteMCPServer`s at the broker-verified MCP routes of
  rfc-mcp-identity, which would need those routes to accept audience `kagent`.

**Roster (D10).** `people.yaml` gains `kind: machine`, `role: service` entries for
`kagent-controller`, `kagent-agents` (the key holders) and `substrate`, plus `kagent-tools` only
if the fallback in (b) is chosen. `substrate` lists its cluster-wide PCR signing and privileged
node agent in its `purpose`. None holds a capability. No principal acts for a person by
impersonation, so `act-as-human` stays unbuilt.

**Pilot agents.** `kagent-k8s` and `kagent-observability`, confirmed by the owner. kagent
`v1.0.0-alpha4` ships no pre-built agents: its chart has no `agents/` directory, and the only
`AgentTemplate` upstream installs is the tool-less `assistant` in
[setup-cluster.sh](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/scripts/setup-cluster/setup-cluster.sh).
The catalog below is the last 0.x chart,
[`v0.10.2/helm/agents`](https://github.com/kagent-dev/kagent/tree/v0.10.2/helm/agents). Each
would have to be ported to a `Harness` × `AgentTemplate` pair.

| 0.10.2 agent | Purpose | Fits read-only, no helm, no Secrets, our stack? |
| --- | --- | --- |
| `k8s` | Kubernetes operations and troubleshooting | Yes, as the read-only subset; basis of `kagent-k8s` |
| `observability` | Prometheus queries, Grafana dashboards, resource checks | Yes, re-pointed at VictoriaMetrics and the MCP gateway, without dashboard creation; basis of `kagent-observability` |
| `promql` | Writes PromQL from natural language; no tools | Yes; a candidate third agent (MetricsQL accepts PromQL) |
| `cilium-policy` | Drafts CiliumNetworkPolicy from natural language | Drafting only; its validate tool execs into Cilium pods, and output lands through Git |
| `cilium-debug` | Cilium diagnostics | No: every tool is `kubectl exec` into `kube-system` Cilium pods, and some flush or change state |
| `cilium-manager` | Installs, upgrades and toggles Cilium | No: writes, and Cilium is Talos- and Flux-managed |
| `helm` | Helm release management | No: helm reads release Secrets, and it uses `shell` |
| `istio` | Istio operations | No: no Istio here, and it writes |
| `kgateway` | kgateway operations | No: we run Envoy Gateway, and it uses helm and writes |
| `argo-rollouts` | Converts Deployments to Argo Rollouts | No: no Argo Rollouts here, and it writes |

### Consequences

* Good, because an agent's Kubernetes reads appear in the audit log as `oidc:<email>` of the
  person who asked, and never exceed that person's RBAC.
* Good, because no standing read identity exists on the Kubernetes path, the property
  rfc-mcp-identity removes from `k8s-mcp`.
* Good, because each agent key is one revocation point, and the team budget at zero is the kill
  switch ADR-0044 describes.
* Bad, because the LiteLLM and MCP gateway legs still act under agent keys. Person attribution
  there depends on an open owner decision.
* Bad, because kagent's trusted-proxy mode parses tokens without verifying them. Only the
  NetworkPolicy keeps a forged header out, and only the API server's own validation keeps it
  from mattering on the Kubernetes path.
* Bad, because cluster-wide `pods/log` and `configmaps` reads remain for whoever uses kagent. A
  log line or ConfigMap that holds a secret is readable. The owner accepted this.
* Bad, because 1.0 brings Substrate: a privileged DaemonSet, root worker pods with thirteen
  capabilities and no seccomp or AppArmor confinement, a second Postgres, bundled S3 (rustfs), an
  in-cluster CA provisioner, and the `certificates.k8s.io/v1beta1` API. The Talos gVisor
  extension removes none of it.

### Confirmation

1. An agent call made by a person shows up in the API audit as `oidc:<their email>` with the
   kagent-tools user agent. `KubernetesImpersonationUsed` stays quiet.
2. A call to `kagent-tools` without a bearer fails with `Bearer token required when
   TOKEN_PASSTHROUGH is true`.
3. `kubectl auth can-i get secrets -n observability --as=system:serviceaccount:kagent:kagent-controller`
   is `no`. The same check for the Substrate credential provider is `no` outside `kagent`.
4. The tools server's tool list has no `shell` and no `helm_*` entries.
5. A `kagent-k8s` call to the MCP gateway lists zero tools. `kagent-observability` lists only
   `grafana_*` and `victorialogs_*`.
6. Exhausting a key's USD 5 budget returns a LiteLLM budget error in the agent's task, and both
   keys show as separate rows in the spend ledger.
7. `grep` over a running actor's environment finds no LiteLLM key.
8. kagent lists no scheduled runs, and nothing outside `kagent` can reach its A2A endpoint.
9. The CA pool Secrets in `ate-system` carry the provisioner Job's labels and no
   `kubectl-ate` field manager.

## Pros and Cons of the Options

### Token pass-through of the person's broker token

* Good, because the audit shows the person and their own RBAC bounds the agent.
* Bad, because it depends on four hops in alpha software, none verified live.
* Bad, because LiteLLM OSS cannot accept the token, so it covers Kubernetes only.

### Own ServiceAccounts, read-only, as the executing identity

* Good, because it works without a person and matches the roster model.
* Bad, because it is a standing, non-person read identity, and the owner rejected unattended
  agents. Kept only as a fallback the owner may choose.

### `k8s-mcp` through the LiteLLM gateway

* Good, because no new Kubernetes principal is needed.
* Bad, because the LiteLLM hostname carries the agent's injected key, which overwrites the
  person's `Authorization` before it reaches `k8s-mcp`.

### Impersonation (`act-as-human`)

* Bad, because pass-through already carries the person, and impersonation would give
  `KubernetesImpersonationUsed` a standing allow-list entry.

### One shared LiteLLM key

* Good, because there is one Secret, and the hostname rule is satisfied trivially.
* Bad, because the ledger can no longer tell the agents apart, and the MCP grant becomes the
  union of every agent's needs.

## More Information

* Unverified until the pilot or GA:
    * the Substrate chart version 1.0 GA pins, and whether it still needs
      `certificates.k8s.io/v1beta1`;
    * each hop of the pass-through chain, live, including whether Substrate's egress path keeps
      `Authorization` on plain HTTP to `kagent-tools` and whether a long turn outlives the token;
    * whether the controller works under `rbac.namespaces` with Substrate on;
    * whether the credential provider accepts a namespaced RoleBinding;
    * whether `WorkerPool.spec.template` takes `automountServiceAccountToken`;
    * whether the egress gateway injects on plain in-cluster HTTP to `litellm.ai.svc`.
* Open for the owner:
    * the gVisor path, now that the Talos extension is ruled out: a pinned release tarball in our
      object store, or no pilot;
    * the fallback executing identity in (b) if pass-through fails;
    * person attribution on the LiteLLM and MCP gateway legs, (c) and (d);
    * enabling the beta `certificates.k8s.io/v1beta1` API, which the feature-gate rule does not
      cover.
* Relates to [ADR-0044](adr-0044-metered-inference-plane-litellm.md),
  [ADR-0055](adr-0055-one-secrets-model-six-levels.md) (keys and CA pools are generated
  in-cluster), [ADR-0058](adr-0058-access-plane-one-module-one-model.md) and
  [ADR-0060](adr-0060-gateway-oidc-for-apps-without-a-login.md).
* 2026-09-27: proposed. Researched against kagent `v1.0.0-alpha4`, kagent-tools `v0.3.0` and
  Substrate `0.2.0-beta5`. Re-check the table above against the 1.0 GA tag before accepting.
* 2026-09-27: owner decisions recorded. Unattended machine identity rejected; agents act only
  for the person asking, so the chosen option moved to token pass-through. Accepted: cluster-wide
  read of `pods/log` and `configmaps` without Secrets, CA pools from an in-cluster provisioner
  Job, USD 5 per key and USD 10 per team per 30 days, pilot agents `kagent-k8s` and
  `kagent-observability`. `PodCertificateRequest` allowed only at beta or GA on 1.37: it is GA.
  Substrate's nightly `runsc` refused in favour of the Talos gVisor extension: Substrate cannot
  use it, so the pilot is blocked on the owner. Researched against Substrate `v0.2.0-beta8` and
  `v0.3.0-alpha1` and Kubernetes `v1.37.0`. Status stays proposed until the GA re-check.
