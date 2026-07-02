# Forgejo Actions Runner (KEDA)

The in-cluster CI runner: a KEDA **ScaledJob** that turns "jobs pending in Forgejo" into
ephemeral `forgejo-runner one-job` pods, each with a privileged Docker-in-Docker sidecar for
image builds. This is **Topology A, host-mode** from [ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md)
— proven on a real job 2026-06-18.

- **Manifests:** `kubernetes/apps/forgejo/forgejo-runner/`
- **Scaler:** KEDA `ScaledJob/forgejo-runner` (namespace `forgejo`), trigger type `forgejo-runner`
  against `forgejo-http.forgejo.svc.cluster.local:3000`, `global: "true"`, `labels: docker`
- **Nodes:** `nodeSelector node.webgrip.io/pool: worker` (the `dedicated=fringe` taint was retired
  2026-06-19; the toleration stays, dormant). In practice pods land on `fringe-workstation` (8c/~15Gi).
- **Label:** advertises exactly one honest label — `docker` (host-mode). Workflows `runs-on: docker`.

## How it scales

```
pollingInterval: 15        # scaler asks Forgejo "how many `docker` jobs are pending?" every 15s
minReplicaCount: 2         # WARM POOL: always keep N runners blocked on `one-job --wait`
maxReplicaCount: 6         # burst ceiling
# NO activeDeadlineSeconds: the warm pool intentionally blocks on `one-job --wait`; a k8s deadline
# would kill idle waiters as DeadlineExceeded (false KubeJobFailed churn). Job runtime is capped by
# Forgejo's per-job timeout (config.yaml `timeout: 1h`). failedJobsHistoryLimit: 0 (don't retain).
```

- **Warm pool.** `minReplicaCount: N` keeps N runner Jobs running permanently. Each runs
  `forgejo-runner one-job **--wait**`, which *blocks until Forgejo assigns a task* — so a warm
  pod sits ready and grabs the next job with no cold-start. Without `--wait`, a warm pod (started
  with no pending job) would exit immediately and KEDA would hot-loop respawning it. `--wait` is a
  no-op for burst pods (their task is already pending).
- **Burst.** When pending jobs exceed the warm pool, KEDA creates more Jobs up to
  `maxReplicaCount`. As each warm runner takes a job and exits, KEDA backfills to maintain the floor.
- **Capacity bound.** Each pod reserves ~**500m CPU / ~1.0Gi** by *requests* (runner 250m/512Mi +
  dind 250m/512Mi); neither container sets a CPU limit, so a lone build bursts into the idle node
  (observed ~1 core). The worker pool is `fringe-workstation` (8c/~15Gi) + `worker-1` (4c) — the
  warm pool + burst fit comfortably. Keep the dind memory *limit* modest (currently 1.5Gi): an
  oversized limit inflates node memory pressure and leaves warm pods `Pending: Insufficient memory`.

## The runner identity (registration)

The `one-job` command consumes a **static, reused** runner identity — `--uuid` + `--token-url`
read from Secret `forgejo-runner-secret` (keys `uuid`, `token`). All pods share that one
registration (the KEDA Forgejo pattern; it is registered **non-ephemeral** so Forgejo doesn't
delete it after one job).

That identity is **minted, not hand-seeded**, by `forgejo-runner-provisioner` (a Tier-1 idempotent
Job, [ADR-0019](../adr/adr-0019-bootstrap-task-pattern.md), mirroring `forgejo-ci-provisioner`):

- It registers **one persistent global runner** via `POST /api/v1/admin/actions/runners`
  (`{name: keda-global-docker, ephemeral: false}`) using the admin Secret, and writes the
  server-issued `uuid` + `token` into `forgejo-runner-secret`.
- **Idempotent:** no-ops when the stored `uuid` is already a well-formed 36-char UUID; otherwise it
  drops any same-named stale runner and re-registers.
- The Job **owns** the Secret (there is no ESO ExternalSecret for it). `forgejo-runner-secret` was
  previously seeded from the retired SOPS secret, whose `uuid` was a malformed 16-hex string — that
  is what the provisioner replaced.
- `force: true` on the app's Flux Kustomization recreates the immutable Job on spec change so it
  re-runs.

> The **scaler** token (`forgejo-runner-scaler-token`, the API token KEDA uses to *read* pending
> jobs) is separate and stays OpenBao-backed via ESO. Only the *registration* secret is
> provisioner-owned.

## The two privileged gates

The `dind` sidecar is `privileged: true`. `forgejo` is an application namespace, so **two
independent admission layers** must be opened — opening one without the other still blocks the
runner (each only surfaces once the prior is cleared):

1. **Kyverno** `pod-security-baseline-enforce` denies the **Job** (`autogen-privileged-containers`).
   Fix: PolicyException `exception-forgejo-runner` (in `security` ns) waiving *only*
   `privileged-containers` + `autogen-privileged-containers` for the runner Job
   (`scaledjob.keda.sh/name=forgejo-runner`) and Pod (`app.kubernetes.io/name=forgejo-runner`).
2. **Built-in Pod Security Admission** denies the **Pod** (`violates PodSecurity baseline:latest`).
   PSA is namespace-scoped (no per-pod exemption), and `namespace-tenancy-audit`'s `+()` mutate
   defaults app namespaces to `enforce: baseline`. Fix: pin
   `pod-security.kubernetes.io/enforce: privileged` on the `forgejo` namespace (mirrors the
   `security` ns). Kyverno's baseline policy + the runner-only exception remain the real gate for
   every other pod in the namespace.

## Troubleshooting

Every one of these passed `kubeconform`/`flux-local` and only failed at runtime.

| Symptom | Cause | Fix |
|---|---|---|
| Scaler `Active`, `triggersActivity.isActive: true`, but **no runner pod**; KEDA log: `admission webhook "validate.kyverno.svc-fail" denied ... autogen-privileged-containers` | Kyverno blocks the privileged **Job** at admission | Ensure `exception-forgejo-runner` PolicyException exists (gate 1 above) |
| Job exists but pods never appear; `kubectl get events -n forgejo` shows `FailedCreate ... violates PodSecurity "baseline:latest": privileged` | Built-in **PSA** blocks the **Pod** | Set `pod-security.kubernetes.io/enforce: privileged` on the `forgejo` namespace (gate 2 above) |
| Runner pod reaches `Error`; `kubectl logs <pod> -c runner` → `invalid configuration: malformed uuid "<16hex>": invalid UUID length: 16` | `forgejo-runner-secret.uuid` is not a real runner UUID | Run/inspect `forgejo-runner-provisioner`; the stored `uuid` must be 36 chars. (`kubectl -n forgejo get secret forgejo-runner-secret -o jsonpath='{.data.uuid}' \| base64 -d` and check length) |
| Job log: `Cannot find: node in PATH`; JS actions (`actions/checkout`, `tj-actions/changed-files`) fail | host-mode steps run in the toolchain container where `node` is bundled under `externals/` but not on `PATH` | The runner `args` prepend `/home/runner/externals/node20/bin` to `PATH` (node20 = `checkout@v4` runtime; node24 also bundled) |
| Warm pod stuck `Pending`; event: `FailedScheduling ... Insufficient memory` | the single `fringe` node can't fit another runner | lower `minReplicaCount`, free/add `fringe` memory, or trim the dind/runner memory requests (the last over-commits — watch for OOM) |
| KEDA `keda-operator` restart count climbing | RAM-pressure OOM on tight nodes (a recurring cluster theme) | check `kubectl -n keda get pods`; correlate with node memory |

Two **workflow-side** failures that look like runner bugs but live in the repo's `.forgejo/`:

| Symptom | Cause | Fix |
|---|---|---|
| `failed to read action 'X', no files found after reading paths: action.yml, action.yaml, Dockerfile` | a job uses a local `uses: ./...` action **without checking out the repo first** (the workspace is empty until `actions/checkout`) | add an `actions/checkout@v5` step before the local-action step (each ephemeral job runs in a fresh pod, so every job that uses a local action must check out) |
| semantic-release: `remote: mirror repository is read-only` (HTTP 403) on `git push` | the Forgejo repo is a **read-only pull-mirror**; semantic-release must push a tag | make the repo authoritative — see [ADR-0024](../adr/adr-0024-forgejo-leading-application-repos.md) |

## Operations

```sh
# Status
kubectl -n forgejo get scaledjob forgejo-runner -o jsonpath='{.status.triggersActivity}{"\n"}'
kubectl -n forgejo get pods -l app.kubernetes.io/name=forgejo-runner
kubectl -n keda logs deploy/keda-operator --tail=40 | grep -E 'Scaling Jobs|Created jobs|Failed to create'

# Change the warm-pool size: edit minReplicaCount in
#   kubernetes/apps/forgejo/forgejo-runner/app/scaledjob.yaml  (validate + commit; Flux reconciles)

# Force a re-registration (e.g. the runner was deleted in Forgejo): clear the stored uuid so the
# provisioner re-mints on its next run, then nudge the app. GitOps-friendly — no imperative apply:
#   - delete the runner under Forgejo → Site Admin → Actions → Runners
#   - then bump the provisioner Job spec (it has force:true) so Flux recreates + re-runs it
```

> Imperative `kubectl delete job` on a KEDA-generated runner is blocked by the cluster's
> GitOps-only guardrails (and unnecessary — KEDA backfills). Drive everything through manifests.

The privileged DinD is deliberate but interim ([ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md) Topology C is the endgame — see roadmap).
