# RFC: Policy estate gap analysis — adopt upstream, keep only what is ours

> Status: **Proposed** · Date: 2026-08-06 · Supersedes the wave plan in [CEL migration](rfc-kyverno-cel-migration.md)

> **TL;DR.** Of 79 validate rules across 25 policies, roughly **half are hand-written
> reimplementations of published standards** — Pod Security Standards and Kyverno's own
> best-practices catalogue — and they implement those standards **incompletely**. Our
> "PSS Baseline" policy covers **4 of ~13** Baseline controls. Meanwhile upstream ships four
> best-practice policies we simply do not have. The recommendation is to stop maintaining
> the standards-derived half and adopt upstream for it, keeping hand-written policy only
> where it encodes a decision no catalogue can know: Harbor-only registries, CNPG backup
> tiers, Longhorn replica ceilings, the OpenBao Transit trust anchor, and the dual-gateway
> topology. Separately, the CEL migration blocker is **solved** — autogen is unnecessary.

## The blocker is solved: match controllers explicitly

[The CEL migration RFC](rfc-kyverno-cel-migration.md) halted because `ValidatingPolicy`
autogen produces nothing, so a migrated Pod policy stops evaluating Deployments and
CronJobs. The fix is to not use autogen at all — list the controller kinds in
`matchConstraints` and resolve the pod spec in a variable:

```yaml
matchConstraints:
  resourceRules:
    - apiGroups: [""];     apiVersions: ["v1"]; operations: [CREATE, UPDATE]; resources: [pods]
    - apiGroups: ["apps"];  apiVersions: ["v1"]; operations: [CREATE, UPDATE]; resources: [deployments, statefulsets, daemonsets]
    - apiGroups: ["batch"]; apiVersions: ["v1"]; operations: [CREATE, UPDATE]; resources: [jobs, cronjobs]
variables:
  - name: podSpec
    expression: >-
      object.kind == 'Pod' ? object.spec :
      (object.kind == 'CronJob' ? object.spec.jobTemplate.spec.template.spec : object.spec.template.spec)
  - name: allContainers
    expression: >-
      variables.podSpec.containers +
      (variables.podSpec.?initContainers.orValue([])) +
      (variables.podSpec.?ephemeralContainers.orValue([]))
```

Verified 2026-08-06: a Deployment and a CronJob both carrying a tagless image → **fail: 2**
(autogen version: 0). Compliant Pod + Deployment-with-initContainers + CronJob → **pass: 3**,
bad Pod → **fail: 1**. Against the real 57-controller corpus → **57 pass, 0 fail**, matching
the legacy policy.

This is *better* than autogen: explicit, readable, testable, and it covers Job and CronJob
without the separate `autogen-cronjob-` mechanism. Note also the optional-chaining idiom
(`.?field.orValue(default)`) upstream uses — it replaces the `has()` guard pile-up.

Kubernetes [#129939](https://github.com/kubernetes/kubernetes/issues/129939) tracks making
this ergonomic upstream; until then, explicit matching is the pattern.

## What upstream actually is

| Source | What it is | Fit |
| --- | --- | --- |
| [kyverno/policies](https://github.com/kyverno/policies) | ~40 domains; `-cel` variants for pod-security, best-practices, flux | **Primary.** Note the `-cel` dirs are `ClusterPolicy` + `validate.cel`, **not** `ValidatingPolicy` — upstream has not migrated its own catalogue, which corroborates that `ValidatingPolicy` is younger than the deprecation timetable implies |
| [kubescape/cel-admission-library](https://github.com/kubescape/cel-admission-library) | Kubescape controls re-implemented as native VAPs | Secondary — engine-independent, no Kyverno dependency |
| [vap-library](https://github.com/vap-library/vap-library) | 12 community VAPs + a test framework | Reference for idiom, too small to adopt wholesale |
| [Kubescape](https://kubescape.io/) | 260+ controls across NSA-CISA, MITRE ATT&CK, CIS, SOC2, PCI-DSS | **Assurance layer, not admission** — see below |

Our cluster runs **Kubernetes v1.36.1**, so `ValidatingAdmissionPolicy` *and*
`MutatingAdmissionPolicy` are both GA and available as an engine option.

## Gap analysis — the 25 policies

**REPLACE** — a hand-written reimplementation of a published standard, incompletely done:

| Ours | Upstream | Note |
| --- | --- | --- |
| `pod-security-baseline-enforce` (4 rules) | `pod-security-cel/baseline` | We cover host-namespaces, hostPath, hostPorts, privileged. Baseline also covers capabilities, AppArmor, SELinux, procMount, seccomp, sysctls, hostProcess — **we implement 4 of ~13** |
| `workload-hardening-audit` (3 of 4 rules) | `pod-security-cel/restricted` | privilege-escalation, run-as-non-root, seccomp are verbatim Restricted controls |
| `workload-advanced-hardening-audit` (9 of 11) | `pod-security-cel` + `best-practices-cel` | capabilities, root user/group, procMount, AppArmor, sysctls, volume types → PSS; `require-ro-rootfs`, `require-drop-all` → best-practices |
| `validate-resources` | `best-practices-cel/require-pod-requests-limits` | |
| `require-pod-probes-audit` | `best-practices-cel/require-probes` | |
| `image-hygiene-audit` | `best-practices-cel/disallow-latest-tag` | |
| `rbac-least-privilege-enforce` | best-practices RBAC set | Keep the *wildcard* rule's fixed CEL idiom; the binding rules are standard |

**REBASE** — adopt the upstream policy, keep our parameterisation:

| Ours | Upstream | What stays ours |
| --- | --- | --- |
| `image-supply-chain-audit` / `-enforce` | `restrict-image-registries` | The registry allowlist (Harbor-only, ADR-0033) |
| `disallow-nodeport-services`, `disallow-service-external-ips` | `restrict-node-port`, `restrict-service-external-ips` | Nothing — adopt as-is |
| `namespace-defaults-generate` | best-practices `add-ns-quota` / `add-networkpolicy` | The opt-in label gating |
| `namespace-tenancy-audit` labels rule | `require-labels` | The `webgrip.io/*` taxonomy |

**KEEP** — encodes a decision no catalogue can know:

- **CNPG governance** (storage class, walStorage, backup plugin, ScheduledBackup, redundant
  PodMonitor) — no `cloudnative-pg` directory exists upstream, and these encode the backup
  tiers and the designated-replica insight that took two days to get right.
- **Longhorn mutations** (backup enrollment, replica ceiling) — bespoke storage economics.
- **`stateful-delete-protection-enforce`** — the break-glass annotation contract.
- **Image verification trio** (`image-verify*`, `image-attestations`, `image-cve-budget`) —
  OpenBao Transit anchor and the OpenVEX-aware CVE-budget predicate. Genuinely novel.
- **HTTPRoute rules** — the dual-gateway topology; upstream has no `gateway-api` directory.
- **`namespace-tenancy-enforce`** — the `default-deny`/`allow-dns` naming contract.
- **`secrets-observability-ops-enforce`** — the VM-operator selector contract.
- **`exception-governance`** — governs our own waivers.
- **`flux-governance-enforce`** — upstream `flux-cel` has only two policies
  (`verify-flux-sources`, `verify-git-repositories`) against our seven rules. **Keep**, and
  contribute the delta upstream if worth it.
- **`cert-manager-governance`** — upstream has a cert-manager directory worth diffing, but
  the issuer/DNS-zone scoping is ours.

## What we are missing (the enterprise gap)

Upstream best-practices we do **not** implement at all:

- **`disallow-cri-sock-mount`** — mounting the container runtime socket is container escape.
  Given the estate waives `hostPath` for four CI workloads, this is the highest-value gap.
- **`disallow-default-namespace`**
- **`check-deprecated-apis`**
- **`require-drop-cap-net-raw`**

Plus the nine PSS Baseline controls above. **A cluster that believes it enforces Baseline and
implements 4 of 13 controls is the most dangerous state in this document** — the belief is
what's wrong, not the coverage.

## Measured baseline (2026-08-06)

`kubescape scan framework nsa,mitre --submit=false` — **compliance score 70/100**, coverage
86% (38/40; the two gaps need the in-cluster operator for kubelet data).

The headline is not the score. It is the **size difference between what our policies report
and what an independent scorer finds on the same cluster**:

| Control | Kubescape failures | Our equivalent rule reports |
| --- | --- | --- |
| C-0053 Access container service account | **289** | `require-serviceaccount-token-opt-out` — 17 |
| C-0270 Ensure CPU limits are set | **147** | `validate-resources` — 7 |
| C-0015 List Kubernetes secrets (RBAC) | **142** | *no coverage* |
| C-0030 Ingress and Egress blocked | **140** | *no equivalent* |
| C-0017 Immutable container filesystem | **134** | `require-readonly-root-filesystem` — 0 (Audit) |
| C-0034 Automatic mapping of service account | **134** | 17 |
| C-0055 Linux hardening (seccomp/AppArmor/caps) | **118** | 14 |
| C-0013 Non-root containers | **111** | `run-as-non-root` — 14 |
| C-0002 Prevent command execution (`exec` RBAC) | **94** | *no coverage* |
| C-0037 CoreDNS poisoning (endpoint RBAC) | **87** | *no coverage* |
| C-0016 Allow privilege escalation | **76** | `privilege-escalation` — 5 |
| C-0012 Credentials in configuration files | **49** | *no coverage* |

**The order-of-magnitude gap is the finding.** It is not that our rules are wrong — it is that
every Pod policy carries a 17-namespace `NotIn` exclusion, so we grade ourselves on the
application tier and score the platform tier not at all. `arc-systems`, `cert-manager`,
`cnpg-system`, `flux-system`, `kube-system`, `longhorn-system`, `network`, `observability`,
`security` are all invisible to our own reporting — and they are where the privileged
workloads live.

C-0012, C-0015, C-0002 and C-0037 confirm the "controls we never considered" section below
with real numbers: **secrets-in-config and RBAC read/exec paths have zero coverage today.**

### Controls that are noise for this cluster

Do not chase these; record them as accepted:

- **C-0026 Kubernetes CronJob** (31 failures, score 0) — flags *every* CronJob as a MITRE
  persistence technique. All 31 are ours and legitimate.
- **C-0036 / C-0039 Validate/mutate admission controller** — flags the existence of admission
  webhooks. That is Kyverno.
- **C-0068 PSP enabled** — PodSecurityPolicy was removed from Kubernetes years ago.

### CIS: score 43, and largely not trustworthy on Talos

`cis-v1.10.0` reports 43/100 at **59% coverage**, and much of the deficit is control-plane
**file-permission and ownership** checks (`C-0092`–`C-0097` et al) that have no meaning on an
immutable OS with no host filesystem to `chmod`. Several flagged items are in fact configured
correctly — Talos already sets `--audit-log-path`, `--audit-policy-file`,
`--audit-log-maxbackup=10` and `--audit-log-maxsize=100`, yet C-0132/C-0133 report failed.

**Treat the CIS number as uninformative here.** Three findings from it are real, verified
against the live API server flags, and none of them are Kyverno's business — they are Talos
machine config:

| Finding | Why it matters |
| --- | --- |
| `--kubelet-certificate-authority` unset | the API server does not verify kubelet serving certs — MITM between control plane and kubelet |
| `AlwaysPullImages` not in `--enable-admission-plugins` (only `NodeRestriction`) | a pod can reuse an image another namespace already pulled with credentials it does not have |
| `EventRateLimit` not enabled | event-flood DoS on etcd — **this cluster has already lived it**: the Kyverno hourly rescan emitted ~12k events/hour and inflated the apiserver watch cache to 3.4 GiB, which is why background scanning was moved to daily |

That is a whole hardening surface — **API server configuration** — that the entire Kyverno
programme does not touch. It belongs in `talos/patches/controller/`, not in a policy.

## Controls we never considered

The sections above compare our estate to what it *tried* to be. This section is the larger
gap: controls that were never on the list. `other-cel` alone holds **66 policies**; these are
the ones that matter for **this** cluster, each tied to something already true here.

### Privilege escalation — the biggest hole

`rbac-least-privilege-enforce` checks wildcards on **Roles** and cluster-admin bindings. It
does not check the verbs that let a subject grant themselves more, across 109 Roles and 118
ClusterRoleBindings:

| Policy | Why it matters here |
| --- | --- |
| **`restrict-escalation-verbs-roles`** | `escalate`, `bind`, `impersonate` are the classic self-promotion path and are **completely uncovered** today |
| **`restrict-clusterrole-nodesproxy`** | `nodes/proxy` is the kubelet API — full node compromise, no audit trail |
| `restrict-binding-system-groups` | binding to `system:masters` bypasses RBAC entirely |
| `restrict-secret-role-verbs` | who may read Secrets — the counterpart to the whole ESO/OpenBao investment |
| `restrict-edit-for-endpoints` | endpoint hijack (CVE-2021-25740) |
| `restrict-wildcard-verbs` / `restrict-wildcard-resources` | our wildcard rule covers Roles only, not ClusterRoles |

### Secrets — we enforce delivery but not consumption

The estate moved to ESO + OpenBao and consumes via `existingSecret`/`envFromSecret` **by
convention**. Nothing enforces it:

- **`disallow-secrets-from-env-vars`** — inline secret env vars leak into logs, crash dumps
  and `kubectl describe`. This is the single control that would make the ESO migration
  *enforced* rather than merely adopted.
- `check-serviceaccount-secrets`, `deny-secret-service-account-token-type`,
  `restrict-sa-automount-sa-token`

### Container escape — narrowing the CI waivers

Four CI workloads hold `hostPath` + `privileged` waivers. Rather than leave them open:

- **`disallow-cri-sock-mount`** (best-practices) and `docker-socket-requires-label`
- **`ensure-readonly-hostpath`**, `limit-hostpath-vols`, `limit-hostpath-type-pv` — turn a
  blanket hostPath waiver into a *scoped* one
- **`block-ephemeral-containers`** — `kubectl debug` attaches a container that sidesteps the
  original pod's admission decision entirely
- `prevent-cr8escape`, `check-node-for-cve-2022-0185`

### Availability and placement — encode what we learned the hard way

- **`restrict-controlplane-scheduling`** — ADR-0002 pins workloads to the worker pool after
  the soyo control-plane OOM cascade. It is currently a *convention*; this makes it a rule.
- **`ensure-probes-different`** — identical liveness and readiness turns a slow dependency
  into a restart storm. Directly relevant given the restart incidents in this cluster.
- `require-deployments-have-multiple-replicas`, `pdb-maxunavailable`,
  `topologyspreadconstraints-policy` — we audit PDB/topology already; these are the enforcing
  counterparts
- `require-qos-guaranteed` / `memory-requests-equal-limits` — QoS class decided which pods
  Talos' PSI OOM controller killed first in the 2026-07-11 incident
- `prevent-bare-pods` — a Pod with no controller never comes back

### Workload and supply-chain hygiene

`imagepullpolicy-always`, `require-image-checksum`, `restrict-deprecated-registry`,
`deny-commands-in-exec-probe`, `limit-containers-per-pod`, `restrict-jobs`,
`enforce-pod-duration`.

### Networking and storage

`restrict-networkpolicy-empty-podselector` (relevant to the default-deny contract),
`disallow-localhost-services`, `restrict-service-port-range`, `enforce-readwriteonce-pod`,
`require-emptydir-requests-limits`.

### Also missing, from best-practices

`disallow-default-namespace`, `check-deprecated-apis`, `require-drop-cap-net-raw`.

**Rough shape of the gap:** we enforce ~79 rules; a defensible enterprise baseline for this
cluster is closer to **120–140 controls**, and the additions are weighted toward privilege
escalation and secret handling — the two areas where a homelab most resembles a production
estate and where our current coverage is thinnest.

## Kubescape is an assurance layer, not an admission engine

Do **not** replace Kyverno with it. Adopt it for what admission control structurally cannot do:

1. **Independent scoring against published frameworks** — NSA-CISA, MITRE ATT&CK, CIS,
   SOC2, PCI-DSS. Answers "how hardened are we" with a number a third party defined, rather
   than our own policies grading their own homework.
2. **Network policy generation from observed traffic.** The operator watches actual flows and
   emits NetworkPolicies. This directly de-risks the outstanding `security` namespace work,
   where guessing the allow-list would fail admission cluster-wide — and it is exactly the
   24h-observation step that would have prevented the litellm MCP outage.
3. **Runtime reachability (eBPF).** Filters the 117 critical CVEs down to those actually
   loaded at runtime — turns [the third-party image backlog](rfc-third-party-image-supply-chain.md)
   from a wall of noise into a ranked list.
4. **`kubescape vap`** generates VAPs from its controls — an engine-independent second path.

Cost: another in-cluster operator with an eBPF node agent, on a cluster that removed Falco and
Tetragon for resource pressure ([runtime RFC](rfc-runtime-detection-response.md)). Start with
the **CLI only** — zero cluster footprint, immediate framework score — and decide on the
operator from that evidence.

## Proposal

0. **DONE 2026-08-06** — `kubescape` added to `.mise.toml` (4.0.11) and the baseline taken:
   **NSA/MITRE 70/100**. Re-run after each batch; that number is the programme's scoreboard.
   Always `--submit=false`.
1. **Unblock and re-plan the CEL migration** on explicit multi-kind matching; delete the
   autogen dependency from the wave plan.
2. **Baseline the estate with Kubescape CLI** — one command, no install, gives the
   framework-scored starting point that this RFC's claims should be checked against.
3. **Adopt `pod-security-cel` baseline + restricted**, replacing three of our policies.
   This is the single biggest correctness win: 4-of-13 → complete. Audit first; our existing
   exceptions must be re-pointed at the upstream policy names in the same commit.
4. **Adopt the four missing best-practices**, `disallow-cri-sock-mount` first.
5. **Rebase the parameterised ones**, keeping our allowlists.
6. **Keep and migrate by hand only the KEEP list** — roughly 8 policies rather than 25.
7. **Adopt the missing controls in themed batches**, Audit first, most-valuable first:
   privilege-escalation verbs → secrets-in-env-vars → hostPath narrowing + ephemeral
   containers → placement/availability. Each batch is one commit with a sweep, per ADR-0032.
8. **Evaluate the Kubescape operator** for network-policy generation before attempting
   `security` zero-trust.

## Decisions

| ADR | Status | Decision |
| --- | --- | --- |
| candidate | — | Explicit multi-kind matching replaces autogen for CEL policies (new) |
| candidate | — | Adopt upstream catalogue for standards-derived policy; hand-write only cluster-specific policy (new) |
| candidate | — | Kubescape as assurance/scoring layer, CLI first, operator gated on evidence (new) |

## Out of scope

- The `verifyImages` gate — [own RFC](rfc-verify-policy-gating.md).
- Third-party image routing — [own RFC](rfc-third-party-image-supply-chain.md).
- Replacing Kyverno with native VAP wholesale. VAP is now a viable engine on 1.36, but
  Kyverno's exceptions, reporting and generate/mutate have no VAP equivalent.
