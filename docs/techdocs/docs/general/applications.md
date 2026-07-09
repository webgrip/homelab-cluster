# Applications — canonical inventory

Everything this repo deploys with an HTTP entrypoint, plus the non-HTTP LoadBalancers and what
is deliberately *not* routed. Regenerated from repo truth 2026-07-02
(`grep -rln 'kind: HTTPRoute' kubernetes/` + app-template `route:` values).

Hostnames follow `<app>.${SECRET_DOMAIN}` (`cluster-secrets`, SOPS-encrypted). Gateways:
**envoy-internal** = LAN-only (`10.0.0.27`); **envoy-external** = public via Cloudflare Tunnel
(`10.0.0.28`).

## Routed via envoy-internal (LAN-only)

| App / UI | Namespace | Hostname | Notes |
| --- | --- | --- | --- |
| Authentik | `authentik` | `authentik.${SECRET_DOMAIN}` | Cluster IdP (SSO/OIDC); CNPG DB |
| Backstage | `backstage` | `backstage.${SECRET_DOMAIN}` | Portal + TechDocs; CNPG DB |
| Excalidraw | `excalidraw` | `excalidraw.${SECRET_DOMAIN}` | Whiteboard |
| Weave GitOps UI | `flux-system` | `gitops.${SECRET_DOMAIN}` | Flux reconciliation/drift UI |
| gitea-mirror | `forgejo` | `gitea-mirror.${SECRET_DOMAIN}` | GitHub→Forgejo mirror manager |
| FreshRSS | `freshrss` | `freshrss.${SECRET_DOMAIN}` | RSS reader; CNPG DB |
| Harbor | `harbor` | `harbor.${SECRET_DOMAIN}` | Private OCI registry; CNPG DB |
| Policy Reporter | `kyverno` | `policy-reporter.${SECRET_DOMAIN}` | Kyverno PolicyReport UI |
| Longhorn UI | `longhorn-system` | `longhorn.${SECRET_DOMAIN}` | Storage dashboard |
| n8n | `n8n` | `n8n.${SECRET_DOMAIN}` | Workflow automation; CNPG DB |
| Alloy gateway (OTLP) | `observability` | `otlp.${SECRET_DOMAIN}` | OTLP ingest for off-cluster clients |
| Grafana | `observability` | `grafana.${SECRET_DOMAIN}` | Dashboards/alerting; CNPG DB |
| k8s MCP | `observability` | `k8s-mcp.${SECRET_DOMAIN}` | Read-only Kubernetes MCP server |
| Grafana MCP | `observability` | `mcp-grafana.${SECRET_DOMAIN}` | Grafana MCP server |
| OpenCost MCP | `observability` | `opencost-mcp.${SECRET_DOMAIN}` | Cost-query MCP server |
| VMSingle ("Prometheus") | `observability` | `prometheus.${SECRET_DOMAIN}` | VictoriaMetrics TSDB/query UI |
| VMAlertmanager | `observability` | `alertmanager.${SECRET_DOMAIN}` | Alert routing UI |
| SearXNG | `searxng` | `searxng.${SECRET_DOMAIN}` | Meta-search + Valkey cache |
| Dependency-Track | `security` | `dependency-track.${SECRET_DOMAIN}` | SBOM/CVE portfolio; CNPG DB |
| GUAC | `security` | `guac.${SECRET_DOMAIN}` | Supply-chain graph; CNPG DB |
| OpenBao | `security` | `openbao.${SECRET_DOMAIN}` | Secrets backend (ESO source) |
| SparkyFitness | `sparkyfitness` | `sparkyfitness.${SECRET_DOMAIN}` | Fitness tracker; CNPG DB |
| Vikunja | `vikunja` | `vikunja.${SECRET_DOMAIN}` | Task management (ADR-0040); CNPG DB; Authentik OIDC |

## Routed via envoy-external (public, via Cloudflare Tunnel)

| App / UI | Namespace | Hostname | Notes |
| --- | --- | --- | --- |
| Echo (test) | `default` | `echo.${SECRET_DOMAIN}` | Ingress/DNS validation target |
| Flux webhook receiver | `flux-system` | `flux-webhook.${SECRET_DOMAIN}` | Forge webhooks → reconcile |
| Forgejo | `forgejo` | `forgejo.${SECRET_DOMAIN}` | Self-hosted forge; CNPG DB |
| Invoice Ninja | `invoiceninja` | `invoice.${SECRET_DOMAIN}` | Invoicing; MariaDB StatefulSet |
| Renovate webhook | `renovate` | `renovate-webhook.${SECRET_DOMAIN}` | renovate-operator webhook |
| Twitch EventSub | `observability` | `twitch-eventsub.${SECRET_DOMAIN}` | twitch-exporter callback |

## Non-HTTP LoadBalancers (Cilium LB-IPAM)

| Service | Namespace | IP | Ports |
| --- | --- | --- | --- |
| `k8s-gateway` (split DNS) | `network` | `10.0.0.26` | 53/udp |
| `envoy-internal` | `network` | `10.0.0.27` | 443 |
| `envoy-external` | `network` | `10.0.0.28` | 443 |
| zomboid (**disabled**) | `zomboid` | `10.0.0.29` | UDP 16261-2, 8766-7; TCP 27015 |
| minecraft | `minecraft` | `10.0.0.30` | game TCP/UDP |
| forgejo-ssh | `forgejo` | `10.0.0.31` | 22 (git SSH) |

Garage S3 (CNPG/Loki/Harbor object storage) is **off-cluster** at `10.0.0.110:3900`.

## Not routed (no HTTPRoute, by design)

- **Operators / controllers:** cert-manager, cloudnative-pg, external-secrets, trust-manager,
  kyverno engine, keda, kepler, vm-operator, grafana-operator, trivy-operator, renovate-operator,
  arc-systems, sloth, alloy-agent, blackbox/node/kube-state exporters, loki, devex.
- **CNPG databases** (`*-db` Clusters in app namespaces) — reached via `*-rw` Services only.
- **kube-system / network internals:** Cilium, CoreDNS, metrics-server, reloader, spegel,
  cloudflare-tunnel, cloudflare-dns.

## Disabled / suspended apps

| App | State | Why / gate |
| --- | --- | --- |
| zomboid | commented out of `kubernetes/apps/kustomization.yaml` | pending its last SOPS→ESO secret migration — see [Zomboid](zomboid.md) |
| drawio | commented out of `kubernetes/apps/kustomization.yaml` | not needed; frees ~1Gi on fringe (manifests retained) |
| tempo, pyroscope, beyla, k6 | suspended in `observability` | see [Observability](observability.md) |

## Verifying against the live cluster

```bash
kubectl get httproute -A                      # every routed hostname + gateway
kubectl get gateway -n network                # envoy-internal / envoy-external state
kubectl -n network get svc envoy-internal envoy-external k8s-gateway -o wide
kubectl get svc -A | grep LoadBalancer        # LB IP assignments
kubectl get pods -A -o wide                   # what is actually running
```

Wiring checks: `k8s-gateway` answers `*.${SECRET_DOMAIN}` on `10.0.0.26:53/udp`; both gateways
reference the `${SECRET_DOMAIN/./-}-production-tls` certificate in `network`.

To add or change an app, see [Adding applications](adding-applications.md) (pointer to the
`add-app` skill).
