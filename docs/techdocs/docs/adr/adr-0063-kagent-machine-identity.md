---
status: proposed
date: 2026-09-27
---

# kagent runs as rostered machine principals: a read-only tools account, a namespaced controller, one budgeted key per agent

Technical Story: VIK-1229 (kagent 1.0 pilot). Fires the D10 trigger of
[RFC: The access plane](../rfc/rfc-access-plane.md) for an agent that acts for nobody, the case
[RFC: MCP endpoints carry the caller's identity](../rfc/rfc-mcp-identity.md) left out of scope.

## Context and Problem Statement

The owner has settled three things for the pilot: wait for kagent 1.0 on Kubernetes 1.37, read
the cluster through the bundled kagent-tools in read-only mode, reach Grafana and VictoriaLogs
through the LiteLLM MCP gateway ([ADR-0044](adr-0044-metered-inference-plane-litellm.md)), and
put the UI behind gateway OIDC ([ADR-0060](adr-0060-gateway-oidc-for-apps-without-a-login.md)).
What is not decided is who kagent *is* when it calls the Kubernetes API, LiteLLM and the MCP
gateway. The agent is meant to run without a person present, so the pass-through answer
rfc-mcp-identity gives `k8s-mcp` does not apply.

kagent 1.0 is not the 0.10 architecture the ticket was researched on. At the latest tag,
[`v1.0.0-alpha4`](https://github.com/kagent-dev/kagent/tree/v1.0.0-alpha4) (2026-09-25; no GA
yet), the facts that shape identity are:

| Component | Identity it presents | Default reach | Source |
| --- | --- | --- | --- |
| Controller | ServiceAccount `kagent-controller` | Cluster-wide `get/list/watch` on core `*` (Secrets included) and `create/update/patch/delete` on core `*`, `apps/*`, `batch/*`, `gateway.networking.k8s.io/*`; `rbac.namespaces` turns every ClusterRole into per-namespace Roles | [getter-role](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/helm/kagent/templates/rbac/getter-role.yaml), [writer-role](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/helm/kagent/templates/rbac/writer-role.yaml), [values](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/helm/kagent/values.yaml) |
| kagent-tools 0.3.0 | Its own ServiceAccount | `*/*/*` plus non-resource `*` unless `rbac.readOnly: true`, which renders get/list/watch on pods, pods/log, services, endpoints, configmaps, serviceaccounts, PVCs, namespaces, events, apps, batch, ingresses, networkpolicies, HPAs; Secrets only with `rbac.allowSecrets`; `--read-only` drops write tools including `shell`; `k8s.tokenPassthrough` can forward a caller's bearer instead | [clusterrole](https://github.com/kagent-dev/tools/blob/v0.3.0/helm/kagent-tools/templates/clusterrole.yaml), [cmd/main.go](https://github.com/kagent-dev/tools/blob/v0.3.0/cmd/main.go), [utils/common.go](https://github.com/kagent-dev/tools/blob/v0.3.0/pkg/utils/common.go) |
| Agents | Not pods of their own: a `Harness` × `AgentTemplate` pair compiles to a Substrate Actor in a gVisor sandbox on a shared `WorkerPool` | No Kubernetes RBAC of their own | [architecture README](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/docs/architecture/README.md), [configuration-and-compilation](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/docs/architecture/configuration-and-compilation.md) |
| Substrate 0.2.0-beta5 (`ate-system`) | Pod identities from `PodCertificateRequest` signer `podidentity.podcert.ate.dev/identity`, trust via `ClusterTrustBundle`, actor JWTs from `actor-id-jwt-pool`, SA tokens with audience `api.ate-system.svc` to its API | Credential provider: cluster-wide Secret `get`; ate-controller: cluster-wide Secret `list/watch`; `atelet` DaemonSet is privileged with hostPath `/dev`; the PCR signer runs as the `default` SA | [setup-cluster.sh](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/scripts/setup-cluster/setup-cluster.sh), [kind-config](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/scripts/kind/kind-config.yaml), `helm template` of `oci://ghcr.io/kagent-dev/substrate/helm/substrate:0.2.0-beta5` |
| Credentials to models and MCP | Substrate's egress gateway injects the header from a Kubernetes Secret per destination hostname; the actor only sees a placeholder. Two different credentials for the same hostname and header are rejected, models and MCP servers included | Credential fetch is allowed per namespace by `credentialProvider.namespacePolicies` | [credential-injection](https://github.com/kagent-dev/kagent/blob/v1.0.0-alpha4/docs/architecture/credential-injection.md) |

The upstream dev cluster turns on the `ClusterTrustBundle`, `ClusterTrustBundleProjection` and
`PodCertificateRequest` feature gates and the `certificates.k8s.io/v1beta1` API. The Kubernetes
[feature-gate reference](https://kubernetes.io/docs/reference/command-line-tools-reference/feature-gates/)
lists `PodCertificateRequest` as off by default. On Talos those are API server and kubelet
flags in the machine config.

## Decision Drivers

* Nothing kagent runs may read a Secret outside its own namespace, or write anything outside it.
* Every call must land under a named principal in the audit log and the spend ledger, rostered
  under D10.
* No credential in an actor's environment; revocation must be one edit.
* Reuse the existing patterns: a machine as roster inventory, a LiteLLM key minted in-cluster
  and registered by an idempotent Job, deny-by-default MCP grants.

## Considered Options

* **Own ServiceAccounts, read-only and Secret-free; one LiteLLM key per agent carrying its MCP grant**
* Route Kubernetes reads through `k8s-mcp` on the LiteLLM gateway
* Token pass-through of a person's broker token (`k8s.tokenPassthrough`)
* Impersonation via the access plane's `act-as-human`
* One shared LiteLLM key for all of kagent

## Decision Outcome

Chosen option: **own ServiceAccounts, read-only and Secret-free, with one LiteLLM key per
agent**, because it is the only option that works when nobody is present, and it keeps every
write and every Secret read inside the `kagent` namespace.

**(a) Kubernetes API**

* `kagent-tools`: `rbac.readOnly: true`, `rbac.allowSecrets: false`, `tools.args: [--read-only]`,
  `tools.enabledTools: [k8s]`. Helm is out: it reads release Secrets. `additionalRules` adds
  get/list/watch on `nodes`, `persistentvolumes`, Flux `kustomizations`, `helmreleases` and
  sources, CNPG `clusters`, and Gateway API `httproutes`. Scope is cluster-wide, because an ops
  assistant blind to half the namespaces is not worth piloting. It is a ClusterRole with no
  Secrets, no write verbs and no non-resource URLs.
* Controller: `rbac.namespaces: [kagent]`, so its write role and its Secret access become Roles
  in `kagent` only. `Harness`, `AgentTemplate`, `WorkerPool` and the key Secrets all live there.
* Actors: no Kubernetes identity. They reach the API only through `kagent-tools`. The
  `WorkerPool` template sets `automountServiceAccountToken: false`, if Substrate allows it.
* Substrate: the credential provider's cluster-wide Secret `get` is narrowed by a Kustomize
  patch to a RoleBinding in `kagent`, to match `namespacePolicies: [{atespace: kagent,
  allowedNamespaces: [kagent]}]`.

**(b) LiteLLM**

* One virtual key per `AgentTemplate` (pilot: `kagent-k8s`, `kagent-observability`), in a
  LiteLLM team `kagent` with a team budget above the keys' sum. Each key allows one
  tool-calling model alias and has a hard `max_budget` per 30 days plus an RPM cap. Proposed
  pilot values: USD 5 per key and USD 10 for the team.
* The key is entropy, generated in-cluster and registered by an idempotent Job, the
  `omnigraph-embed-key` pattern ([runbook](../runbooks/omnigraph.md)). It sits in a Secret in
  `kagent` that the Substrate egress gateway injects. It never enters an actor.
* Because injection is keyed on hostname and header, an agent's model calls and its MCP calls
  to LiteLLM must use the same key. One key per agent is therefore also a constraint.

**(c) MCP gateway**

* A new access group `kagent-observability` on the `grafana` and `victorialogs` servers only.
  The existing `observability` group also carries `kubernetes` and `opencost`, and `kubernetes`
  loses its `view` binding at rfc-mcp-identity stage 4. The `kagent-observability` key is
  granted that group. `kagent-k8s` gets no MCP grant and sees an empty tool list under
  `require_key_mcp_access_defined`. No kagent key gets `board` or `memory`.

**Roster (D10).** `people.yaml` gains `kind: machine`, `role: service` entries for
`kagent-controller`, `kagent-tools`, `kagent-agents` (the key holders) and `substrate`. The last
one lists its cluster-wide PCR signing and privileged node agent in its `purpose`, since it
holds more than the other three. None holds a capability. None acts for a person, so
`act-as-human` stays unbuilt.

### Consequences

* Good, because audit and spend attribution are exact: `system:serviceaccount:kagent:*` in the
  audit dashboard, and one ledger row per agent key.
* Good, because the credential path has one revocation point per agent (delete the key), and
  the team budget at zero is the kill switch ADR-0044 describes.
* Bad, because cluster-wide `pods/log` and `configmaps` reads remain. RBAC cannot subtract
  namespaces, and a log line or ConfigMap that holds a secret is readable. That is accepted
  for the pilot and listed in the access matrix.
* Bad, because 1.0 brings Substrate: a privileged DaemonSet, a second Postgres, bundled S3
  (rustfs) for snapshots, a CA and JWT pools minted imperatively by `kubectl-ate`, and an alpha
  feature gate on the API server. The identity decision cannot remove that. It moves the pilot's
  install cost well above what VIK-1229 assumed.
* Bad, because the agents are not attributable to a person. Anything an agent says in the UI
  comes from `kagent-agents`, whoever asked.

### Confirmation

1. `kubectl auth can-i --list --as=system:serviceaccount:kagent:kagent-tools` shows no `secrets`,
   no verb other than get/list/watch, and no `*`.
2. `kubectl auth can-i get secrets -n observability --as=system:serviceaccount:kagent:kagent-controller`
   is `no`. The same check for the Substrate credential provider is `no` outside `kagent`.
3. The tools server's tool list has no `shell` and no `helm_*` entries.
4. A `kagent-k8s` call to the MCP gateway lists zero tools. `kagent-observability` lists only
   `grafana_*` and `victorialogs_*`.
5. Exhausting a key's budget returns a LiteLLM budget error in the agent's task, and both keys
   show as separate rows in the spend ledger.
6. `grep` over a running actor's environment finds no LiteLLM key.
7. The access matrix lists the four machine principals.

## Pros and Cons of the Options

### Own ServiceAccounts, read-only, one key per agent

* Good, because it works unattended and matches the roster model.
* Bad, because it is a standing, non-person read identity, the property rfc-mcp-identity
  removes from `k8s-mcp`.

### `k8s-mcp` through the LiteLLM gateway

* Good, because no new Kubernetes principal is needed.
* Bad, because after rfc-mcp-identity stage 4, `k8s-mcp` only passes a person's token through,
  and has no identity of its own to lend an unattended agent.

### Token pass-through of a person's broker token

* Good, because the audit would show the person.
* Bad, because there is no person on an alert-triggered run. Unverified: whether kagent's UI
  forwards the gateway-OIDC token to tools at all. Revisit if it does, for interactive use only.

### Impersonation (`act-as-human`)

* Bad, because the agent acts for nobody. Building impersonation would also give
  `KubernetesImpersonationUsed` a standing allow-list entry.

### One shared LiteLLM key

* Good, because there is one Secret, and the hostname rule is satisfied trivially.
* Bad, because the ledger can no longer tell the agents apart, and the MCP grant becomes the
  union of every agent's needs.

## More Information

* Unverified until the pilot or GA:
    * the Substrate chart version 1.0 GA pins;
    * whether `PodCertificateRequest` is still alpha on 1.37 and needs `certificates.k8s.io/v1beta1`;
    * whether the controller works under `rbac.namespaces` with Substrate on;
    * whether the credential provider accepts a namespaced RoleBinding;
    * whether `WorkerPool.spec.template` takes `automountServiceAccountToken`;
    * whether the egress gateway injects on plain in-cluster HTTP to `litellm.ai.svc`;
    * whether gVisor loads on Talos (Substrate fetches a nightly `runsc` build from `gs://gvisor`,
      and Talos also ships a gVisor extension).
* Relates to [ADR-0044](adr-0044-metered-inference-plane-litellm.md),
  [ADR-0055](adr-0055-one-secrets-model-six-levels.md) (keys and CA pools are generated
  in-cluster), [ADR-0058](adr-0058-access-plane-one-module-one-model.md) and
  [ADR-0060](adr-0060-gateway-oidc-for-apps-without-a-login.md).
* 2026-09-27: proposed. Researched against kagent `v1.0.0-alpha4`, kagent-tools `v0.3.0` and
  Substrate `0.2.0-beta5`. Re-check the table above against the 1.0 GA tag before accepting.
