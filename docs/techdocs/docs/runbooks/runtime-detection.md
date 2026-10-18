# Runtime detection (Tetragon on agent pods)

Tetragon watches the agent namespaces `ploeg`, `unfold-workspaces` and `unfold-verifier` from the
worker nodes. Why it is built this way, and why it is safe after the June 2026 suspension:
[ADR-0072](../adr/adr-0072-tetragon-watches-agent-pods.md).

| Piece | Where |
| --- | --- |
| Agent DaemonSet and operator | `kubernetes/apps/security/tetragon/app/helmrelease.yaml` |
| TracingPolicies | `kubernetes/apps/security/tetragon/policies/` |
| Health alerts (VictoriaMetrics) | `kubernetes/apps/observability/victoria-metrics/app/rules/prometheusrule-security-tetragon.yaml` |
| Detection alerts (VictoriaLogs) | `.../rules/vmrule-runtime-detection.yaml`, evaluated by `vmalert-runtime` |
| Events | VictoriaLogs stream `{namespace="security", container="export-stdout"}` |
| Dashboard | Grafana, Security folder, "Tetragon / Runtime Enforcement" |

Tetragon cannot see inside Kata pods (the bronze and copper sandboxes, the Claude runner, the
verifier checks). Silence from those pods means nothing.

## Read the events

Every event is JSON that VictoriaLogs splits into fields. Look at one before filtering:

```text
{namespace="security", container="export-stdout"} process_kprobe.policy_name:* | limit 1
```

Agent activity for one pod, newest first:

```text
{namespace="security", container="export-stdout"}
  (process_exec.process.pod.name:="<pod>" OR process_kprobe.process.pod.name:="<pod>")
  | sort by (_time desc) | limit 200
```

`process_*.parent.binary` and `process_*.process.arguments` say who started what. Arguments pass
through redaction filters for tokens and keys first.

## Agent not ready

`TetragonAgentNotReady`: a worker has no ready agent.

1. `kubectl -n security get pods -l app.kubernetes.io/name=tetragon -o wide`.
2. **Pending** with `Insufficient memory`: the node's memory requests are full. Tetragon has no
   PriorityClass and never preempts, by design. Find what reserves the most:

   ```sh
   kubectl describe node <node> | sed -n '/Allocated resources/,/Events/p'
   kubectl get pods -A --field-selector spec.nodeName=<node> \
     -o custom-columns=NS:.metadata.namespace,POD:.metadata.name,MEM:.spec.containers[*].resources.requests.memory
   kubectl top pods -A --sort-by=memory | head -30
   ```

   Lower the requests of workloads that reserve far more than they use (in Git, as a PR). Do not
   add a PriorityClass to Tetragon: preemption is one of the June failure modes.
3. **CrashLoopBackOff** or **OOMKilled**: read `kubectl -n security logs <pod> -c tetragon
   --previous`. An OOM kill stays inside the agent's own 512Mi; raise the request and limit
   together, never the limit alone.

## Events lost

`TetragonEventsLost`: the kernel ring buffer overflowed before the agent read it. Check the
agent's CPU throttling on the dashboard; raise the 500m CPU limit if it is pinned during bursts.

## Policy load errors

`TetragonPolicyLoadErrors`: `kubectl get tracingpoliciesnamespaced -A` and
`kubectl -n security logs <pod> -c tetragon | grep -i <policy>`. These kernels have no
`CONFIG_FPROBE` and no `CONFIG_BPF_KPROBE_OVERRIDE`: a policy that needs multi-kprobe links or the
`Override` action will not load. Revert the policy change.

## Export rate limited

`TetragonExportRateLimited` (info): a node exported more than 1000 events in a minute and dropped
the rest. Find the noisy pod:

```text
_time:1h {namespace="security", container="export-stdout"} process_exec.process.binary:*
  | stats by (process_exec.process.pod.name) count() as execs | sort by (execs desc) | limit 10
```

Raise `exportRateLimit` only after checking VictoriaLogs disk headroom (18 GiB, 30 days, shared
with every other log).

## Credential file opened

`AgentPodOpenedCredentialFile`: a process in an agent pod opened a ServiceAccount token, a
credential file or a process environment (`/proc/<pid>/environ`).

1. Read the event (above) for the binary, its parent and arguments.
2. If the reader is a known tool doing its job, add an exclusion to the rule after review.
3. If not, stop the Run or session in Unfold, then rotate what the file held. A pod's own token
   dies with the pod; a mounted Forgejo or LiteLLM secret does not.

## Outbound connect

`AgentPodConnectedOutsideCluster`: `connect()` to an address outside `10.42.0.0/16`,
`10.43.0.0/16`, loopback and the gateways `10.0.0.27`/`10.0.0.28`. The kernel saw the attempt;
the network policy may have dropped it. Check `hubble_drop_total` for the pod, then the event's
process. Stop the Run if the caller is not a known tool.

## Cluster or network tool

`AgentPodRanClusterOrNetworkTool`: `kubectl`, `nsenter`, `nc`, `nmap`, `crictl` and similar ran
inside an agent pod. Read the parent process: a build script shelling out is benign; the agent
harness starting it directly is not.

## Prove it works

After a merge that touches Tetragon, prove the path end to end with a throwaway Job in
`unfold-workspaces`. It reads its own environment and dials a documentation address (192.0.2.1,
never routed). Run it on a node where the agent is ready.

```sh
kubectl apply --dry-run=server -f tetragon-canary.yaml
kubectl apply -f tetragon-canary.yaml
```

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: tetragon-canary
  namespace: unfold-workspaces
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 900
  template:
    metadata:
      labels:
        app.kubernetes.io/name: tetragon-canary
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      nodeSelector:
        kubernetes.io/hostname: worker-1
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        runAsGroup: 65534
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: read-environ
          image: harbor.webgrip.dev/dockerhub/library/busybox:1.37.0-musl@sha256:5cec3fc171c87218698e85a52af7087de727372aae264a787b8112901a5b0092
          command: ["/bin/cat", "/proc/self/environ"]
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            requests: {cpu: 10m, memory: 16Mi}
            limits: {cpu: 100m, memory: 16Mi}
        - name: dial-out
          image: harbor.webgrip.dev/dockerhub/library/busybox:1.37.0-musl@sha256:5cec3fc171c87218698e85a52af7087de727372aae264a787b8112901a5b0092
          command: ["/bin/nc", "-w", "3", "192.0.2.1", "443"]
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            requests: {cpu: 10m, memory: 16Mi}
            limits: {cpu: 100m, memory: 16Mi}
```

Expected within five minutes (the Job itself ends `Failed`, because `nc` cannot connect):

```sh
kubectl get --raw /api/v1/namespaces/observability/services/vmalert-vmalert-runtime:8080/proxy/api/v1/alerts \
  | jq -r '.data.alerts[] | [.name, .labels.agent_pod, .labels.path // .labels.daddr // .labels.binary] | @tsv'
```

shows `AgentPodOpenedCredentialFile` (`/proc/<pid>/environ`), `AgentPodConnectedOutsideCluster`
(`192.0.2.1`) and `AgentPodRanClusterOrNetworkTool` (`/bin/nc`) for a `tetragon-canary-*` pod.
If one is missing, read the raw events for the pod (above) to see whether the event or the rule
is at fault. The Job deletes itself after 15 minutes.

## Roll back

Revert the pull request that introduced or changed Tetragon. Flux prunes the `tetragon` and
`tetragon-policies` Kustomizations and Helm removes the DaemonSet; the BPF programs detach when
the agent exits. The two Tetragon CRDs remain, so `kubectl get tracingpolicies -A` returning
nothing does not mean Tetragon runs: check `kubectl -n security get ds tetragon`.
