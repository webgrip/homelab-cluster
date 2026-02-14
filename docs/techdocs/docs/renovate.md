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

   - Files that contain `# renovate:` annotations (for example [talos/talenv.yaml](../../talos/talenv.yaml)).

In practice, most PRs you’ll see for this repo come from:

- Flux/Kustomize/Helm-related changes in `kubernetes/**`
- Container image updates referenced by those manifests
- GitHub Action updates

## How Renovate runs (GitOps + in-cluster execution)

Renovate runs inside the cluster via `renovate-operator` and is installed/configured through Flux.

### GitOps wiring

Entry point:

- [kubernetes/apps/renovate/kustomization.yaml](../../kubernetes/apps/renovate/kustomization.yaml)

Key details:

- Namespace: [kubernetes/apps/renovate/namespace.yaml](../../kubernetes/apps/renovate/namespace.yaml)
  - `kustomize.toolkit.fluxcd.io/prune: disabled` is set on the namespace.
- Flux applies two Kustomizations:
  - [kubernetes/apps/renovate/renovate-operator/ks.yaml](../../kubernetes/apps/renovate/renovate-operator/ks.yaml) (operator install)
  - [kubernetes/apps/renovate/renovate-operator/ks-jobs.yaml](../../kubernetes/apps/renovate/renovate-operator/ks-jobs.yaml) (job/config/secrets)
  - The jobs Kustomization depends on the operator Kustomization.

Both Kustomizations use `postBuild.substituteFrom` to substitute `${SECRET_DOMAIN}` and other cluster variables from `cluster-secrets`.

### renovate-operator install

Operator manifests:

- [kubernetes/apps/renovate/renovate-operator/app/ocirepository.yaml](../../kubernetes/apps/renovate/renovate-operator/app/ocirepository.yaml)
- [kubernetes/apps/renovate/renovate-operator/app/helmrelease.yaml](../../kubernetes/apps/renovate/renovate-operator/app/helmrelease.yaml)

Notable HelmRelease settings:

- Metrics enabled with a ServiceMonitor (`values.metrics.enabled: true` + `serviceMonitor.enabled: true`).
- Webhook enabled with an external route host `renovate-webhook.${SECRET_DOMAIN}` via the Gateway API parent `envoy-external`.

### RenovateJob execution model

The main RenovateJob is:

- [kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml](../../kubernetes/apps/renovate/renovate-operator/jobs/webgrip-gitops.yaml)

What it does (as configured):

- Discovers repositories matching `webgrip/*`.
- Runs on cron schedule `0 */2 * * *` (every 2 hours).
- Runs up to 5 repositories in parallel (`parallelism: 5`).
- Uses `RENOVATE_CONFIG_FILE=/config/renovate.json` mounted from a ConfigMap.
- Uses webhook authentication from Secret `renovate-webhook-auth`.

Operational implication:

- “I checked a Dependency Dashboard checkbox, why no PR?” is usually answered by:
  - waiting for the next scheduled run, and/or
  - schedule gating in repo config (see next section).

## Renovate configuration: layering, precedence, and the two places to edit

Renovate behavior for this repo is the result of **two** config files:

1. Cluster-wide Renovate defaults (used by the RenovateJob)

   - [kubernetes/apps/renovate/renovate-operator/jobs/configmap-gitops.yaml](../../kubernetes/apps/renovate/renovate-operator/jobs/configmap-gitops.yaml)
2. Repo-specific Renovate configuration

   - [.renovaterc.json5](../../.renovaterc.json5)

When changing behavior, decide first whether you want:

- a change for *all repos discovered by the job* (edit the ConfigMap), or
- a change *only for this repo* (edit `.renovaterc.json5`).

### Global config (ConfigMap) highlights

The global config is stored as JSON in a ConfigMap and mounted into the Renovate executor container.

Important behaviors in the current global config:

- Managers enabled include: `flux`, `kustomize`, `helm-values`, `helmfile`, `github-actions`, plus many language ecosystems.
- Dependency Dashboard enabled and auto-closing enabled.
- Grouping is defined via `packageRules` (e.g. “GitOps container images”, “Flux controllers & OCI artifacts”, “GitHub Actions”).
- Major updates require Dependency Dashboard approval (`dependencyDashboardApproval: true`).
- It is resilient to flaky registries: `abortOnExternalHostError: false`.
- Schedule defaults to `at any time` and `minimumReleaseAge` defaults to `1 days`.
- `autodiscover: false` is set in Renovate config. Discovery is handled by the RenovateJob/operator layer, and each execution should only handle the intended repository.

Ignore paths are defined globally too (including `bootstrap/**` and `talos/**`).

### Repo config (.renovaterc.json5) highlights

The repo config is where “house style” lives.

Key behaviors in the current repo config:

- Dependency Dashboard enabled and the title is customized.
- Schedule is restricted: `schedule: ["every weekend"]`.
- Semantic commit conventions, commit message formatting, and update-type labeling.
- A GitHub Actions packageRule enables automerge for minor/patch/digest updates (with `minimumReleaseAge: "3 days"`).
- Two custom regex managers are defined to process `# renovate:` annotations.

Annotated dependency pins are the mechanism used for values that aren’t otherwise discoverable by a native manager. Example:

- [talos/talenv.yaml](../../talos/talenv.yaml) uses annotations to keep `talosVersion` and `kubernetesVersion` current.

Important note about `ignorePaths`:

- The global ConfigMap defines an `ignorePaths` list.
- The repo config also defines `ignorePaths`.

Array merge/override behavior can materially change what Renovate scans. If a dependency appears “ignored” or “unexpectedly updated”, inspect both files and verify what Renovate reports in logs/Dependency Dashboard.

## Pull request behavior (grouping, approvals, automerge)

This repo uses Renovate to keep PR noise manageable:

- Grouping is primarily controlled by global `packageRules.groupName` in the ConfigMap.
- Major updates are gated by the Dependency Dashboard approval checkbox.

Automerge behavior is defined in both places:

- Global config enables automerge for some patch updates.
- Repo config enables automerge for specific managers (notably GitHub Actions) and enforces semantic commits/labels.

If a PR isn’t opening when you expect it to, check these in order:

1. Is there actually an update available?
2. Did the run execute successfully?
3. Is it blocked by schedule (`every weekend`)?
4. Is it blocked by Dependency Dashboard approval (major updates)?
5. Is it blocked by GitHub permissions/branch protections?

## GitHub repo conventions used with Renovate

This repository has Renovate-specific labels and PR hygiene conventions.

### Labels

Label definitions:

- [.github/labels.yaml](../../.github/labels.yaml)

Relevant labels include:

- `area/renovate`
- `renovate/container`, `renovate/helm`, `renovate/github-action`, `renovate/github-release`, `renovate/grafana-dashboard`

### Auto-labeling and label syncing

- Labeler rules: [.github/labeler.yaml](../../.github/labeler.yaml)
  - Changes to `.renovaterc.json5` are categorized as `area/renovate`.
- Workflow that applies labeler: [.github/workflows/labeler.yaml](../../.github/workflows/labeler.yaml)
- Workflow that syncs labels into GitHub: [.github/workflows/label-sync.yaml](../../.github/workflows/label-sync.yaml)

### Release notes

Release/changelog config excludes Renovate as an author:

- [.github/release.yaml](../../.github/release.yaml)

## Observability (dashboards and alerts)

Renovate-operator exposes metrics and this repo ships both a Grafana dashboard and Prometheus alert rules.

### Grafana dashboard

- Dashboard ConfigMap: [kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml](../../kubernetes/apps/observability/grafana/app/dashboards/platform-renovate-operator.yaml)

### Prometheus alert rules

- PrometheusRule: [kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml](../../kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-platform-renovate-operator.yaml)

Alerts include:

- `RenovateOperatorDeploymentUnavailable`
- `RenovateProjectRunFailed`
- `RenovateProjectDependencyIssues`

Each alert annotation points to the Renovate section in the runbooks page:

- [docs/techdocs/docs/runbooks.md](runbooks.md)

## Secrets and credentials (SOPS policy)

This repo is GitOps-managed and uses SOPS for secrets.

Renovate-related secrets in this repo:

- GitHub App credentials: [kubernetes/apps/renovate/renovate-operator/jobs/secret.sops.yaml](../../kubernetes/apps/renovate/renovate-operator/jobs/secret.sops.yaml)
- Webhook auth token: [kubernetes/apps/renovate/renovate-operator/jobs/webhook-auth.secret.sops.yaml](../../kubernetes/apps/renovate/renovate-operator/jobs/webhook-auth.secret.sops.yaml)

Human note:

- SOPS-encrypted secrets require human-encryption workflows; never commit plaintext secrets.

### Runtime token minting

Renovate itself uses a runtime token secret created/updated in-cluster.

- CronJob: [kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml](../../kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.cronjob.yaml)
- RBAC: [kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.rbac.yaml](../../kubernetes/apps/renovate/renovate-operator/jobs/github-app-token.rbac.yaml)

Mechanics (as implemented):

- The CronJob mints a GitHub App installation token.
- It applies a Secret `renovate-runtime-token` in namespace `renovate` containing `token` and `RENOVATE_TOKEN`.

## Maintenance jobs (cleanup)

To avoid accumulating executor Jobs forever, there is a cleanup CronJob:

- [kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml](../../kubernetes/apps/renovate/renovate-operator/jobs/job-cleanup.cronjob.yaml)

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

   - Often schedule gating (`every weekend`) or major-approval gating.
2. Run fails with registry/auth errors

   - GHCR 403 when reading a private package: GitHub App needs **Packages: read** and correct installation scope.
   - Docker Hub 429/rate limit: global config is set to not abort the whole run, but some lookups may still fail.
3. Renovate executes but doesn’t “see” expected files

   - Check `ignorePaths` interaction between global ConfigMap and repo config.
   - Check the regex manager patterns if using `# renovate:` annotations.

## Notes on repo badges and GitHub Actions

Renovate runs in-cluster via `renovate-operator`, not via a GitHub Actions workflow.

The root README uses a static “Renovate in cluster” badge and links here for details.
