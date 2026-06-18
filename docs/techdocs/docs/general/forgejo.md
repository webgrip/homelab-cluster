# Forgejo

Self-hosted Git service (issues, PRs, wiki, packages, LFS, Actions) deployed via the
official Forgejo Helm chart and reconciled by Flux.

- **Manifests:** `kubernetes/apps/forgejo/`
- **Chart:** `oci://code.forgejo.org/forgejo-helm/forgejo` (pinned tag + digest in `app/ocirepository.yaml`)
- **Web (LAN):** `https://forgejo.${SECRET_DOMAIN}` via `envoy-internal` (10.0.0.27)
- **Git SSH (LAN):** `forgejo-ssh.${SECRET_DOMAIN}` → Cilium LoadBalancer `10.0.0.31`, port 22
- **Database:** CloudNativePG cluster `forgejo-db` (Postgres), backed up to Garage S3
- **SSO:** Authentik OIDC (auto-provisions users; local `gitea_admin` is break-glass)

## Architecture

| Concern | Choice |
| --- | --- |
| Web ingress | `HTTPRoute` → `envoy-internal` `https` listener (LAN only) |
| Git SSH | Chart `service.ssh` as `LoadBalancer` on `10.0.0.31` (rootless sshd on 2222, exposed as 22) |
| Database | CNPG `forgejo-db`; credentials injected from the operator-managed `forgejo-db-app` Secret |
| Sessions | Stored in Postgres (`session.PROVIDER=db`) — survive pod restarts, no Redis needed |
| Cache / queue | In-process `memory` + `level` (on the data PVC) — fine for a single replica |
| Repo / LFS / packages | Longhorn RWO PVC `forgejo-data` (20Gi) mounted at `/data` |
| Metrics | `/metrics` + `ServiceMonitor` labelled `release: kube-prometheus-stack` |

Forgejo is **not** HA-capable: `replicaCount` stays at 1 with a `Recreate` strategy.

## First-time bring-up

Forgejo needs two SOPS-encrypted Secrets that a human must create (the repo never
commits plaintext secrets). Templates live next to the app:

1. **Admin Secret** (`forgejo-admin-secret`, keys `username`/`password`/`email`):

   ```bash
   cd kubernetes/apps/forgejo/forgejo/app
   cp forgejo-admin-secret.template.yaml forgejo-admin-secret.sops.yaml
   # edit the password, then encrypt:
   sops --encrypt --in-place forgejo-admin-secret.sops.yaml
   ```

2. **OIDC Secret** (`forgejo-oidc-secret`, keys `key`/`secret`): wait for the Authentik
   blueprint (`authentik/app/blueprints/34-oidc-forgejo.yaml`) to reconcile (~10 min),
   then read the generated **Client ID** and **Client Secret** from the Authentik
   "Forgejo OIDC" provider (Admin → Applications → Providers):

   ```bash
   cp forgejo-oidc-secret.template.yaml forgejo-oidc-secret.sops.yaml
   # paste key (client id) + secret (client secret), then encrypt:
   sops --encrypt --in-place forgejo-oidc-secret.sops.yaml
   ```

3. **Enable them**: uncomment both `*.sops.yaml` entries in
   `kubernetes/apps/forgejo/forgejo/app/kustomization.yaml`, then validate & commit:

   ```bash
   ./scripts/run-flux-local-test.sh
   git -c commit.gpgsign=false commit -am "feat(forgejo): enable admin + oidc secrets"
   ```

Until both Secrets exist the Forgejo pod stays in `CreateContainerConfigError`
(it mounts them via `gitea.admin.existingSecret` and `gitea.oauth[].existingSecret`).
This is expected for a fresh install.

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
- **Dashboard:** `Forgejo` (uid `forgejo`) under the **Apps** folder
  (`observability/grafana/app/dashboards/forgejo.yaml`).
- **Alerts:** `app/prometheusrule.yaml` (`ForgejoDown`, `ForgejoDeploymentUnavailable`,
  `ForgejoPodRestarting`), labelled `release: kube-prometheus-stack`.

## Operations

- **Backups / restore:** standard CNPG flow — see [Backups](../runbooks/cnpg-backups.md) and the
  [Restore Playbook](../runbooks/cnpg-restore-playbook.md). `forgejo-db` has a dedicated 5Gi
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

## Follow-ups (not yet deployed)

- **Forgejo Actions runner** — Actions is enabled server-side, but no `forgejo-runner`
  is deployed yet. A runner needs a privileged/DinD container and therefore a kyverno
  hardening exception for the `forgejo` namespace.
- **Public exposure** — currently LAN-only. To publish, move the `HTTPRoute` to
  `envoy-external` and add `forgejo` to the external-gateway allow-list in the kyverno
  `network-exposure-enforce` policy.
- **Outgoing email** — `mailer` is disabled; wire SMTP to enable notifications.
