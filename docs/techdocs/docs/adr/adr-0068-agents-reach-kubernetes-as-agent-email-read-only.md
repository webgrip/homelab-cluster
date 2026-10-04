---
status: proposed
date: 2026-10-04
---

# Agents reach the Kubernetes API on the person's own token, as `agent:<email>`, read-only

Technical Story: split out of [ADR-0063](adr-0063-kagent-machine-identity.md) on 2026-10-04, after
[RFC: agent runtime, kagent vs Glide](../rfc/rfc-agent-runtime-kagent-vs-glide.md) reopened the
runtime choice while keeping the identity work as runtime-neutral.

## Context and Problem Statement

An agent that reads the cluster for a person needs an identity at the API server. ADR-0063 worked
this out for kagent and the owner answered its questions on 2026-09-27. The identity answer does not
depend on kagent: any agent runtime behind the gateway's OIDC gate receives the person's access
token and can pass it on. The runtime decision is now open again, so the identity decision gets its
own record. The full option analysis, with source references at the researched tags, stays in
ADR-0063 under "Person-bound identity: the options".

"Person-bound" means: the API server authenticates the person, not a component; the token is only
good at the API server; it dies within minutes of the person leaving; revoking the person stops the
agent; and the audit log names the person and shows that an agent made the call.

## Considered Options

* Pass-through of the person's gateway token, mapped to its own username prefix (option 1b)
* Pass-through under the person's normal `oidc:` username (option 1)
* Token exchange (RFC 8693) at Authentik (option 2)
* Impersonation by a trusted proxy (option 3)

## Decision Outcome

Chosen option: "Pass-through of the person's gateway token, mapped to its own username prefix",
because it keeps the person in the audit and the access plane's "agents run under the human's own
credential" model, while capping what any replayed token can do at read-only.

* The API server trusts the agent provider's audience with the username prefix `agent:`, so it sees
  `agent:<email>`, a user distinct from the person's own `oidc:<email>`.
* The access-plane module renders one read-only binding to `human-reader` (`view` plus
  cluster-scoped reads, no Secrets) for each person who holds the agent capability. An agent never
  writes, even for a person who can.
* A `userValidationRules` entry refuses any `agent:` username outside the Workspace domain.
* The provider's access tokens live 15 minutes and refresh through `offline_access` without a login
  page. A run cannot outlive the token it started with.
* Move to token exchange (option 2) once Authentik runs 2026.8 and the agent runtime's STS client can
  send a `client_id`; it keeps this prefix and these bindings.

### Consequences

* Good, because the audit names the person and marks the call as an agent's from the username alone.
* Good, because a replayed token cannot write, whatever the person's own role.
* Bad, because the bearer token passes every hop between the gateway and the API server, and any of
  them can replay it read-only until it expires.
* Bad, because revoking a session does not stop tokens already issued; option 2 narrows that.

### Confirmation

* `kubectl --token <agent token> auth whoami` returns `agent:<email>`, and
  `kubectl --token <agent token> auth can-i create pods` returns `no`.
* A multi-step agent run appears in the audit log as `agent:<email>` on every call, with
  `KubernetesImpersonationUsed` quiet.

## Pros and Cons of the Options

### Pass-through under `oidc:<email>`

* Good, because it is the smallest change.
* Bad, because the token carries the person's full RBAC, `k8s-admin` for the owner.

### Token exchange at Authentik

* Good, because the exchanged token has one audience, a short life, and a revocation check per run.
* Bad, because it needs Authentik 2026.8 and an upstream `client_id` change in the runtime's STS
  client.

### Impersonation by a trusted proxy

* Bad, because the identity it acts on is an unverified header, and it puts
  `KubernetesImpersonationUsed` on a standing allow-list.

## More Information

* Split from [ADR-0063](adr-0063-kagent-machine-identity.md); the owner's answers of 2026-09-27
  (option 1b, 15-minute tokens, Authentik 2026.8 pulled forward, upstream PR VIK-1246, spike
  VIK-1247) carry over unchanged.
* The prefix is `agent:` rather than ADR-0063's `kagent:`, as the runtime RFC proposed, so the
  binding does not name a runtime.
* 2026-10-04 — proposed, split out at the owner's direction in the ADR audit. The spike in ADR-0063
  has not run.
