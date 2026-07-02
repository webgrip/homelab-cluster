# Forgejo

Self-hosted Git service (issues, PRs, wiki, packages, LFS, Actions) deployed via the
official Forgejo Helm chart and reconciled by Flux.

- **Manifests:** `kubernetes/apps/forgejo/`
- **Chart:** `oci://code.forgejo.org/forgejo-helm/forgejo` (pinned tag + digest in `app/ocirepository.yaml`)
- **Web (public):** `https://forgejo.${SECRET_DOMAIN}` via `envoy-external` (10.0.0.28, Cloudflare Tunnel)
- **Git SSH (LAN):** `forgejo-ssh.${SECRET_DOMAIN}` → Cilium LoadBalancer `10.0.0.31`, port 22
- **Database:** CloudNativePG cluster `forgejo-db` (Postgres), backed up to Garage S3
- **SSO:** Authentik OIDC (auto-provisions users; local `gitea_admin` is break-glass)

## Architecture

| Concern | Choice |
| --- | --- |
| Web ingress | `HTTPRoute` → `envoy-external` `https` listener (public via Cloudflare Tunnel) |
| Git SSH | Chart `service.ssh` as `LoadBalancer` on `10.0.0.31` (rootless sshd on 2222, exposed as 22) |
| Database | CNPG `forgejo-db`; credentials injected from the operator-managed `forgejo-db-app` Secret |
| Sessions | Stored in Postgres (`session.PROVIDER=db`) — survive pod restarts, no Redis needed |
| Cache / queue | In-process `memory` + `level` (on the data PVC) — fine for a single replica |
| Repo / LFS / packages | Longhorn RWO PVC `forgejo-data` (20Gi) mounted at `/data` |
| Metrics | `/metrics` + `ServiceMonitor` labelled `release: kube-prometheus-stack` (vestigial label the labels policy still requires; a no-op for the VM operator) |

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

Clone URLs render as `git@forgejo-ssh.${SECRET_DOMAIN}:owner/repo.git`. The hostname
resolves to `10.0.0.31` (Cilium L2-announced LoadBalancer) for LAN clients using the
cluster DNS (`10.0.0.26`). The `forgejo` namespace is explicitly allow-listed for
LoadBalancer Services in the kyverno `network-exposure-enforce` policy.

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
the privilege) is [ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md).

**Repo authority.** `webgrip/infrastructure` is de-mirrored and **Forgejo-authoritative** (done)
so its in-cluster CI can cut releases — a read-only pull-mirror can't be pushed to, which blocks
`semantic-release`. See [ADR-0024](../adr/adr-0024-forgejo-leading-application-repos.md) and the
`forgejo-leading` skill for cutting over further repos.

## Follow-ups (not yet deployed)

- **Outgoing email** — `mailer` is disabled; wire SMTP to enable notifications.
