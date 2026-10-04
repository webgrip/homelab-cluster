---
status: proposed
date: 2026-10-04
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

1. **Gateway to UI and controller.** The upstream controller binary at `v1.0.0-alpha4` has no
   authentication. `main.go` calls `app.Run(ctx, app.Options{})`
   ([main.go L39-41](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/cmd/controller/main.go#L39-L41)),
   and a nil `Authenticator` selects `UnsecureAuthenticator`
   ([app.go L119-124](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/pkg/app/app.go#L119-L124)).
   That authenticator takes the user from `?user_id=` or `X-User-Id`, defaults to
   `admin@kagent.dev`, and forwards whatever `Authorization` arrived
   ([authn.go L24-60](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/internal/httpserver/auth/authn.go#L24-L60)).
   The chart still renders `AUTH_MODE`, but no Go code reads it. `trusted-proxy`
   ([proxy_authn.go](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/internal/httpserver/auth/proxy_authn.go))
   is only reachable by a consumer that builds its own binary, and it sits under `internal/`, so
   that consumer must be a fork. v0.10.2 did wire it
   ([v0.10.2 main.go L47-48](https://github.com/kagent-dev/kagent/blob/v0.10.2/go/core/cmd/controller/main.go#L47-L48)).
   Envoy Gateway's OIDC filter sends the broker's access token as `Authorization: Bearer` only
   with `oidc.forwardAccessToken: true`, which no `SecurityPolicy` in this repo sets today
   ([oidc_types.go at v1.9.1](https://github.com/envoyproxy/gateway/blob/v1.9.1/api/v1alpha1/oidc_types.go),
   [API reference](https://gateway.envoyproxy.io/docs/api/extension_types/#oidc)).
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
  hardened default. The owner decided this on 2026-09-27, in (e) below.

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
* kagent 1.0 authenticates no one itself (see step 1 above), so the gateway is the whole door.
  The kagent `SecurityPolicy` pairs `oidc` with a `jwt` provider on the same broker client. The
  `jwt` provider verifies the forwarded access token and `claimToHeaders` writes `email` into
  `X-User-Id`, overwriting anything the client sent. The route strips `X-Agent-Name`. A
  NetworkPolicy admits kagent's UI, controller and A2A ports from the Envoy gateway only. The
  owner accepted piloting the alpha build, which authenticates no one, only behind these two
  controls together (2026-09-27, round 3). Whether the `jwt`
  filter sees the token the OIDC filter just forwarded is unverified, and it is step 2 of the
  spike below.

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
* The owner declined to pick a fallback for a failed pass-through. Identity is the component
  this pilot exists to get right, so the options were researched instead. They are compared in
  [Person-bound identity: the options](#person-bound-identity-the-options), which ends in a
  recommendation and a spike. The owner adopted it on 2026-09-27 (round 3), which changes two
  details of this section: the API server maps the kagent audience to its own username prefix,
  `kagent:`, and a person's agent bindings are the read-only `human-reader` binding only. An
  agent never carries the person's full rights, even for a person who can write.
* The Authentik `kagent` provider's access tokens live 15 minutes. A run cannot outlive the
  token it started with. The gateway requests `offline_access`, so Envoy refreshes the token
  without a login page.
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
* The spend ledger shows the agent key, not the person, because OSS LiteLLM cannot authenticate
  a broker token. The owner accepted per-agent keys without the person on 2026-09-27.

**(d) MCP gateway**

* A new access group `kagent-observability` on the `grafana` and `victorialogs` servers only. The
  `kagent-observability` key is granted that group. `kagent-k8s` gets no MCP grant. No kagent key
  gets `board` or `memory`.
* These calls carry the agent key, not the person. The owner accepted that on 2026-09-27.
  Pointing the observability agent's `RemoteMCPServer`s at the broker-verified MCP routes of
  rfc-mcp-identity stays possible later, once those routes accept a kagent audience.

**(e) Substrate and gVisor**

The owner accepts Substrate's privileges for the pilot, on one condition: `runsc` comes from a
checksum-pinned gVisor release tarball in our own Garage S3, never a nightly fetched from the
internet.

* **Asset.** The chart's cluster-wide `SandboxConfig` is replaced by one whose `gvisor` asset
  for `x86_64` is `s3://substrate-assets/gvisor/release-20260921.0/x86_64/gvisor.tar.zstd` with
  the tarball's `sha256`. gVisor publishes release tarballs next to the nightlies
  (`gs://gvisor/releases/release/20260921.0/x86_64/gvisor.tar.zstd` and `.sha512`, checked
  2026-09-27), and `release-20260921.0` carries the `allow-connected-on-save` flag Substrate passes
  ([flags.go L46](https://github.com/google/gvisor/blob/release-20260921.0/runsc/config/flags.go#L46)).
  The chart's default points at `gs://gvisor/releases/nightly/2026-09-02/…`
  ([sandboxconfig-gvisor.yaml L30](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/charts/substrate/templates/sandboxconfig-gvisor.yaml#L30)).
  The pilot has no ARM nodes, so there is no `aarch64` asset. The chart's admission rule requires
  a `gvisor` asset for each key under `spec.assets`, so a config listing only `x86_64` passes it
  ([sandboxconfig-validation.yaml L34-40](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/charts/substrate/templates/sandboxconfig-validation.yaml#L34-L40)).
* **How atelet reads Garage.** atelet ignores the URL scheme. The host is the bucket and the
  path is the key
  ([objects.go L479-485](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/cmd/atelet/internal/ategcs/objects.go#L479-L485)).
  It tries an anonymous GCS client first and then its one main client
  ([sandbox_assets.go L437-449](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/cmd/atelet/sandbox_assets.go#L437-L449)).
  `ATE_STORAGE_BACKEND=s3` makes that main client S3, configured by the standard AWS variables
  ([atelet main.go L225-240](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/cmd/atelet/main.go#L225-L240)):
  `AWS_ENDPOINT_URL` set to Garage at `10.0.0.110:3900`, `AWS_S3_USE_PATH_STYLE=true`, and a
  Garage key delivered through ESO. The main client is atelet-wide, so Substrate's snapshots move
  to Garage too, and the bundled rustfs is not installed. The Garage key reads
  `substrate-assets` and reads and writes the snapshot bucket, nothing else. The sha256 check
  ([sandbox_assets.go L262-315](https://github.com/kagent-dev/substrate/blob/v0.2.0-beta8/cmd/atelet/sandbox_assets.go#L262-L315))
  stops a public GCS bucket of the same name from serving a different binary. Denying atelet
  egress to `storage.googleapis.com` makes Garage the only source.
* **How the tarball gets there.** An idempotent provisioner Job on the `provisioner-job`
  pattern, in `ate-system`. Git pins the release as a `# renovate: datasource=github-tags
  depName=google/gvisor` value (`release-YYYYMMDD.N`) next to the expected sha256. The Job
  downloads the tarball and its `.sha512` from `storage.googleapis.com`, checks both the
  published sha512 and the pinned sha256, and uploads only when both match and the object is
  absent. Renovate cannot compute the new sha256, so its PR fails the Job's check until someone
  commits the hash. That failure is the gate: no unreviewed binary reaches a node. A manual
  upload was rejected because it leaves nothing in Git that the cluster can rebuild from.
* **Kyverno.** Two `Deny` policies would refuse Substrate. Each gets one CEL `PolicyException`
  that matches named objects only:
    * `pod-security-baseline-privileged`: DaemonSet `ate-system/atelet` and Pods it owns
      (`privileged: true`).
    * `pod-security-baseline-host-path`: DaemonSet `ate-system/atelet` and its Pods (`/dev`,
      `/var/lib/ateom-gvisor`, `/var/lib/kubelet/plugins`, `/var/lib/kubelet/device-plugins`),
      plus the pilot `WorkerPool`'s Deployment in `kagent` and its Pods (`/run/ateom`, and
      `/dev/net/tun` when present).
    * Waived on the same objects so the audit report stays readable:
      `workload-advanced-baseline-audit` (AppArmor `Unconfined`, capabilities outside the
      baseline set), `workload-drop-all-capabilities-audit`, `workload-root-identity-audit`,
      `workload-risky-volumes-audit`.
    * Not waived: `image-supply-chain-*` and `require-pod-probes-audit`. The images are pinned by
      digest in our values, and a probe gap on a Substrate pod gets fixed, not excused.
      `seccomp-default-mutate` skips pods with a privileged container and only fills in a
      profile where none is declared. The workers declare `Unconfined` per container, which
      takes precedence over a pod-level default, so the policy needs no change. The spike
      confirms this on a live worker pod.
  The owner prefers no exceptions, so both files are tracked debt. Each carries
  `owner: platform-team`, names this ADR, and sits in the exception ledger under
  More Information. Retire them when Substrate runs its workers without host paths, or when the
  pilot ends.

**(f) The beta `certificates.k8s.io/v1beta1` API**

* Enabled only for the pilot, with `runtime-config: certificates.k8s.io/v1beta1=true` in the API
  server's `extraArgs` in `talos/patches/controller/cluster.yaml`. That is one Talos apply per
  control plane, the same routine as the authentication change.
* **Removal trigger:** the first Substrate release that reads and writes `ClusterTrustBundles`
  through `certificates.k8s.io/v1`. The flag is removed in the same commit that moves the
  Substrate chart to that release. It is also removed when the pilot ends. If Kubernetes stops
  serving the beta API first, the pilot pauses; the flag does not stay.

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

* Good, because an agent's Kubernetes reads appear in the audit log as `kagent:<email>` of the
  person who asked, holding only read-only bindings. They never exceed `human-reader`, whatever
  that person's own RBAC.
* Good, because no standing read identity exists on the Kubernetes path, the property
  rfc-mcp-identity removes from `k8s-mcp`.
* Good, because each agent key is one revocation point, and the team budget at zero is the kill
  switch ADR-0044 describes.
* Bad, because the LiteLLM and MCP gateway legs act under agent keys, without the person. The
  owner accepted this.
* Bad, because kagent 1.0 authenticates no one itself and trusts `X-User-Id` as sent. Only the
  gateway's verified header and the NetworkPolicy keep a forged identity out of kagent, and only
  the API server's own validation keeps it from mattering on the Kubernetes path.
* Bad, because two PolicyExceptions (privileged and host paths, for Substrate) stay open for the
  pilot's life, against the owner's preference for none.
* Bad, because cluster-wide `pods/log` and `configmaps` reads remain for whoever uses kagent. A
  log line or ConfigMap that holds a secret is readable. The owner accepted this.
* Bad, because 1.0 brings Substrate: a privileged DaemonSet, root worker pods with thirteen
  capabilities and no seccomp or AppArmor confinement, a second Postgres, snapshots in Garage, an
  in-cluster CA provisioner, and the `certificates.k8s.io/v1beta1` API. The Talos gVisor
  extension removes none of it.

### Confirmation

1. An agent call made by a person shows up in the API audit as `kagent:<their email>`, with the
   kagent-tools user agent. `KubernetesImpersonationUsed` stays quiet.
   `kubectl auth can-i create pods --as=kagent:<owner email>` is `no`.
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
10. The live `SandboxConfig` asset URL names the Garage bucket and its sha256 equals the one in
    Git. atelet's egress to `storage.googleapis.com` is refused.
11. Both Substrate PolicyExceptions match only the named DaemonSet, Deployment and their Pods:
    a test Pod in `kagent` with a hostPath is still denied.
12. The API server's flags carry `certificates.k8s.io/v1beta1=true` only while a Substrate
    release that needs it is installed.
13. A NetworkPolicy in `kagent` admits the UI, controller and A2A ports from the Envoy gateway
    only: a test Pod in another namespace, and one in `kagent` itself, gets no connection to any
    of them, while the UI works through the gateway.
14. A token issued by the Authentik `kagent` provider has `exp - iat` of 900 seconds.

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

## Person-bound identity: the options

Researched on 2026-09-27 against kagent
[`v1.0.0-alpha4`](https://github.com/kagent-dev/kagent/tree/v1.0.0-alpha4) (`8be872b`), kagent-tools
`v0.3.0`, Authentik
[`version/2026.8.3`](https://github.com/goauthentik/authentik/tree/version/2026.8.3), Envoy
Gateway [`v1.9.1`](https://github.com/envoyproxy/gateway/tree/v1.9.1) (the version running
here) and Kubernetes `v1.37.1`. "Verified" means read in source or docs at those tags. Nothing
here has run live yet.

"Person-bound" means five things here. The API server authenticates the person, not a
component. The token is only good at the API server. It dies within minutes of the person
leaving. Revoking the person stops the agent. The audit log names the person and shows that an
agent made the call.

### What every option shares

* **Where the token rides (verified).** Envoy forwards the access token on every request to
  kagent. The controller copies `Authorization` and `X-User-Id` onto each A2A call to the actor
  ([runtime.go L89-107](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/internal/a2agateway/runtime.go#L89-L107)).
  Each MCP request of a run reads that call's `Authorization` again
  ([registry.go L314-329](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/adk/pkg/mcp/registry.go#L314-L329)).
  Sub-agents called through the remote A2A tool get it too
  ([remote_a2a_tool.go L289](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/adk/pkg/tools/remote_a2a_tool.go#L289)).
  So every tool call of a multi-step run carries the token that started the run. A new chat
  message brings a new token.
* **Lifetime mid-run (verified in code, unverified live).** Authentik access tokens here live
  one hour (`access_token_validity = "hours=1"` in
  `kubernetes/apps/security/access-plane/tofu/broker/applications.tf`). Envoy refreshes an
  expired token and forwards the new one on that same request
  (`refreshToken` defaults to true since Envoy Gateway v1.6.0;
  [translator oidc.go](https://github.com/envoyproxy/gateway/blob/v1.9.1/internal/xds/translator/oidc.go)).
  Authentik only issues a refresh token when the `offline_access` scope is requested
  ([views/token.py L151, L183](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/providers/oauth2/views/token.py#L151)),
  and Envoy Gateway adds only `openid` by itself. None of our `SecurityPolicy`s asks for
  `offline_access`, so today they send the person back to the login page after an hour. Neither
  side re-issues a token during a run. A run that outlives the token's remaining lifetime gets a
  401 from the API server on its next tool call. The person's next message carries a fresh
  token.
* **Authentik's claims vs the API server (verified).** An access token is a JWT signed with the
  provider's key. `aud` is the provider's `client_id`
  ([id_token.py L93](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/providers/oauth2/id_token.py#L93))
  and `iss` is `https://authentik.<domain>/application/o/<slug>/`, one issuer per provider. The
  default `email` mapping hard-codes `email_verified: False`
  ([providers-oauth2.yaml L24-28](https://github.com/goauthentik/authentik/blob/version/2026.8.3/blueprints/system/providers-oauth2.yaml#L24-L28)).
  An API server with `username.claim: email` refuses such a token ("oidc: email not verified",
  [oidc.go](https://github.com/kubernetes/kubernetes/blob/v1.37.1/staging/src/k8s.io/apiserver/plugin/pkg/authenticator/token/oidc/oidc.go)).
  Two ways around it: set the provider's subject mode to the user's email and map `sub`, or give
  the provider its own email mapping that asserts `email_verified: true`. Every broker login
  comes from Google Workspace with `hd=webgrip.nl`, so the second is honest. rfc-mcp-identity's
  audience `mcp` has the same problem and does not mention it.
* **The API server's trust (verified).** The Talos 1.14 contract (VIK-1239, commit `c671e066`)
  expresses authentication as a `KubeAuthenticationConfig` with a `jwt[]` list holding Google.
  It is on branch `prep/talos-1.14-contract`, not on `main`, where the four `oidc-*` flags still
  apply. Each issuer URL may appear once
  ([validation.go L67-73](https://github.com/kubernetes/kubernetes/blob/v1.37.1/staging/src/k8s.io/apiserver/pkg/apis/apiserver/validation/validation.go#L67-L73)),
  which fits Authentik's per-provider issuers. The API server runs on the host network. Its
  discovery goes through LAN DNS to `envoy-internal`. While Authentik is down, only the broker
  entries fail; the Google door of D7 stays open.
* **kagent's own record of the person.** In the 1.0 binary this is `X-User-Id`, trusted as
  sent. Instance ownership and history are keyed on it
  ([gateway.go L123](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/core/internal/a2agateway/gateway.go#L123)).
  The gateway must write it from a verified claim, as in (a).

### Option 1: pass the gateway's access token straight through

**End to end.** Authentik provider `kagent` (client and audience `kagent`) → Envoy
`oidc.forwardAccessToken: true` → controller → actor with `KAGENT_PROPAGATE_TOKEN=true` →
kagent-tools with `TOKEN_PASSTHROUGH=true`, which runs `kubectl --token <bearer>`
([k8s.go L821-830](https://github.com/kagent-dev/tools/blob/v0.3.0/pkg/k8s/k8s.go#L821-L830),
[builder.go L254](https://github.com/kagent-dev/tools/blob/v0.3.0/internal/commands/builder.go#L254))
→ the API server, which trusts issuer `…/application/o/kagent/` for audience `kagent`.

* **Verified:** every hop in source. The token has the right shape and a fixable `email`
  mapping.
* **Unverified:** whether Substrate's egress path keeps `Authorization` on plain HTTP to
  kagent-tools; whether Envoy's `jwt` filter sees the token the OIDC filter forwards; that the
  API server accepts the token live.
* **Audience and scope.** One token authenticates the person to the kagent UI and to the API
  server. Its reach at the API server is the person's full RBAC. kagent-tools' `--read-only`
  limits the tools, not the token. For the owner that is `k8s-admin`.
* **Replay.** It is a bearer token. The controller, the actor, the Substrate egress gateway
  (which intercepts TLS) and kagent-tools all see it, and any of them can replay it as the owner
  until it expires.
* **Lifetime and revocation.** Up to one hour. The API server validates offline, so revoking
  the Authentik session stops nothing already issued.
* **Audit.** `oidc:<email>` with kubectl's user agent. An agent call and a laptop `kubectl`
  call from the same person differ only in user agent.
* **Cost.** Smallest: one broker provider, one `jwt` entry, three chart values, one
  `SecurityPolicy`.

**Variant 1b: its own username prefix.** The `jwt` entry for audience `kagent` maps the username
with the prefix `kagent:` instead of `oidc:`. The API server then sees `kagent:ryan@webgrip.nl`,
a different user with no bindings. The access-plane module renders one read-only binding to
`human-reader` (`view` plus cluster-scoped reads, no Secrets) for each person who holds the
agent capability. A `userValidationRules` entry refuses any `kagent:` username without
`@webgrip.nl`. This changes the security properties above:

* the token's reach at the API server is read-only by construction, whatever the person's own
  role, so a replayed token cannot write;
* the audit names the person and says it was the agent, from the username alone;
* it costs one capability, one binding set in `access-kubernetes`, and a prefix. It reopens
  rfc-mcp-identity M5 only in part: M5 rejected a synthetic identity because it "loses the human
  binding", and `kagent:<email>` keeps it.

### Option 2: token exchange (RFC 8693) at Authentik

**Authentik supports it since 2026.8, which overturns rfc-mcp-identity M4** ("the broker is not
an STS"). The grant is `urn:ietf:params:oauth:grant-type:token-exchange`
([constants.py L13](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/common/oauth/constants.py#L13)),
off by default and enabled per provider. It shipped in PRs #23900 and #24874
([release notes](https://docs.goauthentik.io/releases/2026.8/),
[docs](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/token_exchange/)).
**This cluster runs Authentik 2026.5.2** (HelmRelease `authentik`, read live 2026-09-27) and the
Terraform provider `2026.5.1`, so option 2 needs that upgrade first.

**End to end.** The person's `kagent` token reaches the actor as in option 1. kagent's harness
has an RFC 8693 client built in: `STS_WELL_KNOWN_URI` turns it on, `KAGENT_STS_AUDIENCE` names
the target, and it exchanges once per run and injects the result into every MCP request
([adapter.go L109-142](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/adk/pkg/runner/adapter.go#L109-L142),
[plugin.go L310-405, L430](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/adk/pkg/sts/plugin.go#L310)).
Authentik checks the subject token against its own `AccessToken` table, keeps the human as the
user ([token_exchange.py L79-96](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/providers/oauth2/token/token_exchange.py#L79-L96),
[base_fed.py L113-134](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/providers/oauth2/token/base_fed.py#L113-L134)),
checks the target application's policy bindings, and issues a token for provider `kagent-k8s`.
That provider must list `kagent` in `jwt_federation_providers`
([token_exchange.py L22-56](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/providers/oauth2/token/token_exchange.py#L22-L56)).
The API server trusts only `kagent-k8s`, and the `kagent` token no longer opens it.

* **Verified:** both halves exist in source.
* **Blocking gap, verified:** Authentik identifies the requesting provider by `client_id`, from
  Basic auth or the form, and a confidential client must also send its secret
  ([base.py L76-96](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/providers/oauth2/token/base.py#L76-L96),
  [utils.py L110-135](https://github.com/goauthentik/authentik/blob/version/2026.8.3/authentik/providers/oauth2/utils.py#L110-L135)).
  kagent's client sends neither, and no scope either
  ([client.go L71-111](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/adk/pkg/sts/client.go#L71-L111)).
  The smallest fix is an upstream kagent change that sends a configured `client_id`, with
  `kagent` registered as a public client so the actor holds no secret. Until then option 2
  cannot run without a fork.
* **Unverified:** the `act` claim. With an actor token, Authentik records delegation. kagent
  reads the actor token from the ServiceAccount token file, and actors have none, so kagent
  would call in impersonation mode with no `act`.
* **Audience and scope.** The exchanged token is valid only for `kagent-k8s`, one audience, with
  that provider's own lifetime. With no scope requested it carries no scope claims, so the
  username must come from `sub` (subject mode: email). It combines with 1b's prefix.
* **Replay.** The `kagent` token still passes the same hops, but it no longer opens the API
  server. The exchanged token lives only in the actor and kagent-tools.
* **Lifetime and revocation.** The exchanged token lives as long as `kagent-k8s` says, for
  example ten minutes, and kagent never caches it past the subject token's own expiry
  ([plugin.go L391](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/go/adk/pkg/sts/plugin.go#L391)).
  Every run's exchange checks the subject token against Authentik's database, so revoking the
  person's session stops the next run. Tokens already issued still live out their lifetime.
* **Audit.** The API server shows `oidc:` or `kagent:<email>`. Authentik logs every exchange as
  a login event naming the person and the application.
* **Cost.** Authentik 2026.8 upgrade and Terraform provider bump; two providers; the upstream
  kagent change; a second `jwt` entry. Moderate, and gated on someone else's release.

### Option 3: impersonation by a trusted proxy

**End to end.** kagent-tools calls the API server as its own ServiceAccount with
`Impersonate-User: oidc:<email>`, the email taken from `X-User-Id`.

* **Not supported in kagent-tools 0.3.0 (verified):** it has no `--as` and reads no user
  header, so this needs a fork.
* **The identity it acts on is a header.** In kagent 1.0 that header is unauthenticated from the
  controller onward (option 5). Whoever reaches kagent-tools, or sends a forged `X-User-Id`
  past the gateway, acts as anyone, the owner included.
* **Scope.** Classic `impersonate` on `users` is all or nothing. Constrained impersonation
  (KEP-5284: alpha 1.35, beta and on by default since 1.36;
  [docs](https://kubernetes.io/docs/reference/access-authn-authz/user-impersonation/#constrained-impersonation))
  can limit the ServiceAccount to `impersonate-on:user-info:get` and `list` on named resources.
  That narrows the damage but does not fix the forged header.
* **Replay and lifetime.** No person's token exists to replay. The ServiceAccount's token is
  standing. Revocation means deleting one binding, which takes effect at once.
* **Audit.** The best trail of the three: `user` is the ServiceAccount and `impersonatedUser` is
  the person. `KubernetesImpersonationUsed` fires on every call and needs a standing allow-list.
* **Cost.** A fork of kagent-tools, the `agent-impersonator` ClusterRole the access plane has
  named but never built, and an alert allow-list.

### Option 4: how each fits the access plane

| Piece | Option 1 / 1b | Option 2 | Option 3 |
| --- | --- | --- | --- |
| D10 "agents run under the human's own credential" ([rfc-access-plane](../rfc/rfc-access-plane.md)) | Fits | Fits: a narrowed token for the same human | Conflicts: the agent's credential, not the human's |
| `act-as-human` capability, role `agent`, ClusterRole `agent-impersonator` (`model/capabilities.yaml`, `model/roles.yaml`), projection deferred | Stays unbuilt | Stays unbuilt | Its intended use; it would have to be built |
| rfc-mcp-identity M4 (pass-through; impersonation and exchange rejected) | Same pattern | M4's reason for rejecting exchange no longer holds on 2026.8 | Rejected there |
| rfc-mcp-identity M5 (audit shows `oidc:<email>`, no synthetic identity) | 1 fits; 1b bends it but keeps the email | Fits, or bends it as 1b does | Fits: the impersonated user is `oidc:<email>` |
| `KubernetesImpersonationUsed` ("nothing in this cluster impersonates today") | Quiet | Quiet | Fires; needs an allow-list |
| `access-broker` Terraform (Authentik providers and gates) | One provider | Two providers plus the exchange grant | Nothing |
| `access-kubernetes` Terraform (bindings from the roster) | 1b: one read-only binding set for `kagent:` users | Same as 1b if prefixed | One impersonation binding |
| Provenance rule on User subjects | Satisfied: the module renders the bindings | Satisfied | Not involved |

### Option 5: what kagent 1.0 offers natively

* **No login of its own.** The upstream binary always runs `UnsecureAuthenticator` (see
  Context, step 1). There is no OIDC client, no signature check and no session cookie. The UI
  expects a proxy in front.
* **User-scoped sessions, keyed on an unverified header.** Instances and history belong to their
  creator, and sharing uses share tokens, but the creator is whatever `X-User-Id` said.
* **Runtime identity is unsigned too.** Actors report to the controller with an
  `x-kagent-insecure-runtime-identity` header. Upstream calls these builds "for isolated
  deployments" until Substrate issue #1660 brings signed actor JWTs
  ([a2a-gateway.md L148-162](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/docs/architecture/a2a-gateway.md#L148-L162)).
* **Delegation plumbing exists:** `KAGENT_PROPAGATE_TOKEN` and the RFC 8693 client of option 2.
  kagent expects the identity to arrive from outside and carries it; it does not establish it.

### Recommendation

Build option 1b for the pilot. The person's gateway token passes through, and the API server
maps audience `kagent` to `kagent:<email>`, which holds only a roster-rendered read-only
binding. That keeps the person in the audit and D10's model while capping what any replayed
token can do. Move to option 2 once Authentik runs 2026.8 and kagent's STS client can send a
`client_id`: it keeps 1b's prefix and bindings, and adds a single-audience, short-lived token
plus revocation checked at every run. Do not build option 3. In kagent 1.0 the identity it
would act on is an unverified header, and it would put `KubernetesImpersonationUsed` on a
standing allow-list.

### Spike

Run it on the pilot with the `kagent-k8s` agent before anything else lands.

1. Authentik: provider `kagent` with scopes `openid email profile offline_access`, and an email
   mapping that asserts `email_verified: true`. Obtain a token by hand and decode it.
   **Pass:** `iss` is `…/application/o/kagent/`, `aud` is `kagent`, `email_verified` is `true`.
2. Gateway: the `SecurityPolicy` of (a). **Pass:** a new agent instance is stored with the
   signed-in email as its creator, also when the request carries a forged `X-User-Id`. A request without a cookie
   gets a redirect.
3. API server: add the `kagent` `jwt` entry with the `kagent:` prefix, apply one control plane,
   bind `kagent:<owner email>` to `human-reader`. **Pass:** `kubectl --token <token> auth whoami`
   returns `kagent:<email>`; `auth can-i create pods` is `no`; the Google login still works.
4. Chain: ask the agent a question that needs three or more tool calls. **Pass:** each call
   appears in the audit as `kagent:<email>` with kagent-tools' user agent, and none as a
   ServiceAccount. `KubernetesImpersonationUsed` stays quiet. **Fail:** a 401 or missing bearer
   at kagent-tools, which would mean Substrate's egress drops `Authorization`.
5. Lifetime: set `kagent`'s access-token validity to five minutes for the spike, then start a
   run four minutes into a token. **Pass:** the run's later tool calls fail with 401, and the
   next message succeeds with a refreshed token and no login page. That measures the mid-run
   limit and proves refresh. Set 15 minutes afterwards, the owner's choice.
6. Revocation: delete the person's Authentik session. **Pass:** the next UI request redirects to
   login; tool calls stop within the token's remaining lifetime.

### Questions for the owner, answered 2026-09-27

1. Accept option 1b's read-only ceiling: an agent never writes, even for a person who can?
   **Accepted.** Agents act as `kagent:<email>` with only the read-only `human-reader` binding,
   never with the person's full rights.
2. Accept that a run cannot outlive the token it started with, and choose the access-token
   lifetime for the `kagent` provider (one hour today, shorter is safer)? **Accepted, 15
   minutes.** Refresh goes through `offline_access`, without a login page.
3. Upgrade Authentik to 2026.8 now, so option 2 can follow without waiting for the pilot?
   **Pulled forward:** right after the Kyverno work, once its restart cause is found, so RFC 8693
   token exchange becomes available.
4. Carry the upstream kagent change (STS `client_id`) ourselves, or wait for upstream? **Submit
   an upstream PR and wait; no fork.** Option 1b runs until upstream ships it.
5. Accept the pilot on a kagent 1.0 build that upstream calls "for isolated deployments" until
   Substrate issue #1660 lands, given that the gateway and NetworkPolicy are the only door?
   **Accepted only behind both:** the gateway OIDC gate of (a) and a NetworkPolicy that admits
   only the Envoy gateway to kagent's UI, controller and A2A ports (Confirmation 13).

## More Information

* Unverified until the pilot or GA:
    * the Substrate chart version 1.0 GA pins, and whether it still needs
      `certificates.k8s.io/v1beta1`;
    * each hop of the pass-through chain, live, including whether Substrate's egress path keeps
      `Authorization` on plain HTTP to `kagent-tools` and how a run behaves when its token
      expires (the spike in "Person-bound identity");
    * whether Envoy Gateway's `jwt` filter reads the access token its OIDC filter forwarded;
    * that the gVisor release tarball has the layout Substrate's nightly has, and that atelet
      reads it from Garage with `ATE_STORAGE_BACKEND=s3`;
    * whether the controller works under `rbac.namespaces` with Substrate on;
    * whether the credential provider accepts a namespaced RoleBinding;
    * whether `WorkerPool.spec.template` takes `automountServiceAccountToken`;
    * whether the egress gateway injects on plain in-cluster HTTP to `litellm.ai.svc`.
* The five owner questions at the end of "Person-bound identity" are answered there.
* Follow-up work under epic VIK-1223: VIK-1229 (pilot), VIK-1246 (upstream kagent PR adding
  `client_id` to the token-exchange client) and VIK-1247 (the identity spike).
* Exception ledger, tracked debt from this record (owner prefers none):
    * `pod-security-baseline-privileged` for DaemonSet `ate-system/atelet`. Retire when Substrate
      runs atelet unprivileged, or when the pilot ends.
    * `pod-security-baseline-host-path` for `ate-system/atelet` and the pilot `WorkerPool`
      Deployment in `kagent`. Retire when Substrate drops its host paths, or when the pilot ends.
    * The four audit waivers on the same objects, retired with them.
    * Not a Kyverno exception but the same kind of debt: `--runtime-config` for
      `certificates.k8s.io/v1beta1`, retired by the trigger in (f).
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
* 2026-09-27: owner decisions, round 2. Substrate's privileges accepted for the pilot, with
  `runsc` from a sha256-pinned gVisor release tarball staged in Garage by a Renovate-tracked
  provisioner Job; the two Kyverno exceptions it needs are recorded as tracked debt, (e). The
  beta `certificates.k8s.io/v1beta1` API enabled for the pilot only, with a removal trigger,
  (f). Per-agent LiteLLM and MCP keys accepted without the person, (c) and (d). No fallback
  identity chosen: the owner asked for research, now in "Person-bound identity: the options",
  which recommends pass-through under a `kagent:` username prefix with read-only bindings, then
  token exchange. Corrected: kagent `v1.0.0-alpha4` has no `trusted-proxy` mode in its binary,
  and Authentik supports token exchange since 2026.8 (this cluster runs 2026.5.2). Researched
  against kagent `v1.0.0-alpha4`, kagent-tools `v0.3.0`, Substrate `v0.2.0-beta8`, Authentik
  `version/2026.8.3`, Envoy Gateway `v1.9.1`, Kubernetes `v1.37.1` and gVisor
  `release-20260921.0`. Status stays proposed.
* 2026-09-27: owner decisions, round 3, answering the five questions of "Person-bound
  identity". Option 1b adopted: agents act as `kagent:<email>` with only the read-only
  `human-reader` binding, never the person's full rights, (b). The `kagent` provider's access
  tokens live 15 minutes, a run cannot outlive its token, and refresh uses `offline_access`
  without a login page. The Authentik 2026.8 upgrade is pulled forward to right after the Kyverno
  work, once its restart cause is found, so token exchange (option 2) becomes available. The
  missing `client_id` in kagent's token-exchange client goes upstream as a PR (VIK-1246); no
  fork, and 1b runs until it ships. The spike is VIK-1247. Piloting the alpha build without in-app authentication is accepted only
  behind the gateway OIDC gate plus a NetworkPolicy admitting only the Envoy gateway to kagent's
  UI, controller and A2A ports, now Confirmation 13. Status stays proposed until the GA re-check.
* 2026-09-27 — runtime choice reopened by the [kagent vs Glide RFC](../rfc/rfc-agent-runtime-kagent-vs-glide.md) (c60616fe; owner decisions 03c428c1): the pilot (VIK-1229) waits for Kubernetes 1.37 and the ops assistant is preferred as a Glide reader role on agent-sandbox (installed 12b51c15); the person-bound identity work here is kept as runtime-neutral. Nothing of the kagent deployment has landed (logged in audit 2026-10-04)
* 2026-10-04 — the person-bound identity half split into [ADR-0068](adr-0068-agents-reach-kubernetes-as-agent-email-read-only.md) at the owner's direction, with the prefix generalised to `agent:`; this record keeps the kagent runtime and Substrate decisions
