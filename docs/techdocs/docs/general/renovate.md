# Renovate

This repository uses Renovate to continuously open pull requests for dependency updates across the GitOps manifests and supporting automation.

The “why” is simple: versions drift constantly (container tags, Helm charts, Flux artifacts, GitHub Actions, and ad-hoc version pins). Renovate is the automation layer that turns that drift into reviewed, reproducible PRs.

This documentation describes how Renovate is actually implemented here end-to-end: GitOps wiring, runtime jobs, config layering, repo conventions, observability, and troubleshooting.

## What Renovate updates in this repo

Renovate is configured (globally and per-repo) to look for updates in several ways:

1. Kubernetes GitOps YAML

   - Flux resources, Kustomizations, HelmRelease values, Helmfile usage, and image tags referenced in the `kubernetes/` tree.
2. GitHub Actions

   - Workflow dependencies under `.github/workflows/` (actions versions, pinned digests).
3. Annotated version pins (“regex managers”)

   - Files that contain `# renovate:` annotations (for example [talos/talenv.yaml](../../../../talos/talenv.yaml)).

In practice, most PRs you’ll see for this repo come from:

- Flux/Kustomize/Helm-related changes in `kubernetes/**`
- Container image updates referenced by those manifests
- GitHub Action updates

## How Renovate runs (GitOps + in-cluster execution)

Renovate runs inside the cluster via `renovate-operator` and is installed/configured through Flux.

### GitOps wiring

Entry point:

- [kubernetes/apps/renovate/kustomization.yaml](../../../../kubernetes/apps/renovate/kustomization.yaml)

Key details:

- Namespace: [kubernetes/apps/renovate/namespace.yaml](../../../../kubernetes/apps/renovate/namespace.yaml)
  - `kustomize.toolkit.fluxcd.io/prune: disabled` is set on the namespace.
- Flux applies two Kustomizations:
  - [kubernetes/apps/renovate/renovate-operator/ks.yaml](../../../../kubernetes/apps/renovate/renovate-operator/ks.yaml) (operator install)
  - [kubernetes/apps/renovate/renovate-operator/ks-jobs.yaml](../../../../kubernetes/apps/renovate/renovate-operator/ks-jobs.yaml) (job/config/secrets)
  - The jobs Kustomization depends on the operator Kustomization.

Both Kustomizations use `postBuild.substituteFrom` to substitute `${SECRET_DOMAIN}` and other cluster variables from `cluster-secrets`.

### renovate-operator install

Operator manifests:

- [kubernetes/apps/renovate/renovate-operator/app/ocirepository.yaml](../../../../kubernetes/apps/renovate/renovate-operator/app/ocirepository.yaml)
- [kubernetes/apps/renovate/renovate-operator/app/helmrelease.yaml](../../../../kubernetes/apps/renovate/renovate-operator/app/helmrelease.yaml)

Notable HelmRelease settings:

- Metrics enabled with a ServiceMonitor (`values.metrics.enabled: true` + `serviceMonitor.enabled: true`).
- Webhook enabled with an external route host `renovate-webhook.${SECRET_DOMAIN}` via the Gateway API parent `envoy-external`.

### RenovateJob execution model — dual-run (GitHub + Forgejo)

Two RenovateJobs run side by side ([ADR-0029](../adr/adr-0029-dual-run-renovate-forgejo.md) dual-run;
[RFC: Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md)):

| RenovateJob | Platform | Scope | Schedule |
| --- | --- | --- | --- |
| [`webgrip-gitops`](../../../../kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml) | GitHub | `webgrip/*` | `17 */6 * * *` |
| [`webgrip-forgejo`](../../../../kubernetes/apps/renovate/renovate-operator/jobs/webgrip-forgejo.yaml) | Forgejo (in-cluster endpoint `forgejo-http.forgejo.svc:3000/api/v1`) | explicit list of Forgejo-authoritative repos (+ pilot) — grows as repos flip Forgejo-leading; no `webgrip/*` glob because pull-mirrors are read-only | `47 */6 * * *` (offset to avoid overlap) |

Shared mechanics (both jobs):

- One repository at a time (`parallelism: 1`), non-root, `RENOVATE_BASE_DIR=/tmp`.
- `RENOVATE_CONFIG_FILE=/config/renovate.json` mounted from a per-platform ConfigMap
  (`configmap-gitops.yaml` / `configmap-forgejo.yaml`).
- Webhook authentication from Secret `renovate-webhook-auth`.

**Migration status:** the Forgejo path is live; the **GitHub path retires only at the Flux-source
cutover** (`homelab-cluster` flips last — gated on [ADR-0011](../adr/adr-0011-flux-source-forgejo.md)).
At that point `webgrip-gitops`, its ConfigMap, and the GitHub-App token CronJob get deleted.

Operational implication:

- “I checked a Dependency Dashboard checkbox, why no PR?” is usually answered by:
  - waiting for the next scheduled run, and/or
  - Dependency Dashboard or release-age gating in repo config (see next section).

## Renovate configuration: layering, precedence, and the two places to edit

Renovate behavior for this repo is the result of **two** config files:

1. RenovateJob admin/runtime config

   - [kubernetes/apps/renovate/renovate-operator/jobs/configmap-gitops.yaml](../../../../kubernetes/apps/renovate/renovate-operator/jobs/configmap-gitops.yaml)
2. Repo-specific Renovate configuration

   - [.renovaterc.json5](../../../../.renovaterc.json5)

When changing behavior, decide first whether you want:

- a runtime/admin change for the in-cluster Renovate executor (edit the ConfigMap), or
- a change *only for this repo* (edit `.renovaterc.json5`).

Do not move self-hosted/admin-only settings such as `allowedCommands`, GitHub API throttling `hostRules`, executor identity, `enabledManagers`, or `RENOVATE_CONFIG_FILE` wiring into `.renovaterc.json5`. Renovate ignores self-hosted settings in repository config and some of them are intentionally protected from repo-controlled changes.

### Runtime/admin config (ConfigMap) highlights

The admin config is stored as JSON in a ConfigMap and mounted into the Renovate executor container.

Important behaviors in the current admin config:

- Managers enabled are intentionally scoped to this GitOps estate: `flux`, `kustomize`, `kubernetes`, `helm-values`, `helmfile`, `custom.regex`, `github-actions`, `mise`, `dockerfile`, and `docker-compose`.
- Post-upgrade commands are allow-listed here. Currently only `./scripts/update-oci-digests.sh` is allowed because the Renovate executor does not have a Docker daemon for tests such as Kyverno CLI.
- GitHub and Docker Hub API throttling is configured here.
- Queue limits are configured here. Repository package rules use `prPriority` to decide which updates consume the limited slots first.
- The admin config owns manager enablement, post-upgrade command allowlisting, Git author identity, and runtime safety defaults.
- `autodiscover: false` is set in Renovate config. Discovery is handled by the RenovateJob/operator layer, and each execution should only handle the intended repository.

### Repo config (.renovaterc.json5) highlights

The repo config is where “house style” lives.

Key behaviors in the current repo config:

- The repo extends the shared Webgrip default preset and the Webgrip GitOps preset.
- Shared preset references are pinned to an immutable commit SHA. This is safer than an unprotected mutable tag; switching to tags should only happen after `webgrip/renovate-config` protects release tags.
- Kubernetes and Talos versions are centralized in `talos/talenv.yaml`; Renovate does not currently expose a generic Kubernetes-version constraint filter for Helm/chart compatibility in repo config, so compatibility gates stay as explicit package rules where needed.
- The repo defines ignore paths, release-age gates, dependency grouping, PR priority, semantic commit scopes, labels, and PR body notes.
- GitHub Actions and Mise patch updates can branch-automerge after a 1-day soak and successful checks; minor updates are opened as PRs so the AI dependency review can gate auto-merge.
- GitOps changes under `kubernetes/apps/*` are regrouped by nearest package directory using Renovate templating instead of one rule per namespace.
- Reused dependencies that span many apps, such as `ghcr.io/bjw-s-labs/helm/app-template`, are carved back out into shared PRs to avoid one dependency generating many near-identical namespace PRs.
- Cluster-critical namespaces require Dependency Dashboard approval for minor updates and a longer release-age soak before PR creation.

Annotated dependency pins are the mechanism used for values that aren’t otherwise discoverable by a native manager. Example:

- [talos/talenv.yaml](../../../../talos/talenv.yaml) uses annotations to keep `talosVersion` and `kubernetesVersion` current.

Important note about `ignorePaths`:

- Ignore paths are repo-owned in `.renovaterc.json5`. The admin ConfigMap should not carry repo-specific ignore paths.
- If a dependency appears “ignored” or “unexpectedly updated”, inspect `.renovaterc.json5` and verify what Renovate reports in logs/Dependency Dashboard.

## Pull request behavior (grouping, approvals, automerge)

This repo uses Renovate to keep PR noise manageable:

- Global defaults still provide coarse grouping by manager/datasource.
- Repo-level packageRules then split `kubernetes/apps/*` updates by nearest package directory, so app/component areas get separate PRs instead of one repo-wide GitOps batch.
- A small set of shared cross-namespace dependencies can override that split later in the rule order and stay repo-wide when that produces cleaner PRs.
- Major updates are gated by the Dependency Dashboard approval checkbox and a release-age soak.
- Minor updates for cluster-critical namespaces are also dashboard-gated.

Automerge behavior is defined in both places:

- Global config enables automerge for some patch updates.
- Repo config enables automerge for specific patch/digest-only manager updates and enforces semantic commits/labels.
- Minor Renovate PRs are eligible for GitHub auto-merge only after the relayed AI review is `Green Low risk`, recommends `Merge` or `Merge after checks`, and lists no improvement opportunities, special pre-merge checks, or follow-up work.

If a PR isn’t opening when you expect it to, check these in order:

1. Is there actually an update available?
2. Did the run execute successfully?
3. Is it blocked by `minimumReleaseAge` / pending release-age checks?
4. Is it blocked by Dependency Dashboard approval (major updates, or minor updates in cluster-critical namespaces)?
5. Is it blocked by GitHub permissions/branch protections?

## GitHub repo conventions used with Renovate

This repository has Renovate-specific labels and PR hygiene conventions.

### Labels

Label definitions:

- [.github/labels.yaml](../../../../.github/labels.yaml)

Relevant labels include:

- `area/renovate`
- `renovate/container`, `renovate/helm`, `renovate/github-action`, `renovate/github-release`, `renovate/grafana-dashboard`

### Auto-labeling and label syncing

- Labeler rules: [.github/labeler.yaml](../../../../.github/labeler.yaml)
  - Changes to `.renovaterc.json5` are categorized as `area/renovate`.
- Workflow that applies labeler: [.github/workflows/labeler.yaml](../../../../.github/workflows/labeler.yaml)
- Workflow that syncs labels into GitHub: [.github/workflows/label-sync.yaml](../../../../.github/workflows/label-sync.yaml)

### Release notes

Release/changelog config excludes Renovate as an author:

- [.github/release.yaml](../../../../.github/release.yaml)

## Observability (dashboards and alerts)

Renovate-operator exposes metrics and this repo ships both a Grafana dashboard and Prometheus alert rules.

### Grafana dashboard

- Dashboard ConfigMap: [kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml](../../../../kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml)

### Prometheus alert rules

- PrometheusRule: [kubernetes/apps/observability/victoria-metrics/app/rules/prometheusrule-platform-renovate-operator.yaml](../../../../kubernetes/apps/observability/victoria-metrics/app/rules/prometheusrule-platform-renovate-operator.yaml)

Alerts include:

- `RenovateOperatorDeploymentUnavailable`
- `RenovateProjectRunFailed`
- `RenovateProjectDependencyIssues`

Each alert annotation points to the Renovate section in the runbooks page:

- Runbooks index: [docs/techdocs/docs/runbooks.md](../runbooks/index.md)
- Renovate runbook: [docs/techdocs/docs/runbooks/renovate.md](../runbooks/renovate.md)

## Secrets and credentials (ESO)

Renovate secrets are **ExternalSecrets** (OpenBao-backed, no SOPS), in
`kubernetes/apps/renovate/renovate-operator/jobs/`:

- `renovate-secrets.externalsecret.yaml` — GitHub App credentials (+ optional Docker Hub
  `RENOVATE_DOCKERHUB_USERNAME`/`RENOVATE_DOCKERHUB_TOKEN` to reduce registry throttling).
- `renovate-webhook-auth.externalsecret.yaml` — webhook auth token.
- `renovate-forgejo-token` — minted in-cluster by the Forgejo provisioner Job
  (`renovate-operator/forgejo-provisioner/`), not human-typed.

To change or re-seed one, use the `external-secrets` skill.

### Runtime token minting

Renovate itself uses a runtime token secret created/updated in-cluster.

- CronJob: [kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml](../../../../kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml)
- RBAC: [kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.rbac.yaml](../../../../kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.rbac.yaml)

Mechanics (as implemented):

- The CronJob mints a GitHub App installation token every 30 minutes.
- It applies a Secret `renovate-runtime-token` in namespace `renovate` containing `token`, `RENOVATE_TOKEN`, and `RENOVATE_HOST_RULES`.
- `RENOVATE_HOST_RULES` always authenticates GHCR with the GitHub App token and can also authenticate Docker Hub when `renovate-secrets` includes `RENOVATE_DOCKERHUB_USERNAME` and `RENOVATE_DOCKERHUB_TOKEN`.

## Vulnerability sources

This setup uses two vulnerability sources:

- GitHub vulnerability alerts via `vulnerabilityAlerts.enabled: true`
- OSV via the experimental `osvVulnerabilityAlerts: true`

Operational notes:

- OSV coverage applies to direct dependencies only.
- The Dependency Dashboard uses `dependencyDashboardOSVVulnerabilitySummary: "unresolved"`, which keeps unresolved OSV findings visible without dumping every fixable item into the dashboard.
- Because OSV support is still marked experimental upstream, expect some behavior and coverage to evolve across Renovate releases.

## Maintenance jobs (cleanup)

To avoid accumulating executor Jobs forever, there is a cleanup CronJob:

- [kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml](../../../../kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml)

It deletes completed Renovate executor Jobs older than 3 days.

## Troubleshooting (practical runbook)

### Step 1: Confirm Flux applied the manifests

```sh
flux get kustomizations -A | grep renovate
flux get helmreleases -A | grep renovate
```

### Step 2: Operator health

```sh
kubectl -n renovate get deploy,pods
kubectl -n renovate logs deploy/renovate-operator --tail=200
```

### Step 3: RenovateJob and executor jobs

```sh
kubectl -n renovate get renovatejobs
kubectl -n renovate describe renovatejob webgrip-gitops
kubectl -n renovate get jobs --sort-by=.metadata.creationTimestamp | tail
kubectl -n renovate get pods --sort-by=.metadata.creationTimestamp | tail -20
kubectl -n renovate logs job/<k8s-job-name> --all-containers --tail=200
```

### Step 4: Interpret the most common failures

1. No PRs, but the Dependency Dashboard is updating

   - Often release-age gating or Dependency Dashboard approval gating.
2. Run fails with registry/auth errors

    - GHCR 403 when reading a private package: GitHub App needs **Packages: read** and correct installation scope.
    - Docker Hub 429/rate limit: configure `RENOVATE_DOCKERHUB_USERNAME` and `RENOVATE_DOCKERHUB_TOKEN` in Secret `renovate-secrets`, then wait for CronJob `renovate-github-app-token` to refresh `renovate-runtime-token`. The global Renovate config also throttles Docker Hub requests and reduces branch/repository parallelism to lower burst traffic.
3. Renovate executes but doesn’t “see” expected files

   - Check `ignorePaths` interaction between global ConfigMap and repo config.
   - Check the regex manager patterns if using `# renovate:` annotations.

## Notes on repo badges and GitHub Actions

Renovate runs in-cluster via `renovate-operator`, not via a GitHub Actions workflow.

The root README uses a static “Renovate in cluster” badge and links here for details.
