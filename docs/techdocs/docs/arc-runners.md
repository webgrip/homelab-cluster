# ARC Runners

GitHub Actions runners are managed by ARC in `kubernetes/apps/arc-systems`.

The cluster exposes two runner pools:

| Pool | Node placement | Labels | Use for |
| --- | --- | --- | --- |
| Normal (SOYO) | `nodegroup: soyo` | `arc-runner-set`, `arc`, `homelab`, `normal`, `fringe` | linting, unit tests, small validation jobs, non-privileged automation |
| Heavy (Fringe) | `nodegroup: fringe` | `arc-runner-set`, `arc`, `homelab`, `fringe`, `heavy`, `dind` | Docker image builds, Buildx, multi-arch builds, heavier integration jobs |

`arc-runner-set` is a compatibility label used by existing jobs. Keep it on self-hosted workflows, but add workload labels so GitHub can route jobs to the correct pool.

## Workflow labels

Normal jobs should use the normal pool (SOYO):

```yaml
runs-on: [self-hosted, arc-runner-set, normal]
```

Docker image builds and other heavy jobs should use the heavy pool (fringe):

```yaml
runs-on: [self-hosted, arc-runner-set, heavy, dind]
```

Avoid using literal hostnames such as `fringe-workstation` in workflow labels. Prefer capability labels like `heavy` and `dind` so future heavy runner nodes can be added without changing every workflow again.

## Routing rules

- Every self-hosted job should include `arc-runner-set`.
- Normal jobs should include `normal`.
- Docker-in-Docker jobs must include `heavy` and `dind`.
- Add `fringe` only when the fringe node pool itself matters.
- Avoid jobs that only specify `[self-hosted, arc-runner-set]`; they can land on either pool.

## Docker build cache

Prefer registry-backed BuildKit cache for heavy image builds:

```yaml
with:
  cache-from: type=registry,ref=ghcr.io/<owner>/<image>:buildcache
  cache-to: type=registry,ref=ghcr.io/<owner>/<image>:buildcache,mode=max
```

This keeps ARC runners ephemeral and avoids coupling cache performance to a Longhorn volume or a single node-local filesystem.
