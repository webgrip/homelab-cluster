# ADR-0008: Rootless CI image builds (drop privileged Docker-in-Docker)

> Status: **Proposed** · Date: 2026-06-12 · Part of [RFC: Security Hardening](../rfc/rfc-security-hardening.md) · Amended 2026-06-18 (see Status log)

## Context

The Forgejo CI runner (`kubernetes/apps/forgejo/forgejo-runner/`, a KEDA `ScaledJob` pinned to the
worker pool — `node.webgrip.io/pool: worker`, [ADR-0025](adr-0025-node-taxonomy.md)) builds images
through a **privileged Docker-in-Docker sidecar** (`docker:dind`,
`securityContext.privileged: true`). A privileged container shares the host kernel with full
capabilities, and CI runs untrusted-ish code by definition — the cluster's **only** privileged
workload sits in the one place that executes arbitrary repo code. The runner itself is proven on
real jobs (see Status log); what remains is removing the privilege from how it builds.

"Runner + sidecar" hides **three** distinct responsibilities; conflating them is what produced the
`localhost:2376` networking confusion:

| Role | What it does | Must have | Must NOT have |
| --- | --- | --- | --- |
| **Agent** | `forgejo-runner one-job`: claims a job, orchestrates steps | the forgejo-runner binary, git | privilege; secrets |
| **Toolchain / job env** | where the workflow's steps actually run | node, git, `docker`/`buildx` (or `buildctl`), `cosign`, `syft`; **the Harbor robot cred, the Forgejo OIDC token, the DT key, the checkout** | privilege |
| **Build engine** | actually assembles the image (`dockerd` → `buildkitd`) | the build engine + the layer/cache storage | **any credential; any source code** |

The rule that falls out: **privilege and secrets never share a container.** The elevated component
(the build engine) holds no credentials and no source; the credential-bearing component (the
toolchain) holds no privilege. Today's DinD already gets this half-right — the privileged daemon is
not the container holding the Harbor token. The end-state removes privilege entirely.

## Decision

Two moves, **sequenced** — prove the runner before hardening how it builds:

1. **Prove the runner on topology A, host-mode** *(done 2026-06-18 — see Status log)*: the agent
   runs inside the toolchain image (`github-runner`: docker CLI + buildx), the `dockerd` sidecar
   shares the pod netns (`DOCKER_HOST=tcp://localhost:2376` just works), an init container injects
   the static `forgejo-runner` binary, and a narrow Kyverno exception covers the one privileged
   sidecar.
2. **Then converge on topology C.** A long-lived **rootless `buildkitd`** (`rootlesskit` +
   `--oci-worker-no-process-sandbox`) reached as a Service, with a registry cache to Harbor; point
   `docker buildx` at a `--driver remote`/`kubernetes` builder; drop `privileged: true`; narrow or
   remove the `forgejo` hardening exceptions. Kaniko/buildah stay fallbacks for builds BuildKit
   can't express.

The ScaledJob today still runs topology A — a privileged `docker:dind` sidecar
(`forgejo-runner/app/scaledjob.yaml`). This ADR stays **Proposed** until step 2 exists.

## Alternatives considered

**Topology** — where the build engine lives:

| | **A — Privileged DinD sidecar** | **B — Rootless BuildKit sidecar** | **C — Shared rootless BuildKit service** |
| --- | --- | --- | --- |
| Shape | agent + **privileged** `dockerd` sidecar, per pod | agent + **rootless** `buildkitd` sidecar, per pod | slim runners + **one long-lived** rootless `buildkitd` Deployment |
| Privilege | `privileged: true` (the only one in CI) | user-ns, no `privileged` | user-ns, no `privileged` |
| Build cache | cold every job (ephemeral) | cold every job | **warm** — PVC + Harbor registry cache |
| Engine reach | `localhost:2376` (shared pod netns) | `localhost` socket | a **Service** (DNS) — no netns coupling |
| Node prereq | none | userns/seccomp/apparmor on the node | same, but on **one** Deployment, not every runner |
| Precedent | Forgejo official k8s example; ARC DinD mode | ADR-0008's literal wording | GitLab / CERN / Buildkite buildkit-as-a-service |
| Verdict | **prove the runner here, then leave** | awkward middle | **target end-state** |

Topology B pays the rootless tax (node config, fuse-overlayfs rough edges) while keeping the
cold-cache penalty — a fallback only. ARC's no-privileged "Kubernetes mode" is rejected outright:
it has no container runtime, so it cannot build images at all.

**Engine technology** (orthogonal to topology):

- **Keep DinD, sandbox the node** (gVisor / Kata runtime class) — strong isolation, but a new
  runtime to operate and slower builds.
- **Sysbox** — lets DinD run unprivileged, but another node-level component on Talos, which
  favors a minimal immutable host.
- **Kaniko only** — daemonless, but stumbles on some multi-stage/cache patterns and is effectively
  in maintenance mode; fallback, not default.
- **Keep privileged DinD** — an unbounded privileged escape surface in the exact component that
  runs repo-controlled code is the worst place to keep one.

## Consequences

- Removes the only privileged container in CI; a compromised build can no longer trivially escape
  to the node.
- Build invocations change (`docker build` → `buildctl`/`docker buildx` against rootless
  `buildkitd`, or a Kaniko step), absorbed by the
  [Forge migration](../blogs/2026-06-12-bringing-the-forge-home.md) workflow rewrites; builds
  needing genuinely privileged features (loop devices, some `RUN --mount` flavors) may need a
  narrow exception.
- Registry-backed BuildKit cache to Harbor still works — rootless BuildKit has first-class cache
  export.
- The Kyverno/PSA hardening exceptions on the `forgejo` namespace can be narrowed or removed, and
  the engine becomes a Service reached by DNS — retiring the job/sidecar netns coupling and the
  `localhost:2376` foot-gun.

## Status log

- 2026-06-12 — Proposed; the ScaledJob carried an explicit `NOTE` to validate the `one-job`
  invocation end-to-end before any hardening.
- 2026-06-18 — Step 1 done: the runner is **proven on real jobs** — it registered, scheduled, and
  ran `webgrip/infrastructure` workflows end to end on topology A (privileged DinD, host-mode),
  after clearing four sequential gates: a Kyverno PolicyException waiving only
  `privileged-containers`, a `pod-security.kubernetes.io/enforce: privileged` pin on the `forgejo`
  namespace, an idempotent `forgejo-runner-provisioner` minting a real runner identity (the stored
  `uuid` was malformed), and prepending the toolchain's `externals/node20/bin` to `PATH`. A warm
  pool (`minReplicaCount` + `one-job --wait`) was added. Operations + the full failure table:
  [Forgejo runner runbook](../runbooks/forgejo-runner.md).
- 2026-07-02 — Still topology A in production; step 2 (rootless topology C) not started.
