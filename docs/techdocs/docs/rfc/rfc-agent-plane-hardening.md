# RFC: Agent plane hardening

> Status: **Accepted** 2026-10-18 · Owner: Ryan · Decision records: ADR-0070 to ADR-0077 below.
> Builds on the [security hardening](rfc-security-hardening.md) programme and the
> [Kyverno audit→enforce](rfc-kyverno-audit-enforce-hardening.md) and
> [runtime detection](rfc-runtime-detection-response.md) RFCs.

## Why

Ploeg and Unfold run code that AI agents write or fetch, against repositories nobody on the estate
controls. On 2026-10-18 the owner asked whether the homelab ran them on its strongest settings. A
read-only review of the live cluster said no:

| Finding | Where |
| --- | --- |
| `ploeg` enforced only `baseline`; the harness container ran as the image's user, root for the shared agent image | Ploeg chart, namespace `ploeg` |
| Unfold workspaces shared the node's kernel; Kata was only reachable through an unqualified provisioner | Unfold, `unfold-workspaces` |
| A workspace could reach the whole `network` namespace on every port, so every hostname behind the gateways | Unfold workspace egress |
| A Ploeg Run could reach every pod in `ploeg`: its database, Unfold, ploeg-mcp | `ploeg-allow-egress` |
| Image signatures and CVE verdicts were checked in Audit only; Ploeg's images were not signed at all | Kyverno, Ploeg release CI |
| Exec, Secret-read, env-secret and seccomp policies only reported | Kyverno |
| Nothing watched what agent processes did at run time | Falco and Tetragon off since 2026-06-19 |
| The API audit log raised no alert for the agent namespaces | vmalert-audit |
| Admin sign-ins accepted any second factor and lasted until the browser closed | Google, Authentik, OpenBao |
| A stored, signed-out personal Claude login sat on a volume in `ploeg` | team pewter, retired by ADR-0088 |

## Decisions

| ADR | Decision |
| --- | --- |
| [0070](../adr/adr-0070-agent-code-runs-restricted-and-in-its-own-kernel.md) | `ploeg` enforces `restricted`; Unfold workspaces run under Kata |
| [0071](../adr/adr-0071-agent-egress-reaches-only-what-it-needs.md) | Agent egress reaches only DNS, the model gateway, the forge and its own control plane |
| [0072](../adr/adr-0072-tetragon-watches-agent-pods.md) | Tetragon alone watches agent pods, inside a reserved memory budget |
| [0073](../adr/adr-0073-image-admission-signatures-enforced.md) | Unsigned first-party images are refused at admission |
| [0074](../adr/adr-0074-audit-to-deny-exec-secrets-seccomp-tokens.md) | Exec and Secret-read grants, seccomp and token opt-outs are denied |
| [0076](../adr/adr-0076-kubernetes-audit-trail-watches-the-agent-plane.md) | The API audit trail watches the agent plane and pages |
| [0077](../adr/adr-0077-admins-prove-a-security-key-at-google-and-sessions-end-in-twelve-hours.md) | Admins prove a security key at Google; sessions end in twelve hours |
| [0088](../adr/adr-0088-no-stored-personal-claude-logins-in-the-cluster.md) | The cluster holds no personal Claude login: team pewter and its runner are retired |

Upstream halves: Ploeg ADR-0120 (restricted harness container), ADR-0126 (a recurring attack drill
against every harness) and signed Ploeg releases; Unfold's pod `runtimeClassName` and git URL
rewrites; the `cosign-sign-attest` action attesting the CVE-budget verdict.

The attack drill found one real weakness on its first run: OpenCode loaded a repository's own
plugins and MCP servers before any prompt, with the harness's environment. Ploeg 0.2.0-rc.40 starts
OpenCode with project configuration disabled.

## Still open

* **CVE budget at admission.** Stays Audit until the conditions in ADR-0073 hold: images meet their
  budgets, the largest SBOM fits Kyverno's context limit, and the sweep covers the verdict.
* **Ploeg image signatures at admission.** Promote `image-verify-ploeg-hq-audit` once a signed Ploeg
  release is the deployed one.
* **Audit policy on the control planes.** The owner applies the Talos change (ADR-0076).
* **Agent identity.** Agents still reach the API as the break-glass `admin`, so the new exec and
  Secret alerts are noisy until ADR-0068 lands.
* **Runtime detection stage two.** After seven days of explained info alerts, raise credential reads
  to critical (ADR-0072).

## History

* 2026-10-18 — review, owner instruction "fix it all, ADRs and RFCs, then implement".
* 2026-10-19 — ADR-0070 to ADR-0078 merged or in review; this RFC records the programme.
* 2026-10-24 — ADR-0070 lands. ADR-0078 went to the release recipe, so the stored-login record
  waits for its own number.
