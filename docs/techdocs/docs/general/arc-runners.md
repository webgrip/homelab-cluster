# ARC Runners

GitHub Actions runners are managed by ARC in `kubernetes/apps/arc-systems`.

The cluster exposes two runner pools:

| Pool | Scale set name | Node placement | Labels | Use for |
| --- | --- | --- | --- | --- |
| Normal (SOYO) | `arc-runner-set` | `nodegroup: soyo` | `arc-runner-set`, `arc`, `homelab`, `normal` | linting, unit tests, small validation jobs, non-privileged automation |
| Heavy (Fringe) | `arc-runner-set-heavy` | `nodegroup: fringe` | `arc-runner-set-heavy`, `arc`, `homelab`, `fringe`, `heavy`, `dind` | Docker image builds, Buildx, multi-arch builds, heavier integration jobs |

`arc-runner-set` is the default scale set name. Existing jobs targeting `arc-runner-set` land on the normal/SOYO pool. Heavy jobs must explicitly target `arc-runner-set-heavy`.

## Workflow labels

Normal jobs use the normal pool (SOYO):

```yaml
runs-on: [self-hosted, arc-runner-set]
# or with explicit pool label:
runs-on: [self-hosted, arc-runner-set, normal]
```

Docker image builds and other heavy jobs use the heavy pool (fringe):

```yaml
runs-on: [self-hosted, arc-runner-set-heavy]
# or with capability labels for clarity:
runs-on: [self-hosted, arc-runner-set-heavy, heavy, dind]
```

Avoid using literal hostnames such as `fringe-workstation` in workflow labels. Prefer capability labels like `heavy` and `dind` so future heavy runner nodes can be added without changing every workflow again.

## Routing rules

- Normal/light jobs: use `arc-runner-set` (the default).
- Docker-in-Docker/heavy jobs: use `arc-runner-set-heavy`.
- Add `normal` or `heavy`/`dind` labels for documentation and clarity.
- Avoid jobs that only specify `[self-hosted]` without a scale set name.

## Docker build cache

Prefer registry-backed BuildKit cache for heavy image builds:

```yaml
with:
  cache-from: type=registry,ref=ghcr.io/<owner>/<image>:buildcache
  cache-to: type=registry,ref=ghcr.io/<owner>/<image>:buildcache,mode=max
```

This keeps ARC runners ephemeral and avoids coupling cache performance to a Longhorn volume or a single node-local filesystem.
