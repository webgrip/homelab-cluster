# Forgejo

Self-hosted Git service (issues, PRs, wiki, packages, LFS, Actions) deployed via the
official Forgejo Helm chart and reconciled by Flux.

- **Manifests:** `kubernetes/apps/forgejo/`
- **Chart:** `oci://code.forgejo.org/forgejo-helm/forgejo` (pinned tag + digest in `app/ocirepository.yaml`)
- **Web (public):** `https://forgejo.${SECRET_DOMAIN}` via `envoy-external` (10.0.0.28, Cloudflare Tunnel)
- **Git SSH:** `forgejo-ssh.${SECRET_DOMAIN}` → Cilium LoadBalancer `10.0.0.11`, port 22 on the
  LAN; the same name reaches the same daemon off-LAN through the Cloudflare Tunnel
  ([ADR-0054](../adr/adr-0054-forgejo-ssh-off-lan-cloudflare-tunnel.md))
- **Database:** CloudNativePG cluster `forgejo-db` (Postgres), backed up to Garage S3
- **SSO:** Authentik OIDC (auto-provisions users; local `gitea_admin` is break-glass)

## Architecture

| Concern | Choice |
| --- | --- |
| Web ingress | `HTTPRoute` → `envoy-external` `https` listener (public via Cloudflare Tunnel) |
| Git SSH (LAN) | Chart `service.ssh` as `LoadBalancer` on `10.0.0.11` (rootless sshd on 2222, exposed as 22) |
| Git SSH (off-LAN) | Same Service via a `ssh://` rule on the Cloudflare Tunnel, gated by Cloudflare Access |
| Database | CNPG `forgejo-db`; credentials injected from the operator-managed `forgejo-db-app` Secret |
| Sessions | Stored in Postgres (`session.PROVIDER=db`) — survive pod restarts, no Redis needed |
| Cache / queue | In-process `memory` + `level` (on the data PVC) — fine for a single replica |
| Repo / LFS / packages | Longhorn RWO PVC `forgejo-data` (20Gi) mounted at `/data` |
| Metrics | `/metrics` + `ServiceMonitor` (the legacy `release: kube-prometheus-stack` label is vestigial and no longer required; VM scrapes all CRs) |

Forgejo is **not** HA-capable: `replicaCount` stays at 1 with a `Recreate` strategy.

## Secrets (ESO)

All Forgejo secrets are **ExternalSecrets** in `kubernetes/apps/forgejo/forgejo/app/` — no SOPS:

- `forgejo-admin-secret.externalsecret.yaml` — local admin (`username`/`password`/`email`),
  the break-glass identity.
- `forgejo-oidc-secret.externalsecret.yaml` — Authentik client credentials (`key`/`secret`),
  minted via the `34-oidc-forgejo` blueprint, stored in OpenBao.
- `forgejo-s3-secret.externalsecret.yaml` — S3 credentials.

To change or re-seed one, use the `external-secrets` skill. Until the Secrets sync, the Forgejo
pod sits in `CreateContainerConfigError` (it mounts them via `gitea.admin.existingSecret` and
`gitea.oauth[].existingSecret`) — expected on a fresh install while OpenBao populates.

### OIDC redirect URI

The Authentik provider's redirect URI must match the Forgejo auth source named
`authentik`: `https://forgejo.${SECRET_DOMAIN}/user/oauth2/authentik/callback`
(already set in the blueprint). Users are auto-registered on first SSO login
(`oauth2_client.ENABLE_AUTO_REGISTRATION=true`, `ACCOUNT_LINKING=auto`); the local
signup form is hidden (`ALLOW_ONLY_EXTERNAL_REGISTRATION=true`).

## Git over SSH

Clone URLs render as `git@forgejo-ssh.${SECRET_DOMAIN}:owner/repo.git`. There is **one**
SSH endpoint, one host key and one set of remotes; only the transport differs by where you
are sitting.

| Where you are | How the name resolves | Path to the daemon |
| --- | --- | --- |
| On the LAN, or on the WireGuard VPN | k8s-gateway (`10.0.0.26`) is authoritative for the zone and answers the Service's LoadBalancer IP | Direct TCP to `10.0.0.11:22` |
| Anywhere else | Public Cloudflare DNS answers a proxied CNAME to the tunnel | `cloudflared` → Cloudflare edge → tunnel → `forgejo-ssh.forgejo.svc:22` |

The `forgejo` namespace is explicitly allow-listed for LoadBalancer Services in the kyverno
`network-exposure-enforce` policy. The off-LAN path needed no NetworkPolicy change:
`forgejo-allow-ingress` already admits the `network` namespace (where cloudflared runs) on all
ports.

### Pushing from off the LAN, without the VPN

Rationale and trade-offs: [ADR-0054](../adr/adr-0054-forgejo-ssh-off-lan-cloudflare-tunnel.md).
Each off-LAN machine needs two things — `cloudflared`, and an SSH config block.

!!! warning "Your SSH key is the only gate"
    `forgejo-ssh.${SECRET_DOMAIN}` is reachable from the public internet. Forgejo's sshd accepts
    **publickey auth only**, for one forced-command `git` user, which is the same posture GitHub
    and Codeberg run — but it does mean every key on a Forgejo account now works from anywhere,
    not just from the LAN. Remove keys you stop using, and treat a lost laptop as urgent.

```bash
brew install cloudflared        # or: https://github.com/cloudflare/cloudflared/releases
```

```ssh-config
# ~/.ssh/config
#
# On the LAN (or the VPN) 10.0.0.11:22 answers, so take the direct path: `ProxyCommand none`
# wins because ssh keeps the FIRST value it obtains for a keyword. Off-LAN the probe fails,
# this block does not apply, and the tunnel block below takes over.
Match host forgejo-ssh.<your-domain> exec "nc -z -G1 -w1 10.0.0.11 22 2>/dev/null"
  ProxyCommand none

Host forgejo-ssh.<your-domain>
  User git
  ProxyCommand cloudflared access ssh --hostname %h
```

Remotes stay exactly as they are (`ssh://git@forgejo-ssh.<your-domain>/owner/repo.git`), and so
does your `known_hosts` entry — it is the same sshd either way.

There is no login flow and no token: `cloudflared` here is a plain TCP proxy over Cloudflare's
edge, and authentication is the SSH key exchange at the far end, exactly as on the LAN. That also
makes the off-LAN path safe for headless use (CI outside the cluster, an agent runner on a
laptop) with no extra credential.

In-cluster consumers are untouched by all of this — Flux reconciles over
`forgejo-http.forgejo.svc.cluster.local:3000`, and the runners clone over the same in-cluster
HTTP.

### Symptom → cause

| Symptom | Cause |
| --- | --- |
| `ssh: connect to host ... port 22: Operation timed out` off-LAN | No `ProxyCommand` — the ssh config block is missing on this machine |
| `ProxyCommand ... cloudflared: command not found` | `cloudflared` not installed on this machine |
| `websocket: bad handshake`, or the proxy exits immediately | The public CNAME is missing or unproxied — a `cfargotunnel.com` target only resolves through Cloudflare's edge |
| Off-LAN works but LAN pushes got slow | The `Match ... exec` probe is failing — check `nc -z -G1 -w1 10.0.0.11 22` by hand (drop the `2>/dev/null` to see why); LAN traffic is hairpinning through Cloudflare |
| `kex_exchange_identification: ... connection reset` | The tunnel's wildcard rule is matching first — the `ssh://` rule must stay **above** `*.${SECRET_DOMAIN}` in `cloudflare-tunnel/app/helmrelease.yaml` |

## Observability

- **Metrics:** `/metrics` is enabled and scraped via the chart `ServiceMonitor`
  (`up{job="forgejo-http"}`). The DB is scraped by the shared CNPG PodMonitor; the
  `forgejo-db` Cluster carries `monitoring.webgrip.io/enabled: "true"`.
- **Dashboards:** `Forgejo / Runtime Health`
  (`observability/grafana/app/dashboards/infra-forgejo.yaml`) + `infra-forgejo-ci.yaml`.
- **Alerts:** `app/prometheusrule.yaml` (`ForgejoDown`, `ForgejoDeploymentUnavailable`,
  `ForgejoPodRestarting`).

## Operations

- **Backups / restore:** standard CNPG flow — see [CNPG backups & restore](../runbooks/cnpg-backups.md). `forgejo-db` has a dedicated 5Gi
  `walStorage`; the daily `ScheduledBackup` runs at 02:30. The restore-drill CronJob is
  shipped but `suspend: true` by default.
- **Upgrades:** Renovate bumps the chart tag/digest in `app/ocirepository.yaml`; the
  Forgejo app version tracks the chart `appVersion`.
- **Stale-branch / zombie-PR cleanup is automated:** the weekly `scheduled-maintenance`
  workflow (`.forgejo/workflows/scheduled-maintenance.yml`, Mondays 06:00 UTC) closes PRs
  whose head is already contained in the base and prunes fully-merged branches (never
  `main`/`renovate/*`; mass-delete fuse at 15). Manual run: Actions → scheduled-maintenance →
  Run workflow (`dry-run` defaults to `true`). Contract + branch protection:
  [ADR-0050](../adr/adr-0050-per-repo-delivery-contract.md) and the
  [branch-protection rollout runbook](../runbooks/forgejo-branch-protection-rollout.md).
- **OIDC login failures:** see the [Authentik runbook](../runbooks/authentik-oidc-login.md)
  — almost always pod DNS, credentials, or redirect URI (in that order).
- **Recovering a stalled HelmRelease:** imperative `flux reconcile --force` is blocked
  by the GitOps-only guardrail. If the HelmRelease is `Stalled`/`RetriesExceeded` (e.g.
  it failed before a referenced Secret existed), make a **spec change to bump the
  generation** (a `spec.maxHistory` tweak works) and commit — helm-controller resets the
  failure count and re-attempts. Adding the missing Secret alone does not un-stall it.

## Actions runner (CI)

Forgejo Actions is enabled server-side and the runner is **deployed and proven on a real job**
(2026-06-18): a KEDA `ScaledJob` of ephemeral `forgejo-runner one-job` pods with a privileged
Docker-in-Docker sidecar (host-mode, `runs-on: docker`), a **warm pool** (`minReplicaCount` +
`one-job --wait`), and a provisioner-minted runner identity. The privileged sidecar needs **two**
admission gates opened on this namespace — a Kyverno `PolicyException` **and**
`pod-security.kubernetes.io/enforce: privileged` (a plain kyverno hardening exception is not
enough). Full architecture, scaling knobs, and the runtime troubleshooting table:
[Forgejo runner runbook](../runbooks/forgejo-runner.md); the destination (rootless BuildKit, drop
the privilege) is [ADR-0026](../adr/adr-0026-rootless-ci-image-builds.md).

**Repo authority.** `webgrip/infrastructure` is de-mirrored and **Forgejo-authoritative** (done)
so its in-cluster CI can cut releases — a read-only pull-mirror can't be pushed to, which blocks
`semantic-release`. See [ADR-0013](../adr/adr-0013-forgejo-leading-application-repos.md) and the
`forgejo-leading` skill for cutting over further repos.

## Follow-ups (not yet deployed)

- **Outgoing email** — `mailer` is disabled; wire SMTP to enable notifications.
