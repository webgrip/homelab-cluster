# ADR-0008: Rootless CI image builds (drop privileged Docker-in-Docker)

> Status: **Proposed** · Date: 2026-06-12 · Part of [RFC: Security Hardening](rfc-security-hardening.md)

## Context

The new Forgejo CI runner (`kubernetes/apps/forgejo/forgejo-runner/`, a KEDA `ScaledJob`) builds
container images using a **privileged Docker-in-Docker sidecar** — `docker:dind` with
`securityContext.privileged: true` — on the dedicated `fringe` nodes. A privileged container shares
the host kernel with full capabilities; a malicious or compromised build (and CI runs untrusted-ish
code by definition) has a wide path to node escape. It is, today, the **only** privileged container
in the cluster's normal workload set, and it sits in the one place that executes arbitrary repo
code. The runner is also **not yet proven on a real job** — the ScaledJob carries an explicit
`NOTE` to validate the `one-job` invocation end-to-end first.

## Decision

*(Proposed.)* Replace privileged DinD with **rootless, daemonless image builds** — **BuildKit
rootless** (`rootlesskit` + `buildkitd --oci-worker-no-process-sandbox`) as the preferred backend,
with Kaniko or buildah as fallbacks for builds BuildKit can't express. Drop `privileged: true` from
the runner entirely. **Sequence this with the first real-job proof of the runner**, not before:
prove the runner works, then harden how it builds — don't destabilize an unproven component.

## Consequences

- Removes the only privileged container in CI; a compromised build can no longer trivially escape to
  the `fringe` node.
- Workflows change their build invocation: `docker build` → `buildctl`/`docker buildx` against a
  rootless `buildkitd`, or a Kaniko executor step. The Forgejo Actions workflow rewrites
  (see the [Forge migration](../../blog/2026-06-12-bringing-the-forge-home.md)) absorb this.
- A small set of builds that genuinely need privileged features (loop devices, some `RUN --mount`
  flavors, nested containers) may need adjustment or an explicit, narrowly-scoped exception.
- Registry-backed BuildKit cache (to Harbor, once it lands) still works — arguably better, since
  rootless BuildKit has first-class cache export.
- The kyverno hardening-exception for the `forgejo` namespace can be **narrowed or removed** once no
  privileged container remains.

## Alternatives considered

- **Keep DinD, sandbox the node** with **gVisor** or **Kata Containers** runtime for the runner
  pods — strong isolation, but a new runtime class to operate and a performance hit on builds.
- **Sysbox** runtime — lets DinD run unprivileged, but it's another node-level component to install
  and maintain on Talos (which favors a minimal, immutable host).
- **Kaniko only** — no daemon, unprivileged, but it stumbles on some multi-stage/cache patterns and
  is effectively in maintenance mode. Fine as a fallback, not the default.
- **Keep privileged DinD** — simplest, status quo. Rejected: an unbounded privileged escape surface
  in the exact component that runs repo-controlled code is the worst place to keep one.
