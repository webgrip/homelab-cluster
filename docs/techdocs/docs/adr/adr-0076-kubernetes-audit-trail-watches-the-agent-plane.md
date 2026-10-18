---
status: accepted
date: 2026-10-18
---

# The Kubernetes audit trail watches the agent plane: control planes only, more detail where agents run, four more alerts

Technical Story: [RFC: Access plane](../rfc/rfc-access-plane.md) (D7 made the admin certificate
evidential through an audit policy, Alloy and VictoriaLogs) and
[RFC: Security hardening](../rfc/rfc-security-hardening.md). Decided by Ryan Grippeling on
2026-10-18 ("fix it all") as part of hardening the agent plane next to
ADR-0071 to ADR-0075.

## Context and Problem Statement

Ploeg runs agents in `ploeg`, and Unfold runs their workspaces in `unfold-workspaces` and its
verifier in `unfold-verifier`. Those three namespaces hold provider keys, forge tokens and
database passwords, and an agent that escapes its sandbox reaches the Kubernetes API first. The
question is whether the API server's audit trail would show it, and whether anyone would hear.

What existed on 2026-10-18, read from the repository and the live cluster:

* The Talos controller patch already sets an audit policy. Exec, attach, port-forward and proxies
  are recorded with their bodies; RBAC, CSR and webhook writes too; Secrets and everything else at
  Metadata. All `watch` calls, leases, events and endpoints are dropped.
* Talos writes the log to `/var/log/audit/kube/kube-apiserver.log` on each control plane.
  `alloy-agent` ships it to its own `victorialogs-audit` instance, and `vmalert-audit` evaluates
  five alerts on it: break-glass certificate, RBAC changed outside GitOps, anonymous allowed,
  Secret read burst by a person, impersonation.
* Gaps found:
    * No alert covered exec into the agent plane (2,196 exec and 371 port-forward calls by
      `admin` into `ploeg` in 14 days), Secret reads there by unexpected identities (354 by
      `admin`), or network-policy changes outside Flux (7 by `admin` on CiliumNetworkPolicies).
    * Every `alloy-agent` pod tailed the audit path, including on workers. `fringe-workstation`, a
      worker that runs CI, contributed 10,888 lines a day from a nested cluster on its pod
      network. Anything on a worker that can write that host path can plant or flood audit lines.
    * The main `vmalert`, which selects every VMRule, also loaded the audit group and failed every
      evaluation against VictoriaMetrics with HTTP 400.
    * The RBAC alert's allow-list missed three Kubernetes and CNPG controllers that write RBAC
      every day, so it fired on noise.
    * Ephemeral debug containers (`pods/ephemeralcontainers`), a shell by another name, were only
      at Metadata.
    * Secret `watch` was dropped everywhere.
    * Retention: the volume caps at 9GiB and held 6.9GB after 30 days. The real horizon was about
      40 days, not the configured 365. 40% of the volume was Kyverno and Trivy report churn,
      Longhorn CRD updates and access reviews from metrics-server.
    * `KubernetesBreakGlassCertificateUsed` has fired since 2026-10-17 15:10 UTC, because agent
      sessions on the workstation use the admin certificate. ADR-0068 (agents as `agent:<email>`)
      is still proposed.

## Decision Drivers

* An agent's or attacker's first moves in the agent plane (a shell, a Secret read, an egress
  policy edit) must page a person within fifteen minutes.
* The trail must only contain lines the API server wrote.
* More detail costs disk; spend it where agents run and take it back from report churn.
* No new component, and nothing that needs an apiserver restart beyond one rolling Talos apply.

## Considered Options

* Extend the existing policy, pipeline and rule group (chosen)
* Ship the audit stream through a webhook backend straight to Alloy instead of a file
* Detect the same actions at runtime with Tetragon instead of the API audit

## Decision Outcome

Chosen option: "Extend the existing policy, pipeline and rule group", because every part already
runs and works, and each gap closes with a small change in the file that owns it.

* **Policy** (`talos/patches/controller/cluster.yaml`), first match wins:
    * add `pods/ephemeralcontainers` to the RequestResponse rule with exec and attach;
    * record Secret `watch` at Metadata in the three agent namespaces, ahead of the rule that
      drops every `watch`;
    * record writes to pods, service accounts, Jobs, NetworkPolicies and CiliumNetworkPolicies in
      the agent namespaces at Request level, and writes to CiliumClusterwideNetworkPolicies
      everywhere;
    * drop report churn from the Kyverno and Trivy controllers, Longhorn's own CRD updates,
      `events.k8s.io` events, and access reviews by metrics-server and Kyverno. The drops name the
      controller's service account, so a person writing the same objects is still recorded.
* **Pipeline** (`alloy-agent`): tail the audit file only on nodes labelled
  `node-role.kubernetes.io/control-plane`, found through the node's own labels rather than a list
  of names.
* **Evaluation**: the main `vmalert` excludes VMRules labelled `rules: audit`; only `vmalert-audit`
  evaluates them.
* **Alerts**, in the existing `kubernetes-audit` group, routed by severity through the existing
  Alertmanager to ntfy:
    * `KubernetesExecIntoAgentNamespace` (warning): exec, attach, port-forward or an ephemeral
      container in the agent plane by anyone but CloudNativePG and its DR check;
    * `KubernetesSecretReadInAgentNamespace` (critical): a Secret get, list or watch there by an
      identity outside the allow-list of readers observed over 14 days;
    * `KubernetesNetworkPolicyChangedOutsideGitOps` (critical): a write to any network policy kind
      by anything but Flux, Kyverno's generator, the namespace and garbage controllers, or Unfold
      inside `unfold-workspaces`;
    * `KubernetesAuditTrailIncomplete` (warning): lines from fewer than three control planes for
      thirty minutes.
* `KubernetesRBACChangedOutsideGitOps` adds the garbage collector, the namespace controller and
  the CNPG barman plugin to its allow-list.

### Consequences

* Good, because a shell, a Secret read or a policy edit in the agent plane now pages, with the
  request body on record for the writes that matter.
* Good, because a worker can no longer write into the trail the alerts read.
* Good, because the noise cut buys back roughly two-fifths of the volume, which pays for the added
  detail and stretches retention towards two months.
* Bad, because until agent sessions stop using the admin certificate (ADR-0068), the exec and
  Secret alerts fire alongside the break-glass alert whenever an agent touches the agent plane.
  That is the intended pressure, and it is noisy.
* Bad, because the allow-lists are hand-kept: a new controller that reads Secrets or writes policy
  in the agent plane fires until a pull request adds it.
* Bad, because the policy change needs a Talos apply on each control plane, which restarts its
  API server; the owner runs it one node at a time.
* Bad, because the trail still lives inside the cluster it audits. Someone with cluster-admin can
  delete the `victorialogs-audit` volume. Off-cluster copies are a separate decision.

### Confirmation

* `_time:15m | stats by (node) count()` on `victorialogs-audit` lists `soyo-1`, `soyo-2` and
  `soyo-3` and no worker.
* The main `vmalert` no longer lists the `kubernetes.audit` group; `vmalert-audit` lists nine
  rules, all healthy.
* Each test command in the runbook's "Prove an alert fires" section makes its alert fire within
  ten minutes.
* After a week, the audit volume per day is lower than the 1.18 million events of 2026-10-17.

## Pros and Cons of the Options

### Webhook backend straight to Alloy

* Good, because no file on the node, so no host path to plant lines in.
* Bad, because Talos would need a webhook kubeconfig file on each control plane, placed through
  boot-only `machine.files`, and an unreachable receiver blocks or drops events by batch policy.
* Bad, because it replaces a working pipeline to fix what a node-label filter fixes.

### Runtime detection with Tetragon

* Good, because it sees what happens inside the container after the shell opens.
* Bad, because it does not see who asked the API server; the audit names the identity. The two
  complement each other, and Tetragon is ADR-0072's decision.

## More Information

* Runbook: [Kubernetes audit trail](../runbooks/kubernetes-audit-trail.md).
* Related: [ADR-0059](adr-0059-per-user-kubernetes-identity-via-google.md) (people reach the API as
  `oidc:<email>`), [ADR-0062](adr-0062-talos-configs-from-plain-talosctl.md) (how the controller
  patch reaches the nodes), [ADR-0068](adr-0068-agents-reach-kubernetes-as-agent-email-read-only.md)
  (agents as `agent:<email>`; its rollout quiets the admin-certificate firings).
* The source of the nested-cluster lines on `fringe-workstation` was not identified; the
  control-plane filter makes it irrelevant to the trail.
* 2026-10-18 — accepted.
