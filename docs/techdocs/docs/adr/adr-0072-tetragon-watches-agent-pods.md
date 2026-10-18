---
status: accepted
date: 2026-10-18
decision-makers: Ryan Grippeling
---

# Tetragon alone watches agent pods, on the worker pool, inside a reserved memory budget

## Context and Problem Statement

Nothing watches what AI agents do while they run. Ploeg Runs and Unfold sessions execute code that
a model chose, in `ploeg`, `unfold-workspaces` and `unfold-verifier`. Admission policy (Kyverno),
the network policies and the Kata sandbox bound what those pods may do, but no record says what
they actually did: which programs started, which credential files were opened, which addresses
they tried to reach.

The cluster had runtime detection once. Falco and Tetragon ran on every node until 2026-06-19,
when both were commented out of `kubernetes/apps/security/kustomization.yaml` because "repeated
cluster outages were attributed to these runtime-security agents". The
[runtime detection RFC](../rfc/rfc-runtime-detection-response.md) asked for three things before any
return: find out what actually destabilised the cluster, pick one detector, and give detections
somewhere to go. This record answers all three for the agent namespaces. It covers
`kubernetes/apps/security/tetragon/`, the alert rules under
`kubernetes/apps/observability/victoria-metrics/app/rules/`, the `vmalert-runtime` evaluator, and
the removal of `kubernetes/apps/security/falco/`.

### What caused the June outages

No primary evidence survives, so the cause cannot be proven:

* The suspension landed inside an unrelated Grafana commit on 2026-06-19 at 07:17 (+02:00), with
  only the YAML note as its explanation. No incident record names Falco or Tetragon.
* VictoriaMetrics keeps 15 days and VictoriaLogs 30 days. The Talos OOM controller's kill ledger
  (`talosctl get oomactions`) resets at reboot; on 2026-10-18 the oldest entry on
  `fringe-workstation` was from 2026-09-29.

What the record does show is the setting. The suspension was one step of a memory-freeing sweep
in the middle of storage incidents: the
[2026-06-18 Longhorn instance-manager roll](../incidents/2026-06-18-longhorn-im-cpu-rolling-detonation.md)
was still recycling replicas, and the same morning's commits right-sized memory requests and
suspended Tempo and k6 "to free fringe resources". Those incidents were later traced to a Longhorn
setting and to BestEffort pods, not to the agents. The agents were probably bystanders that made
memory pressure worse, not the root cause.

Six properties of the June configuration made them plausible contributors. This design removes
each of them:

| June configuration | Why it could hurt | This design |
| --- | --- | --- |
| Both agents on every node, including the three 12 GiB control-plane soyos (then still running apps at 68–78% memory) | Two eBPF stacks beside etcd on the scarcest RAM | One agent, only on `node.webgrip.io/pool: worker`; the soyos never run it |
| Requests 256Mi, limits 1Gi per agent (plus a 256Mi export sidecar) | Up to ~2.3 GiB per node the scheduler never reserved | Memory request equals limit on every container: 512Mi + 48Mi, all reserved |
| `system-node-critical` priority | Kubelet gives node-critical pods `oom_score_adj` -997, so the kernel kills other pods first (the 06-09 victim was BestEffort `longhorn-manager`); the scheduler may also evict application pods to place them | No PriorityClass: the pod never preempts and waits Pending when a node has no room |
| `tolerations: [{operator: Exists}]` | Scheduled onto nodes tainted for pressure or not-ready | No tolerations |
| Tetragon exported every exec and exit on every node, host and `kube-system` included; Falco hooked every syscall | Event volume and per-syscall overhead on every process, including etcd and the DinD CI runner that went live on 06-18 | Two kprobes, namespaced to the agent namespaces; export limited to those namespaces and capped at 1000 events per minute per node |
| Request far below real use | The Talos OOM controller ranks pods by use relative to request, so the agents were standing kill candidates, and each restart reloads BPF programs | With request equal to limit on every container the pod cgroup has `memory.max`, which the ranker scores zero and skips (talos#13437, Talos 1.13.4 and later; the nodes run 1.13.10) |

### What the nodes support

Read-only checks on 2026-10-18 on `fringe-workstation`, `worker-1` and `worker-2` (Talos 1.13.10,
kernel 6.18.48-talos):

* `/sys/kernel/btf/vmlinux` exists and `CONFIG_DEBUG_INFO_BTF=y`, so Tetragon needs no BTF file.
* `CONFIG_KPROBES=y`, `CONFIG_BPF_EVENTS=y`. `CONFIG_FPROBE` is not set, so Tetragon attaches one
  kprobe per hooked function instead of a multi-kprobe link; with two hooks that costs nothing.
* The active LSM list is `lockdown,capability,yama,selinux,bpf,landlock`, lockdown is `none`, and
  SELinux is enforcing.
* `CONFIG_BPF_KPROBE_OVERRIDE` is not set, so Tetragon's `Override` action is unavailable.
  `Sigkill` remains the in-kernel response primitive if one is ever chosen.

### What Tetragon can and cannot see

Tetragon observes the host kernel. Pods that run under Kata (`runtimeClassName: kata`) run their
processes in a guest kernel it cannot see. Today that is the bronze and copper sandboxes, the
Claude runner, and the delivery verifier's checks in `unfold-verifier`. Tetragon sees the pods
that run on runc: every Unfold workspace in `unfold-workspaces`, the silver team's Runs and the
sandbox launcher pods in `ploeg`. For Kata pods the controls remain the VM boundary and the egress
policy (ADR-0071, the agent egress record written in parallel).

### Room on the nodes

On 2026-10-18 memory requests were at 99% of allocatable on `fringe-workstation`, 98% on
`worker-2` and 77% on `worker-1`. A Tetragon pod needs 560Mi of requests. Until room exists it
stays Pending on the first two, by design, and `TetragonAgentNotReady` says so.

## Decision Drivers

* Never again make the cluster less stable to watch it: every byte reserved, nothing preempted,
  the control plane untouched.
* See what agents do, not everything every process does.
* One detector, and detections that reach the existing alert path.
* Observe before alerting, and a one-commit way back.

## Considered Options

* Tetragon only, scoped to the worker pool and the agent namespaces
* Falco only
* Both, as before
* Neither: rely on admission, network policy and Kata, and delete the manifests

## Decision Outcome

Chosen option: "Tetragon only, scoped to the worker pool and the agent namespaces", because it is
the only option that observes in-kernel with a policy scoped to the agent pods, uses the eBPF
stack the cluster already runs for Cilium, and has a response primitive for later.

* **Agent.** Chart `tetragon` 1.7.1 from `https://helm.cilium.io` (chart archive SHA-256
  `79ec0f7d…c632`). Images `tetragon`, `tetragon-operator` v1.7.1 and `hubble-export-stdout`
  v1.1.1, pulled through the Harbor quay proxy and pinned by digest (each digest matched quay.io
  and Harbor on 2026-10-18). DaemonSet and operator on `node.webgrip.io/pool: worker`, no
  tolerations, no PriorityClass. Agent 50m/512Mi request, 500m/512Mi limit; export sidecar
  10m/48Mi request, 200m/48Mi limit; operator 10m/128Mi request, 200m/128Mi limit. Process
  credentials, namespaces and ancestors stay off, the process cache is 32768 entries, and Helm
  does not wait for the DaemonSet, so a Pending pod never fails the release.
* **Policies.** Two `TracingPolicyNamespaced`, stamped into `ploeg`, `unfold-workspaces` and
  `unfold-verifier` by `kubernetes/apps/security/tetragon/policies/`:
  * `agent-credential-reads` hooks `security_file_open` for ServiceAccount token paths,
    `/etc/shadow`, `/proc/*/environ`, and common credential files (`.git-credentials`, `.netrc`,
    Docker and kube configs, SSH private keys).
  * `agent-outbound-connects` hooks `tcp_connect` for any destination outside loopback, the pod
    range `10.42.0.0/16`, the Service range `10.43.0.0/16` and the two gateway addresses.
  * Program starts need no policy: Tetragon's base sensor records every exec, and the export
    filter keeps those from the three namespaces.
* **Export.** Tetragon writes JSON to its export file; the `export-stdout` sidecar prints it, and
  the existing Alloy pod-log pipeline ships it to VictoriaLogs as stream
  `{namespace="security", container="export-stdout"}`. Only agent-namespace execs and the two
  policies' events are exported, at most 1000 per minute per node, with redaction filters for
  tokens, keys and `Authorization` headers in arguments. Alloy is unchanged.
* **Alerts.** Health rules live in `prometheusrule-security-tetragon.yaml` and are evaluated by
  the main `vmalert` against VictoriaMetrics: `TetragonAgentNotReady`, `TetragonEventsLost`,
  `TetragonPolicyLoadErrors` (warning) and `TetragonExportRateLimited` (info). Detection rules
  live in the `runtime-detection` VMRule (`rules: runtime-detection`) and are evaluated by a new
  `vmalert-runtime` against VictoriaLogs: `AgentPodOpenedCredentialFile`,
  `AgentPodConnectedOutsideCluster` and `AgentPodRanClusterOrNetworkTool`. They route through
  Alertmanager to ntfy like every other alert.
* **Main vmalert.** It gains `ruleSelector: {rules: DoesNotExist}`. It used to load every VMRule,
  including the LogsQL audit rules, which it evaluated against VictoriaMetrics; on 2026-10-18 all
  five audit rules reported HTTP 400 there. With the selector, LogsQL rules run only in their own
  evaluators.
* **Falco is retired.** `kubernetes/apps/security/falco/` and its Grafana dashboard are deleted.
  The existing Tetragon dashboard stays.

### Staged rollout

0. **Room.** Before merging, check free memory requests on the three workers (runbook). The merge
   is safe without room; the agent just waits Pending on the full nodes.
1. **Observe (this change).** Agents, policies, export and health alerts go live. The three
   detection rules carry `severity: info` and `stage: observe`, which Alertmanager sends to the
   null receiver: they show in vmalert and Grafana but page nobody. Abort and revert if, during
   the first 48 hours on any worker: the Talos OOM controller kills anything, a Tetragon container
   restarts, agent CPU stays above 300m, or VictoriaLogs ingest grows by more than half.
2. **Alert (a later one-line PR per rule).** After seven days in which every info alert has an
   explanation, add exclusions for the known readers and flip `AgentPodOpenedCredentialFile` to
   `critical` and the other two to `warning`.
3. **Respond (a separate record).** In-kernel `Sigkill` for credential reads by unknown binaries
   is possible on these kernels. It is not decided here.

### Rollback

Revert the merge commit. Flux prunes both Kustomizations (`prune: true`), Helm uninstalls the
DaemonSet, and the BPF programs detach when the agent exits. The `tracingpolicies.cilium.io` and
`tracingpoliciesnamespaced.cilium.io` CRDs stay, as they have since May, so check the DaemonSet,
not the CRDs, to see whether Tetragon runs. Reverting also reverts the main `vmalert` selector,
which only brings back the audit rules' existing errors.

### Consequences

* Good, because agent activity on runc pods is recorded for 30 days, searchable by pod, and can
  page.
* Good, because the soyos and etcd never run an eBPF security agent again, and the agent cannot
  take memory it did not reserve or evict another pod.
* Good, because the main `vmalert` stops evaluating LogsQL rules it cannot run.
* Bad, because Kata pods stay invisible: the bronze and copper sandboxes, the Claude runner and
  the verifier checks.
* Bad, because the agent waits Pending on `fringe-workstation` and `worker-2` until their memory
  requests are lowered, and agent pods scheduled there run unobserved until then.
* Bad, because the chart still comes from an HTTP Helm repository, which the flux-governance
  policy reports in Audit; the chart version is pinned exactly.
* Bad, because agent execs share VictoriaLogs' 18 GiB, 30-day budget with every other log; the
  rate limit bounds the worst case and `TetragonExportRateLimited` shows when it binds.

### Confirmation

* `./scripts/run-flux-local-test.sh` renders `tetragon`, `tetragon-policies` and
  `victoria-metrics` cleanly, and `./scripts/test-vmalert-rules.sh` passes
  `security-tetragon.test.yaml`.
* `kubectl -n security get ds tetragon -o wide` shows one ready pod per worker with room, and none
  on `soyo-*`.
* `kubectl get tracingpoliciesnamespaced -A` lists both policies in all three namespaces, and
  `tetragon_tracingpolicy_loaded{state="enabled"}` counts them.
* A throwaway pod in `unfold-workspaces` that reads its ServiceAccount token and connects to an
  outside address produces `AgentPodOpenedCredentialFile` and `AgentPodConnectedOutsideCluster`
  in `vmalert-runtime` within five minutes (runbook, "Prove it works").
* `vmalert` reports no rule with a `lastError`.

## Pros and Cons of the Options

### Tetragon only, scoped to the worker pool and the agent namespaces

* Good, because policies are namespaced and in-kernel, so unwatched pods cost almost nothing.
* Good, because it shares the eBPF and Kubernetes identity model of Cilium, which already runs on
  every node.
* Good, because `Sigkill` gives a later response tier without another component.
* Bad, because rules are written by hand; there is no shipped ruleset like Falco's.

### Falco only

* Good, because it ships a mature ruleset and Falcosidekick routes to many channels.
* Bad, because modern eBPF instruments every syscall on the node, so cost scales with all
  workloads rather than with the watched ones.
* Bad, because it adds a second eBPF stack beside Cilium, the heavier of the two June suspects.

### Both, as before

* Bad, because the detections overlap and the memory and kernel cost doubles, which is the June
  configuration.

### Neither

* Good, because it costs nothing.
* Bad, because a model-driven process that reads a token or dials out leaves no trace, and the
  [attack-path RFC](../rfc/rfc-attack-path-analysis.md) shows privilege chains in the waiver set
  would run unobserved.

## More Information

* Technical story: [RFC: Runtime detection and response](../rfc/rfc-runtime-detection-response.md).
  Related: [RFC: security hardening](../rfc/rfc-security-hardening.md) (detect and respond),
  [RFC: agent observability](../rfc/rfc-agent-observability.md),
  [runbook: runtime detection](../runbooks/runtime-detection.md).
* Honeytokens (ADR-0075, written in parallel): a decoy file path can join
  the `Prefix` or `Postfix` list of `agent-credential-reads`, and its opens then arrive on the same
  stream and rule. A decoy needs no baseline, so its rule can be `critical` from the start; that is
  the honeytoken record's call.
* 2026-06-19 — Falco and Tetragon suspended (commented out of the security kustomization).
* 2026-10-18 — accepted by Ryan Grippeling: Tetragon reinstated in observe stage, Falco removed.
