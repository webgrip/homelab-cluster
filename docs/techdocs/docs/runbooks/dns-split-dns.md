# Runbook: Split-horizon DNS (CoreDNS + k8s-gateway)

Use this when pods inside the cluster cannot resolve `*.webgrip.dev` hostnames (NXDOMAIN, "no such host", `lookup: no such host`) while your workstation resolves them fine.

## Architecture

```
Pod DNS query ──▶ CoreDNS (10.43.0.10) ──forward webgrip.dev──▶ k8s-gateway (10.0.0.26:53)
                                                                            │
                                                              reads HTTPRoutes/Services
                                                                            │
                                                            returns Envoy Gateway external IP
```

Two distinct DNS paths exist for `${SECRET_DOMAIN}`:

| Path | Resolver | Used by |
|---|---|---|
| External (internet) | Cloudflare → Envoy Gateway external LB IP | Browsers outside LAN |
| Internal (cluster pods) | CoreDNS → k8s-gateway → HTTPRoute IPs | Pods talking to other services |

## Fast triage

1) **Can your workstation resolve it?**

```bash
dig authentik.webgrip.dev +short
# Should return the Envoy Gateway external LB IP (e.g. 10.0.0.27)
```

If this fails, the problem is upstream (Cloudflare DNS, Envoy Gateway, or the HTTPRoute itself).

1) **Can a pod resolve it?**

```bash
kubectl run dns-test --rm -it --restart=Never --image=busybox:1.36 -- nslookup authentik.webgrip.dev
```

If this returns NXDOMAIN but step 1 works, the problem is **CoreDNS not forwarding to k8s-gateway**.

1) **Can CoreDNS reach k8s-gateway directly?**

```bash
kubectl exec -n observability deployment/grafana-deployment -- nslookup authentik.webgrip.dev 10.0.0.26
```

If this works, the problem is only the CoreDNS forwarding rule. If it fails too, k8s-gateway itself is down.

## Root cause: missing CoreDNS zone forward

The most common cause is CoreDNS lacking a zone block for `${SECRET_DOMAIN}`. Check:

```bash
kubectl get configmap -n kube-system coredns -o jsonpath='{.data.Corefile}'
```

You should see a zone like:

```
dns://webgrip.dev:53 {
    errors
    forward . 10.0.0.26
    cache {
        prefetch 20
        serve_stale
    }
    log {
        class error
    }
}
```

If this is **missing**, CoreDNS forwards `webgrip.dev` queries to the upstream resolver (`/etc/resolv.conf`) instead of k8s-gateway, and the upstream resolver doesn't know about internal hostnames → NXDOMAIN.

## Fix: add the CoreDNS zone

The CoreDNS config is GitOps-managed at:

- `kubernetes/apps/kube-system/coredns/app/helmrelease.yaml`

Add a second server block inside `servers:`:

```yaml
- zones:
    - zone: webgrip.dev
      scheme: dns://
      use_tcp: true
  port: 53
  plugins:
    - name: errors
    - name: forward
      parameters: . 10.0.0.26
    - name: cache
      configBlock: |-
        prefetch 20
        serve_stale
    - name: log
      configBlock: |-
        class error
```

After committing, Flux will reconcile. If CoreDNS doesn't reload automatically:

```bash
kubectl rollout restart deployment/coredns -n kube-system
```

## Verify the fix

```bash
kubectl exec -n observability deployment/grafana-deployment -- nslookup authentik.webgrip.dev
# Should return 10.0.0.27
```

## Related checks

- **Is k8s-gateway running?**

  ```bash
  kubectl get pods -n network -l app.kubernetes.io/name=k8s-gateway
  ```

  It should show `1/1 Running`.

- **Is k8s-gateway reachable from the node?**

  ```bash
  dig @10.0.0.26 authentik.webgrip.dev +short
  ```

  If not, check the LoadBalancer service and Cilium LB IPAM.

- **Is the HTTPRoute for the target service healthy?**

  ```bash
  kubectl get httproute -A | grep <service>
  ```

## Symptoms that look like this runbook

| Symptom | Likely cause | Runbook |
|---|---|---|
| Grafana "Failed to get token from provider" | Pod can't resolve `authentik.webgrip.dev` | This one, then [authentik-oidc-login](authentik-oidc-login.md) |
| k6 canary pods get NXDOMAIN | Same DNS hole | This one |
| Any pod-to-pod communication using `*.webgrip.dev` | Same DNS hole | This one |
| Workstation resolves, pod doesn't | Split DNS gap | This one |
| Neither workstation nor pod resolves | Envoy Gateway or HTTPRoute down | [envoy-gateway](envoy-gateway.md) |
