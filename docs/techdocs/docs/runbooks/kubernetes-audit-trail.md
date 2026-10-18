# Kubernetes audit trail

What the Kubernetes API server records about each call, where those records go, and what to do
when one of the agent-plane audit alerts fires. Decision:
[ADR-0076](../adr/adr-0076-kubernetes-audit-trail-watches-the-agent-plane.md). The login and
break-glass alerts that read the same trail are in [Kubernetes login](kubernetes-login.md).

## Glossary

| Term | Meaning here |
| --- | --- |
| Audit event | One JSON line the API server writes per call: who (`user.username`), what (`verb`, `objectRef`), from where (`sourceIPs`), and the decision. |
| Level | How much of a call is written. `Metadata` is who/what/when; `Request` adds the body sent; `RequestResponse` adds the body returned too. `None` writes nothing. |
| Audit policy | The ordered rule list in `talos/patches/controller/cluster.yaml` under `apiServer.auditPolicy`. The first rule that matches a call decides its level. |
| Agent plane | The namespaces `ploeg`, `unfold-workspaces` and `unfold-verifier`, where Ploeg runs agents and Unfold runs their workspaces and verifier. |

## The path a record takes

1. Each control plane (`soyo-1`, `soyo-2`, `soyo-3`) writes `/var/log/audit/kube/kube-apiserver.log`.
   Talos rotates the file itself.
2. The `alloy-agent` pod on that node tails the file. It reads it only on nodes that carry the
   `node-role.kubernetes.io/control-plane` label, so a pod on a worker cannot plant lines in the
   trail by writing to the same host path.
3. Alloy drops two kinds of noise before shipping: routine `get`/`list`/`watch` by `system:`
   identities on anything that is not a Secret, a service account, an RBAC object or a CSR, and
   `status` updates.
4. The rest lands in the dedicated `victorialogs-audit` instance (namespace `observability`),
   separate from the application logs. Grafana reads it through the **VictoriaLogs (audit)**
   data source.
5. `vmalert-audit` evaluates the `kubernetes-audit` rule group every five minutes over the last
   fifteen and sends firing alerts to the shared Alertmanager, which routes `critical` to the
   urgent ntfy topic and `warning` to the normal one.

Retention is bounded by disk, not by the configured 365 days: the 10Gi volume caps at 9GiB, and on
2026-10-18 the trail used 6.9GB for 30 days. The noise cut in ADR-0076 removes about 40% of the
volume; expect roughly two months of history after it.

## What is recorded

| Calls | Level |
| --- | --- |
| `pods/exec`, `pods/attach`, `pods/portforward`, `pods/ephemeralcontainers`, node, pod and service proxies | RequestResponse |
| Writes to RBAC objects, CSRs and admission webhooks, anywhere | RequestResponse |
| Writes to pods, service accounts, Jobs, NetworkPolicies and CiliumNetworkPolicies in the agent plane; writes to CiliumClusterwideNetworkPolicies | Request |
| Secret and ConfigMap reads and writes, service-account token requests, token reviews | Metadata |
| Secret `watch` in the agent plane | Metadata |
| Every other call, except the exclusions below | Metadata |

Not recorded: leases, events, endpoints, self-access reviews, every `watch` outside the rule
above, health and discovery URLs, policy and vulnerability report churn from Kyverno and
Trivy, Longhorn's own CRD updates, and metrics-server's and Kyverno's access reviews.

## Query the trail

In Grafana, Explore, data source **VictoriaLogs (audit)**. Useful LogsQL:

```text
_time:1h "objectRef.namespace":="ploeg" "objectRef.subresource":~"^(exec|attach|portforward)$"
_time:1d "objectRef.resource":="secrets" "objectRef.namespace":~"^(ploeg|unfold-workspaces|unfold-verifier)$" | stats by ("user.username") count()
_time:1d "user.username":="oidc:ryan@webgrip.nl" verb:~"^(create|update|patch|delete)$"
_time:15m | stats by (node) count()
```

From a workstation without Grafana, the API server proxies the service read-only:

```sh
q='_time:15m | stats by (node) count()'
kubectl get --raw "/api/v1/namespaces/observability/services/vlsingle-victorialogs-audit:9428/proxy/select/logsql/query?query=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$q")"
```

The state of every audit rule:

```sh
kubectl get --raw /api/v1/namespaces/observability/services/vmalert-vmalert-audit:8080/proxy/api/v1/alerts
```

## Exec into agent namespace

`KubernetesExecIntoAgentNamespace` (warning) fires when anyone but CloudNativePG or the
disaster-recovery check uses `exec`, `attach`, `port-forward` or an ephemeral debug container on a
pod in the agent plane. A shell there can read the pod's service-account token, provider keys and
repository credentials.

1. Ask the person behind `user`. The owner debugging a Run is the usual answer.
2. If `user` is `admin`, an agent session or a terminal is using the break-glass certificate;
   `KubernetesBreakGlassCertificateUsed` fires alongside. Switch that session to the OIDC context.
3. If nobody claims it, read the RequestResponse events for the pod and the command
   (`requestURI` holds the `command=` parameters) and revoke the credential.

## Secret read in agent namespace

`KubernetesSecretReadInAgentNamespace` (critical) fires when an identity outside the allow-list
reads, lists or watches a Secret in the agent plane. The allow-list is the readers seen over the
14 days before 2026-10-18: Flux, External Secrets, Trivy, CloudNativePG and the Ploeg database's own
service accounts, the garbage and namespace controllers, kubelets, and Unfold inside
`unfold-workspaces`.

1. Read the events: `objectRef.name` names the Secret, `sourceIPs` the caller.
2. A legitimate new reader (a controller added in a pull request) goes on the allow-list in
   `kubernetes/apps/observability/victoria-metrics/app/rules/vmrule-audit.yaml`, through a pull
   request.
3. Anything else: rotate every Secret it read (see [secret rotation](secret-rotation.md)) and
   remove the reader's access.

## Network policy changed outside GitOps

`KubernetesNetworkPolicyChangedOutsideGitOps` (critical) fires when anything but Flux, Kyverno's
generate rules, the namespace and garbage controllers, or Unfold inside `unfold-workspaces` writes
a NetworkPolicy, CiliumNetworkPolicy or CiliumClusterwideNetworkPolicy. In the agent plane the
event carries the request body, so the change itself is visible.

1. Read the event and compare the object with Git.
2. Revert a hand edit by letting Flux reconcile (`flux reconcile kustomization <name>`), or delete
   an object Git does not declare.
3. A legitimate new writer goes on the rule's allow-list through a pull request.

## Audit trail incomplete

`KubernetesAuditTrailIncomplete` (warning) fires when audit lines arrived from fewer than three
control planes for thirty minutes. A Talos upgrade reboots one node for a few minutes and does not
trip it.

1. Find the silent node: `_time:15m | stats by (node) count()`.
2. Check its `alloy-agent` pod in `observability` and the node's API server static pod.
3. If both run, the node may have lost the audit policy: compare its machine config with
   `talos/patches/controller/cluster.yaml` (`talosctl -n <ip> get machineconfig -o yaml`).

## Prove an alert fires

Each command below fails harmlessly, because the pod, Secret or policy does not exist, and still
writes an audit event that matches the rule. `kubectl exec` looks the pod up first and stops there,
so the exec test posts to the exec endpoint directly. Run it with your OIDC context, wait up to
ten minutes, and check the alert list above or ntfy.

| Alert | Command |
| --- | --- |
| `KubernetesExecIntoAgentNamespace` | `kubectl create --raw '/api/v1/namespaces/unfold-verifier/pods/audit-alert-test/exec?command=true&stdout=true' -f /dev/null` |
| `KubernetesSecretReadInAgentNamespace` | `kubectl -n unfold-verifier get secret audit-alert-test` |
| `KubernetesNetworkPolicyChangedOutsideGitOps` | `kubectl -n unfold-verifier delete networkpolicy audit-alert-test` |

The alerts resolve on their own fifteen minutes later.
