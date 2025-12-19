# Runtime Inventory

_Last updated: 2025-12-08 @ 15:51 UTC using `kubectl get pods -A -o wide` and `kubectl get svc -A`._

## Snapshot Summary

- Flux + kube-system components account for the bulk of pods (controllers, Cilium, CoreDNS, metrics-server, Spegel, Reloader).
- Networking namespace hosts Envoy internal/external pairs, Cloudflare DNS/tunnel, and the `k8s-gateway` split-DNS responder that matches the README diagram.
- `arc-systems` entries (ARC + gha-runner-scale-set) scale dynamically, so capture their pods when documenting CI bursts.
- Application namespaces (`default`, `freshrss`, others) should be listed below as you add workloads; FreshRSS relies on Bitnami's bootstrap job to reach external Postgres.
- `invoiceninja` adds the Invoice Ninja 5.12.39 deployment (with scheduler sidecar) plus an app-template MariaDB 11.8.5 StatefulSet on Longhorn—include these pods/services the next time you refresh the tables below.
- `cnpg-system` will host the CloudNativePG operator once reconciled; include its controller and any database namespaces the next time you snapshot pods/services.

## Pods by Namespace

| Namespace | Pod Count | Highlights |
| --- | --- | --- |
| `cert-manager` | 3 | Controller, CA injector, and webhook all healthy on soyo-2/3. |
| `default` | 1 | Sample `echo` deployment scheduled on soyo-1. |
| `flux-system` | 6 | Flux operator + controllers + Weave GitOps UI evenly spread across nodes. |
| `kube-system` | 20 | Control-plane static pods, Cilium, CoreDNS, metrics-server, reloader, and Spegel. |
| `network` | 9 | Envoy gateways, Cloudflare DNS/tunnel, and `k8s-gateway`. |

```bash
$ kubectl get pods -A -o wide
NAMESPACE      NAME                                       READY   STATUS    RESTARTS        AGE     IP            NODE
cert-manager   cert-manager-6bff8dcf85-wnzg6              1/1     Running   0               5h17m   10.42.0.151   soyo-3
cert-manager   cert-manager-cainjector-846bc677f6-dcftg   1/1     Running   0               5h17m   10.42.1.30    soyo-2
cert-manager   cert-manager-webhook-68b6644bc-gkc5b       1/1     Running   0               5h17m   10.42.1.176   soyo-2
default        echo-6854795d7b-szwmw                      1/1     Running   0               5h16m   10.42.2.225   soyo-1
flux-system    flux-operator-5b4648fd59-n2k4l             1/1     Running   0               5h17m   10.42.1.226   soyo-2
flux-system    helm-controller-5f48f895-xhv7r             1/1     Running   0               5h17m   10.42.2.87    soyo-1
flux-system    kustomize-controller-6757764687-gsppn      1/1     Running   0               5h17m   10.42.0.181   soyo-3
flux-system    notification-controller-78f7b89465-stzql   1/1     Running   0               5h17m   10.42.1.236   soyo-2
flux-system    source-controller-f6f5b8f5d-x9j2q          1/1     Running   0               5h17m   10.42.2.186   soyo-1
flux-system    weave-gitops-89f9459c-7mzkd                1/1     Running   0               167m    10.42.2.44    soyo-1
kube-system    cilium-6skx7                               1/1     Running   0               5h19m   10.0.0.21     soyo-2
kube-system    cilium-operator-6cf966f58-cz5ww            1/1     Running   0               5h19m   10.0.0.22     soyo-3
kube-system    cilium-qn2rz                               1/1     Running   0               5h19m   10.0.0.22     soyo-3
kube-system    cilium-tbw4k                               1/1     Running   0               5h19m   10.0.0.20     soyo-1
kube-system    coredns-7c94d79f5f-qktvh                   1/1     Running   0               5h18m   10.42.2.98    soyo-1
kube-system    coredns-7c94d79f5f-stlwn                   1/1     Running   0               5h18m   10.42.2.213   soyo-1
kube-system    kube-apiserver-soyo-1                      1/1     Running   0               5h19m   10.0.0.20     soyo-1
kube-system    kube-apiserver-soyo-2                      1/1     Running   0               5h19m   10.0.0.21     soyo-2
kube-system    kube-apiserver-soyo-3                      1/1     Running   0               5h18m   10.0.0.22     soyo-3
kube-system    kube-controller-manager-soyo-1             1/1     Running   2 (5h19m ago)   5h19m   10.0.0.20     soyo-1
kube-system    kube-controller-manager-soyo-2             1/1     Running   0               5h19m   10.0.0.21     soyo-2
kube-system    kube-controller-manager-soyo-3             1/1     Running   0               5h18m   10.0.0.22     soyo-3
kube-system    kube-scheduler-soyo-1                      1/1     Running   2 (5h19m ago)   5h19m   10.0.0.20     soyo-1
kube-system    kube-scheduler-soyo-2                      1/1     Running   0               5h19m   10.0.0.21     soyo-2
kube-system    kube-scheduler-soyo-3                      1/1     Running   0               5h18m   10.0.0.22     soyo-3
kube-system    metrics-server-bf9b6846b-jrckp             1/1     Running   0               5h16m   10.42.1.83    soyo-2
kube-system    reloader-68f95559c6-66q2j                  1/1     Running   0               5h16m   10.42.0.57    soyo-3
kube-system    spegel-2rg5w                               1/1     Running   0               5h17m   10.42.0.156   soyo-3
kube-system    spegel-g8jn4                               1/1     Running   0               5h17m   10.42.1.224   soyo-2
kube-system    spegel-k9jzx                               1/1     Running   0               5h17m   10.42.2.144   soyo-1
network        cloudflare-dns-6f55bfd8c7-lq7sh            1/1     Running   0               5h16m   10.42.2.250   soyo-1
network        cloudflare-tunnel-6ff7596578-zlhmj         1/1     Running   0               5h16m   10.42.0.166   soyo-3
network        envoy-external-664fcd4f5f-swb8s            2/2     Running   0               5h16m   10.42.1.231   soyo-2
network        envoy-external-664fcd4f5f-v4m68            2/2     Running   0               5h16m   10.42.2.199   soyo-1
network        envoy-gateway-7cb4b596c7-h8fpc             1/1     Running   0               5h16m   10.42.2.42    soyo-1
network        envoy-internal-59bb76fb78-76d7h            2/2     Running   0               5h16m   10.42.0.23    soyo-3
network        envoy-internal-59bb76fb78-hxn9n            2/2     Running   0               5h16m   10.42.1.4     soyo-2
network        k8s-gateway-77fcbdbcb7-gn8zc               1/1     Running   0               5h16m   10.42.0.73    soyo-3
```

## Services by Namespace

| Namespace | Service Count | Notable Endpoints |
| --- | --- | --- |
| `cert-manager` | 3 | Controller, CA injector, and webhook metrics/webhooks. |
| `default` | 2 | `kubernetes` API VIP and sample `echo` ClusterIP. |
| `flux-system` | 5 | Flux operator, controllers, and Webhook receiver. |
| `kube-system` | 7 | Cilium control plane, CoreDNS, metrics-server, and Spegel registries. |
| `network` | 5 | Cloudflare DNS/tunnel, Envoy LB pairs, and `k8s-gateway`. |

```bash
$ kubectl get svc -A
NAMESPACE      NAME                      TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)
cert-manager   cert-manager              ClusterIP      10.43.25.174    <none>        9402/TCP
cert-manager   cert-manager-cainjector   ClusterIP      10.43.157.9     <none>        9402/TCP
cert-manager   cert-manager-webhook      ClusterIP      10.43.33.74     <none>        443/TCP,9402/TCP
default        echo                      ClusterIP      10.43.66.195    <none>        80/TCP
default        kubernetes                ClusterIP      10.43.0.1       <none>        443/TCP
flux-system    flux-operator             ClusterIP      10.43.157.106   <none>        8080/TCP
flux-system    notification-controller   ClusterIP      10.43.49.254    <none>        80/TCP
flux-system    source-controller         ClusterIP      10.43.211.155   <none>        80/TCP
flux-system    weave-gitops              ClusterIP      10.43.133.226   <none>        9001/TCP
flux-system    webhook-receiver          ClusterIP      10.43.24.132    <none>        80/TCP
kube-system    cilium-agent              ClusterIP      None            <none>        9962/TCP,9964/TCP
kube-system    cilium-operator           ClusterIP      None            <none>        9963/TCP
kube-system    kube-dns                  ClusterIP      10.43.0.10      <none>        53/UDP,53/TCP
kube-system    metrics-server            ClusterIP      10.43.28.150    <none>        443/TCP
kube-system    spegel                    ClusterIP      10.43.220.107   <none>        9090/TCP
kube-system    spegel-bootstrap          ClusterIP      None            <none>        5001/TCP
kube-system    spegel-registry           NodePort       10.43.239.206   <none>        5000:30021/TCP
network        cloudflare-dns            ClusterIP      10.43.127.73    <none>        7979/TCP
network        cloudflare-tunnel         ClusterIP      10.43.28.84     <none>        8080/TCP
network        envoy-external            LoadBalancer   10.43.217.204   10.0.0.28     80/443 TCP + 443/UDP
network        envoy-gateway             ClusterIP      10.43.170.115   <none>        18000-19001/TCP,9443/TCP
network        envoy-internal            LoadBalancer   10.43.172.108   10.0.0.27     80/443 TCP + 443/UDP
network        k8s-gateway               LoadBalancer   10.43.180.240   10.0.0.26     53/UDP
```

> Repeat these commands whenever diagnosing runtime issues so Backstage TechDocs stays synchronized with the actual Talos cluster state.

## Verification Steps

1. `kubectl get pods -A -o wide` to capture scheduling, IPs, and node placement (mirrors the pod table above).
2. `kubectl get svc -A` to verify LoadBalancer VIPs (`10.0.0.26-28`), ClusterIPs, and node ports match the networking + DNS diagrams on the index page.
3. Cross-check `network` namespace services with the Protectli port map to ensure Envoy/K8s Gateway VIPs are reachable on the flat LAN.
4. If anything drifts, update manifests in `kubernetes/apps/*` first, let Flux reconcile, then re-run these commands and refresh this document.
