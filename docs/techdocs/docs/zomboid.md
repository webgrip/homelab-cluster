````markdown
# Project Zomboid Dedicated Server

This cluster runs the Project Zomboid dedicated server as a Flux-managed HelmRelease using the `bjw-s/app-template` chart.

## Why Zomboid is different (UDP)

Most apps in this repo are published over HTTP(S) via:

Cloudflare (public) → Cloudflare Tunnel (`cloudflared`) → Envoy Gateway (Gateway API) → `HTTPRoute` → Service.

Project Zomboid is primarily **UDP** (game + Steam ports). That traffic does **not** go through the HTTP Gateway/Tunnel path.
To expose Zomboid to the internet, traffic must reach your network first (typically by port-forwarding on OPNsense), then be delivered to the in-cluster LoadBalancer Service.

## Kubernetes manifests

- App definition: [kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml](../../kubernetes/apps/zomboid/zomboid/app/helmrelease.yaml)
- PVC: [kubernetes/apps/zomboid/zomboid/app/pvc.yaml](../../kubernetes/apps/zomboid/zomboid/app/pvc.yaml)

The Service is type `LoadBalancer` and is pinned to a fixed LAN IP via Cilium LB IPAM:

- `10.0.0.29`

### Ports

The server exposes:

- UDP `16261-16262` (game)
- UDP `8766-8767` (Steam)
- TCP `27015` (RCON, optional)

If you run into join/slot issues, consider expanding the forwarded port range (e.g. UDP `16261-16272`) on both OPNsense and the Kubernetes Service.

## Required Secret (SOPS)

The workload consumes a Secret named `zomboid-secrets` in the `zomboid` namespace via `envFrom`.

### Required keys

- `ADMINPASSWORD` (required on first start)

### Recommended keys

- `ADMINUSERNAME`
- `PASSWORD` (server join password)
- `RCONPASSWORD`

### Template

Use the template file below and encrypt it with SOPS before applying it:

- [kubernetes/apps/zomboid/zomboid/app/secret.template.yaml](../../kubernetes/apps/zomboid/zomboid/app/secret.template.yaml)

Suggested workflow:

1. Copy the template to a new file named `secret.sops.yaml`.
2. Replace the placeholder values.
3. Encrypt with SOPS and commit the encrypted file.
4. Add `secret.sops.yaml` to the app kustomization resources.

## Internet exposure (OPNsense + DNS)

### DNS chain

Public DNS is configured as:

- `zomboid.yonnurs.stream` → CNAME → `zomboid.webgrip.stream`
- `zomboid.webgrip.stream` → A → `143.179.177.49`

Important: ensure these records are **DNS only** (not proxied) in Cloudflare. Zomboid uses UDP and will not work through the normal Cloudflare HTTP proxy.

### OPNsense NAT port forwards

Create port-forwards on WAN to the in-cluster LoadBalancer IP `10.0.0.29`:

- UDP `16261-16262` → `10.0.0.29` UDP `16261-16262`
- UDP `8766-8767` → `10.0.0.29` UDP `8766-8767`
- TCP `27015` → `10.0.0.29` TCP `27015` (optional; RCON)

Apply changes and confirm OPNsense also created corresponding WAN firewall allow rules.

### Testing

- Test from outside the LAN (phone hotspot) to avoid NAT reflection confusion.
- Confirm the Service has the expected external IP:
  - `kubectl -n zomboid get svc`

````
