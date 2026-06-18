# ADR-0008: Rootless CI image builds (drop privileged Docker-in-Docker)

> Status: **Proposed** · Date: 2026-06-12 · Part of [RFC: Security Hardening](../rfc/rfc-security-hardening.md)

## Context

The new Forgejo CI runner (`kubernetes/apps/forgejo/forgejo-runner/`, a KEDA `ScaledJob`) builds
container images using a **privileged Docker-in-Docker sidecar** — `docker:dind` with
`securityContext.privileged: true` — on the dedicated `fringe` nodes. A privileged container shares
the host kernel with full capabilities; a malicious or compromised build (and CI runs untrusted-ish
code by definition) has a wide path to node escape. It is, today, the **only** privileged container
in the cluster's normal workload set, and it sits in the one place that executes arbitrary repo
code. The runner is also **not yet proven on a real job** — the ScaledJob carries an explicit
`NOTE` to validate the `one-job` invocation end-to-end first.

## The three roles (what runs where)

"Runner + sidecar" hides **three** distinct responsibilities; conflating them is what produced the
`localhost:2376` networking confusion and the "which image needs what" churn. Keep them separate:

| Role | What it does | Must have | Must NOT have |
|---|---|---|---|
| **Agent** | `forgejo-runner one-job`: claims a job, orchestrates steps | the forgejo-runner binary, git | privilege; secrets |
| **Toolchain / job env** | where the workflow's steps actually run | node, git, `docker`/`buildx` (or `buildctl`), `cosign`, `syft`; **the Harbor robot cred, the Forgejo OIDC token, the DT key, the checkout** | privilege |
| **Build engine** | actually assembles the image (`dockerd` → `buildkitd`) | the build engine + the layer/cache storage | **any credential; any source code** |

The rule that falls out: **privilege and secrets never share a container.** The elevated component
(the build engine) holds no credentials and no source; the credential-bearing component (the
toolchain) holds no privilege. Today's DinD already gets this half-right — the privileged daemon is
not the container holding the Harbor token. The end-state removes privilege entirely.

## Topology alternatives

Three ways to place the build engine, in increasing order of fit with the cluster's rootless /
PSS-baseline posture. (The *engine technology* — BuildKit vs Kaniko vs buildah — is orthogonal and
covered under "Engine alternatives" below.)

| | **A — Privileged DinD sidecar** | **B — Rootless BuildKit sidecar** | **C — Shared rootless BuildKit service** |
|---|---|---|---|
| Shape | agent + **privileged** `dockerd` sidecar, per pod | agent + **rootless** `buildkitd` sidecar, per pod | slim runners + **one long-lived** rootless `buildkitd` Deployment |
| Privilege | `privileged: true` (the only one in CI) | user-ns, no `privileged` | user-ns, no `privileged` |
| Build cache | cold every job (ephemeral) | cold every job | **warm** — PVC + Harbor registry cache |
| Engine reach | `localhost:2376` (shared pod netns) | `localhost` socket | a **Service** (DNS) — no netns coupling |
| Node prereq | none | userns/seccomp/apparmor on the node | same, but on **one** Deployment, not every runner |
| Precedent | Forgejo official k8s example; ARC DinD mode | ADR-0008's literal wording | GitLab / CERN / Buildkite buildkit-as-a-service |
| Verdict | **prove the runner here, then leave** | awkward middle | **target end-state** |

ARC's no-privileged "**Kubernetes mode**" is rejected outright: it spawns job pods via the k8s API
and has **no container runtime**, so it cannot build Dockerfiles/OCI images at all — a non-starter
for a pipeline whose whole job is building images.

## Decision

*(Proposed.)* Two moves, **sequenced** — prove the runner before hardening how it builds:

1. **Now — prove the runner on a real job with topology A, run host-mode.** The agent runs *inside*
   the toolchain image (`github-runner`, which carries the docker CLI + buildx plugin), so steps
   share the pod netns with the `dockerd` sidecar and `DOCKER_HOST=tcp://localhost:2376` just works.
   The toolchain image lacks `forgejo-runner`, so an init container copies the static binary in — no
   bespoke image rebuild needed to prove the runner. Carry the existing narrow Kyverno exception for
   the one privileged sidecar. This is the "validate `one-job` end-to-end" the ScaledJob's `NOTE`
   demands, at minimum risk.
2. **Then — converge on topology C.** A long-lived **rootless `buildkitd`** (`rootlesskit` +
   `--oci-worker-no-process-sandbox`) reached as a Service, with a **registry cache to Harbor**;
   point the Harbor reusable's `docker buildx` at the `--driver remote`/`kubernetes` builder; drop
   `privileged: true` from the runner; **narrow or remove** the `forgejo` Kyverno hardening
   exception. Kaniko/buildah remain fallbacks for builds BuildKit can't express.

Topology B (rootless sidecar) is **not** the destination — it pays the rootless tax (node config,
fuse-overlayfs rough edges) while keeping the cold-cache penalty; treat it only as a fallback if a
shared builder proves unworkable.

## Consequences

- Removes the only privileged container in CI; a compromised build can no longer trivially escape to
  the `fringe` node.
- Workflows change their build invocation: `docker build` → `buildctl`/`docker buildx` against a
  rootless `buildkitd`, or a Kaniko executor step. The Forgejo Actions workflow rewrites
  (see the [Forge migration](../blogs/2026-06-12-bringing-the-forge-home.md)) absorb this.
- A small set of builds that genuinely need privileged features (loop devices, some `RUN --mount`
  flavors, nested containers) may need adjustment or an explicit, narrowly-scoped exception.
- Registry-backed BuildKit cache (to Harbor, once it lands) still works — arguably better, since
  rootless BuildKit has first-class cache export.
- The kyverno hardening-exception for the `forgejo` namespace can be **narrowed or removed** once no
  privileged container remains.
- Step 1 (host-mode) needs `forgejo-runner` present in the toolchain container; it is injected by an
  init container that copies the static binary out of the pinned `forgejo/runner` image, so proving
  the runner requires **no** new image build.
- Topology C also retires a whole class of bugs: the engine becomes a Service reached by DNS, so the
  job/sidecar network-namespace coupling — and the `localhost:2376` foot-gun — disappears.

## Engine alternatives considered (orthogonal to topology)

- **Keep DinD, sandbox the node** with **gVisor** or **Kata Containers** runtime for the runner
  pods — strong isolation, but a new runtime class to operate and a performance hit on builds.
- **Sysbox** runtime — lets DinD run unprivileged, but it's another node-level component to install
  and maintain on Talos (which favors a minimal, immutable host).
- **Kaniko only** — no daemon, unprivileged, but it stumbles on some multi-stage/cache patterns and
  is effectively in maintenance mode. Fine as a fallback, not the default.
- **Keep privileged DinD** — simplest, status quo. Rejected: an unbounded privileged escape surface
  in the exact component that runs repo-controlled code is the worst place to keep one.
