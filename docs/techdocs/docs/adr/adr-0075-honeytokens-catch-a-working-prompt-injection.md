---
status: accepted
date: 2026-10-18
---

# Decoy credentials that grant nothing catch a working prompt injection or an escape within minutes

Technical Story: the agent hardening pass of 2026-10-18 ("fix it all, ADRs and RFCs, then
implement"), under [RFC: Security hardening](../rfc/rfc-security-hardening.md) and
[RFC: Agent observability](../rfc/rfc-agent-observability.md). Decided by Ryan Grippeling on
2026-10-18.

## Context and Problem Statement

Ploeg and Unfold run agents that read untrusted text: Work Items, repository files, fetched pages,
pull request comments. A prompt injection that works turns the agent into the attacker's hands
inside the cluster. Nothing here notices that today. The other hardening records narrow what an
agent can reach: egress (ADR-0071), runtime detection (ADR-0072), admission (ADR-0073, ADR-0074),
API audit (ADR-0076). None of them tells us that an agent *tried* to do something it was never
asked to do while every individual call it made was allowed.

A honeytoken (a decoy credential) answers that question. It is planted where a hijacked agent, a
curious explorer or an escaped workload would look, it grants nothing, and any use of it is
evidence by construction: no legitimate process holds it. The question is where to plant decoys,
what they look like, how they are created without a secret in Git, and how their use reaches a
person within minutes.

## Decision Drivers

* A decoy must grant nothing real, even when the alert is missed.
* Every use must leave a log line we have already seen in this cluster, so the alert query matches
  real lines rather than a guess.
* Each placement answers a different question, so the alert must say which placement leaked.
* No secret value in Git; decoys come from the same ESO, OpenBao and provisioner-Job patterns as
  real credentials.
* The detector must say when it is blind, or a quiet alert means nothing.

## Considered Options

* Decoys unregistered in LiteLLM and restricted Forgejo accounts, one per placement, alerted from
  VictoriaLogs through a logs-backed vmalert
* Decoys registered in LiteLLM with a zero budget and blocked models
* A hosted canary-token service
* No decoys; rely on egress, runtime and audit controls alone

## Decision Outcome

Chosen option: "Decoys unregistered in LiteLLM and restricted Forgejo accounts, one per placement,
alerted from VictoriaLogs through a logs-backed vmalert", because it is the only option where the
decoy grants nothing even if every alert fails, every use of it is logged by software already
running here, and nothing leaves the cluster.

### The decoys

| Decoy | What it is | Why it grants nothing |
| --- | --- | --- |
| LiteLLM key | `sk-` plus 32 random characters from `password-generator-32`, **never registered** in LiteLLM | No row in LiteLLM's key table, so every route answers 401 before any model or MCP tool is reached |
| Forgejo token | A real token, scopes `read:user` and `read:repository`, on a canary account created by the provisioner Job | The account is `restricted`, `private`, owns no repository, may create none and is in no team or organisation. A restricted Forgejo account sees no repository, public ones included (checked on Forgejo 15.0.9) |

### The placements

| Placement | Where | What a use means | Forgejo account |
| --- | --- | --- | --- |
| workspace | Secret `workspace-deploy-credentials` in `unfold-workspaces`, given to the agent container as `FORGEJO_ADMIN_TOKEN` and `LITELLM_ADMIN_KEY` through Unfold's `workspaceAgentSecrets` | An agent used credentials from its environment that no task asked for: the signature of a working prompt injection | `deploy-automation` |
| escape | Secret `forgejo-admin-break-glass` in `ploeg`, holding `FORGEJO_ADMIN_TOKEN` and `LITELLM_MASTER_KEY`; no workload mounts it | Something read Secrets in the `ploeg` namespace, which no agent identity may do (ADR-0068 grants agents `view`, without Secrets) | `breakglass-admin` |
| repository | A private repository `webgrip/ops-credentials` whose `.env` holds the decoys, readable by every agent team | An agent read a repository outside its task and acted on what it found | `backup-operator` |

The workspace placement is the prompt-injection tripwire: an agent legitimately sees its own
environment, so only an instruction to *use* these names trips it. The escape placement is the
escape tripwire: reaching it at all already means a boundary failed, so reading it alerts too,
from the API audit log. The repository placement is the exploration tripwire.

### Detection

* **LiteLLM.** An unknown key is logged by `auth_exception_handler.py` as
  `Authentication Error, Invalid proxy server token passed. key=<sha256 of the key>, not found in
  db. ... Requester IP Address:<pod IP>` (LiteLLM 1.105.1, `KeyNotFoundError`). The alert matches
  the SHA-256 of each decoy. The fingerprints come from an ExternalSecret that hashes the decoys
  with `sha256sum`, and reach the rule through Flux `postBuild.substituteFrom`, so Git holds
  neither the key nor its hash.
* **Forgejo.** Forgejo's router log does not name the caller, so Forgejo's access log is switched
  on (`[log] logger.access.MODE = console`). Its default template writes
  `<ip> - <user> [<date>] "<method> <path> HTTP/1.1" <status> ...` for every request, token,
  Bearer, basic and git-over-HTTP alike. The alert matches the three canary account names in
  the user position. The provisioner authenticates as the site admin, so minting never trips it.
  The access log adds about 260,000 lines a day to the roughly 9 million VictoriaLogs takes in
  now, about 3%.
* **Kubernetes API.** A `get`, `update`, `patch` or `delete` of `ploeg/forgejo-admin-break-glass`
  by anyone other than External Secrets alerts from the audit store
  (the `vmalert-audit` that ADR-0076 governs).
* **Delivery.** Log rules run in a new `vmalert-logs` against the application VictoriaLogs, once a
  minute over a five-minute window, `severity: critical`, so Alertmanager routes them to the
  `alerts-critical` ntfy topic like every other critical alert. The main `vmalert` now skips
  every rule that carries a `rules` label (the same selector the Tetragon change, ADR-0072, sets);
  until now it also loaded the audit store's rules and failed every evaluation against
  VictoriaMetrics. `vmalert-logs` selects `rules: logs` only, so it does not overlap ADR-0072's
  `vmalert-runtime` (`rules: runtime-detection`) on the same VictoriaLogs.
* **Blindness.** `HoneytokenForgejoDetectorBlind` and `HoneytokenLiteLLMDetectorBlind` warn when
  either log source has gone quiet for thirty minutes.

### Consequences

* Good, because a decoy that is used while every alert is down still grants nothing.
* Good, because each alert names the placement and the caller's pod IP, which leads to the Run.
* Good, because the queries were run against real LiteLLM and audit lines in this cluster, and the
  Forgejo query against real Forgejo 15.0.9 access-log lines, through vmalert v1.147.0.
* Bad, because an honest agent that decides to use `FORGEJO_ADMIN_TOKEN` for a Forgejo task trips
  the workspace alert. That is still worth a look: no task gives it that token.
* Bad, because a decoy listed with `kubectl get secrets -o yaml` is not caught at read time; the
  audit rule sees `get` by name, not the contents of a `list`. Its use still alerts.
* Bad, because the Forgejo access log is a second log stream that now matters; the blind alert is
  what keeps it honest.
* Bad, because LiteLLM's log format is an upstream detail; a changed message silences the LiteLLM
  rule without making the blind alert fire. Re-run the post-merge test after each LiteLLM upgrade.
* Bad, because the workspace Secret becomes a dependency of every Unfold workspace; the `unfold`
  Kustomization waits for it, so a broken decoy pipeline stalls Unfold upgrades rather than
  breaking running sessions.

### Confirmation

* `HoneytokenForgejoTokenUsed` and `HoneytokenLiteLLMKeyUsed` fire within two minutes of using each
  decoy once from a throwaway pod, and `HoneytokenEscapeSecretRead` fires on
  `kubectl -n ploeg get secret forgejo-admin-break-glass`; the steps are in the
  [runbook](../runbooks/honeytokens.md#post-merge-test).
* Both blind alerts stay quiet after the merge.
* `vmalert` logs no `kubernetes.audit` evaluation errors.

## Pros and Cons of the Options

### Decoys registered in LiteLLM with a zero budget and blocked models

* Good, because LiteLLM's "Budget has been exceeded! Key=<alias>" line names the key.
* Bad, because the budget check runs only on model routes; `/key/info` and other management
  routes answer the key without a log line.
* Bad, because the key is a real row: a later change to its models, budget or MCP groups turns
  the decoy into a working credential.

### A hosted canary-token service

* Good, because it is free and needs no alert plumbing.
* Bad, because the decoy then calls out of the cluster to a third party, and the alert depends on
  a service outside our control.

### No decoys

* Good, because there is nothing to maintain.
* Bad, because an allowed-but-unasked action stays invisible.

## More Information

* Implementation: `kubernetes/apps/security/honeytokens/` (decoys, placements, alert rules),
  `kubernetes/apps/observability/victoria-metrics/app/vmalert-logs.yaml`, the Forgejo `log`
  section and Unfold's `workspaceAgentSecrets`.
* Operating it: [runbooks/honeytokens.md](../runbooks/honeytokens.md).
* No decoy is a file today, so none joins Tetragon's `agent-credential-reads` path list
  (ADR-0072). A decoy planted as a file in an agent pod, such as a clone of
  `webgrip/ops-credentials`, should join that list with its own `critical` rule.
* Ploeg workers do not receive the workspace decoy: Ploeg's chart has no agent-only Secret hook.
  Adding one belongs upstream in Ploeg.
* 2026-10-18 — accepted. The provisioner mints the `backup-operator` decoy and the LiteLLM
  repository decoy, but writing them into `webgrip/ops-credentials` was held back: the agent
  session that built this was not permitted to commit credential values into a repository. The
  runbook gives the owner the steps to plant them.
