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

## Config

Non-sensitive environment variables are provided via the `zomboid-config` ConfigMap.

- Applied config: [kubernetes/apps/zomboid/zomboid/app/configmap.yaml](kubernetes/apps/zomboid/zomboid/app/configmap.yaml)
- Template (not applied): [kubernetes/apps/zomboid/zomboid/app/configmap.template.yaml](kubernetes/apps/zomboid/zomboid/app/configmap.template.yaml)

Keep passwords and credentials in the Secret only (not the ConfigMap).

Note: `zomboid-config` contains placeholder keys for sensitive variables so the full set of supported env vars is visible in one place, but the real values should still come from `zomboid-secrets` (the Secret is loaded after the ConfigMap and overrides it).

### Template

Use the template file below and encrypt it with SOPS before applying it:

- [kubernetes/apps/zomboid/zomboid/app/secret.template.yaml](kubernetes/apps/zomboid/zomboid/app/secret.template.yaml)

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

### OPNsense outbound NAT (Static Port) — common UDP fix

If clients outside your LAN get **"The server failed to respond"** even though the WAN port-forwards are correct, you may need to preserve source ports for UDP replies.

In OPNsense:

1. Go to **Firewall → NAT → Outbound**.
2. Switch mode to **Hybrid** (keeps automatic rules + lets you add overrides).
3. Add an outbound NAT rule:
  - Interface: `WAN`
  - Protocol: `UDP`
  - Source: `10.0.0.29/32`
  - Destination: `any`
  - Translation / target: `Interface address`
  - **Static-port: enabled**
4. Apply, then re-test from a mobile network.

This is a common requirement for UDP-heavy game/Steam traffic; without it, return traffic can be source-port rewritten in ways some clients/servers don’t tolerate.

### Testing

- Test from outside the LAN (phone hotspot) to avoid NAT reflection confusion.
- Confirm the Service has the expected external IP:
  - `kubectl -n zomboid get svc`

If it still fails, do packet captures on OPNsense:

- **WAN capture**: Protocol `udp`, Port `16261` while attempting a join. You should see inbound packets to your WAN IP.
- **LAN/VLAN capture** (the interface that can see `10.0.0.0/24`): Host `10.0.0.29`, Protocol `udp`, Port `16261`. You should see the forwarded packets.

If packets hit WAN but never appear on the LAN capture, the port-forward/rules aren’t matching. If they appear on LAN but you never see replies on WAN, outbound NAT/static-port or routing is the next suspect.

## Storage notes

Persisting `/home/steam/Zomboid` is required for saves/config.

Do not mount a PVC over `/home/steam/pz-dedicated` itself: this image ships scripts (including `start-server.sh`) under that path and a full mount will mask them, causing startup failures. If you want to cache workshop downloads, persist only `/home/steam/pz-dedicated/steamapps/workshop`.
