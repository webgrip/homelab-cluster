# Runbook: Cluster Health

Use this runbook for a complete, repeatable health check of the homelab cluster. It is designed for both human operators and the `cluster-health` Copilot custom agent.

The goal is not to chase every log line. The goal is to prove whether GitOps is converging, whether the Kubernetes substrate is healthy, whether platform dependencies are available, and whether applications are impacted.

## Standard

A cluster health check must follow this dependency order:

1. Flux reconciliation and GitOps sources
2. Kubernetes nodes, workloads, events, and CRDs
3. Talos/node health
4. Storage
5. Network, DNS, and ingress
6. Certificates and external edges
7. Observability and alerting
8. Applications
9. Standards drift and durable GitOps follow-up

Do not start at application logs unless Flux, Kubernetes primitives, storage, and network basics have already been checked.

## Guardrails

- Prefer read-only commands during diagnosis.
- Do not mutate the cluster during a health check unless a separate fix step is explicitly approved.
- Do not print decoded Secret values.
- Do not edit `*.sops.yaml` files automatically.
- If a finding requires a secret change, document the Secret name, namespace, required keys, and a plaintext template for a human to encrypt with SOPS.
- Durable fixes should be made in Git and reconciled by Flux.

## Required context

Before checking the cluster, confirm:

```bash
pwd
git --no-pager status --short
command -v kubectl flux talosctl helm jq
kubectl cluster-info
```

If live cluster access is unavailable, perform a manifest-only audit against `kubernetes/` and mark all runtime-only checks as not verified.

## Phase 1: Flux reconciliation

```bash
flux get kustomizations -A
flux get helmreleases -A
flux get sources git -A
flux get sources oci -A
flux get sources helm -A
kubectl -n flux-system get pods
kubectl -n flux-system get events --sort-by=.lastTimestamp
```

Investigate any resource that is:

- `Ready=False`
- `Unknown`
- suspended
- stale beyond its expected interval
- reporting build, source, SOPS, Helm, or dependency errors

Useful follow-up:

```bash
kubectl -n <namespace> describe kustomization.kustomize.toolkit.fluxcd.io <name>
kubectl -n <namespace> describe helmrelease.helm.toolkit.fluxcd.io <name>
kubectl -n flux-system logs deploy/kustomize-controller --tail=200
kubectl -n flux-system logs deploy/helm-controller --tail=200
kubectl -n flux-system logs deploy/source-controller --tail=200
```

Classify Flux failures as one of:

- source fetch/auth failure
- OCI/Helm repository resolution failure
- Kustomize build failure
- Helm install/upgrade failure
- missing CRD/API version
- SOPS/decryption/secret material issue
- dependency ordering issue
- manual drift

## Phase 2: Kubernetes substrate

```bash
kubectl get nodes -o wide
kubectl get ns
kubectl get pods -A -o wide
kubectl get deploy,sts,ds,job,cronjob -A
kubectl get events -A --sort-by=.lastTimestamp | tail -n 100
kubectl get crds
```

Look for:

- NotReady nodes
- pods in `CrashLoopBackOff`, `ImagePullBackOff`, `ErrImagePull`, `CreateContainerConfigError`, `Pending`, or `Evicted`
- deployments/statefulsets with unavailable replicas
- daemonsets missing expected nodes
- failing jobs or cronjobs
- namespaces stuck terminating
- CRD/API version mismatches

## Phase 3: Talos and node health

If Talos access is available:

```bash
talosctl health
talosctl version
talosctl get members
talosctl get machines
```

If Talos access is not available:

```bash
kubectl describe nodes
```

Look for:

- kubelet readiness issues
- etcd/control-plane instability
- disk pressure, memory pressure, PID pressure
- node version skew
- flapping Ready conditions

## Phase 4: Storage

```bash
kubectl get pvc -A
kubectl get pv
kubectl get volumeattachments
kubectl -n longhorn-system get pods
kubectl -n longhorn-system get volumes.longhorn.io,engines.longhorn.io,replicas.longhorn.io 2>/dev/null || true
```

Look for:

- pending PVCs
- released or failed PVs
- stuck VolumeAttachments
- Longhorn degraded volumes
- failed replica scheduling
- backup target failures
- multi-attach loops

## Phase 5: Network, DNS, and ingress

```bash
kubectl -n kube-system get pods -l k8s-app=cilium
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl get svc,endpoints,endpointslices -A
kubectl get gateway,httproute,tlsroute,referencegrant -A 2>/dev/null || true
kubectl get networkpolicy -A
```

If the Cilium CLI is available:

```bash
cilium status
```

Look for:

- CoreDNS not ready
- Services without endpoints
- HTTPRoutes not `Accepted`
- HTTPRoutes with unresolved refs
- Gateways not programmed
- Cilium agent/operator failures
- network policies isolating workloads unexpectedly

## Phase 6: Certificates and external edges

```bash
kubectl get certificate,certificaterequest,issuer,clusterissuer -A 2>/dev/null || true
kubectl -n cert-manager get pods
kubectl get challenges,orders -A 2>/dev/null || true
```

Look for:

- not-ready certificates
- certificates approaching expiry
- failed ACME challenges
- issuer authentication failures
- DNS/provider errors

Do not inspect TLS private key Secret values.

## Phase 7: Observability and alerts

```bash
kubectl -n observability get pods
kubectl get servicemonitor,podmonitor,prometheusrule,probe -A 2>/dev/null || true
kubectl -n observability get events --sort-by=.lastTimestamp
```

If Prometheus or Alertmanager access is already available, check active alerts and failing targets. Do not create port-forwards as part of the default health check unless explicitly approved.

Look for:

- active critical/warning alerts
- scrape target failures
- failing PrometheusRule evaluations
- Loki/Mimir/Pyroscope ingest or compactor failures
- blackbox or k6 probe failures

## Phase 8: Application baseline

Only after platform health is understood:

```bash
kubectl get helmrelease -A
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null || true
kubectl get ingress,httproute -A 2>/dev/null || true
```

For every degraded app, identify:

- owning HelmRelease or Kustomization
- failing Kubernetes primitive
- platform dependency involved
- durable fix location in Git
- whether a SOPS-managed secret or external setup step is required

## Severity model

| Severity | Meaning |
| --- | --- |
| `CRITICAL` | Control plane, Flux reconciliation, storage, or ingress outage affecting multiple apps or preventing GitOps from converging |
| `HIGH` | A platform component or important app is degraded with user-visible impact or likely data-loss risk |
| `MEDIUM` | Degraded redundancy, failing non-critical app, stale reconciliation, noisy alerts, certificate/DNS risk with time to act |
| `LOW` | Hygiene issue, stale object, unclear ownership, documentation gap, or non-urgent standards drift |
| `INFO` | Verified healthy area or useful operational note |

## Report template

````markdown
# Cluster Health Report

**Mode:** runtime-verified | manifest-only | partial
**Scope:** <what was checked>
**Overall status:** Healthy | Degraded | Critical | Unknown
**Top risks:** <1-3 bullets>

## Executive summary
<short, plain-language summary>

## Findings
| Severity | Area | Finding | Evidence | Recommended next action |
| --- | --- | --- | --- | --- |

## Flux reconciliation
<status, failed resources, stale/suspended resources, controller notes>

## Kubernetes substrate
<nodes, pods, workloads, events>

## Talos / nodes
<Talos health or fallback node-condition summary>

## Storage
<PVC/PV/Longhorn status>

## Network / ingress / DNS
<Cilium/CoreDNS/Gateway/HTTPRoute/Service endpoint status>

## Certificates and external edges
<cert-manager, ACME, external dependencies by reference only>

## Observability
<alerts, probes, monitoring stack status>

## Application impact
<affected apps and root-cause chain>

## Standards drift
<GitOps, SOPS, ownership, rollback, documentation deviations>

## Recommended follow-up
1. <highest-value next action>
2. <next action>
3. <next action>

## Commands run
```text
<commands, redacted if needed>
```

## Not verified
<anything skipped because access/tooling was missing>
````

## Durable fix standard

When the audit identifies a real issue:

1. Prefer a Git change over an imperative cluster change.
2. Keep the change small and reversible.
3. Reconcile with Flux after the change is merged or applied.
4. Confirm the affected Flux resource becomes `Ready`.
5. Add or update runbook documentation if the issue reveals a repeatable operational pattern.
