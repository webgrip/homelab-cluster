pr: 153

## Dependency Update Review

**Verdict:** Yellow Caution
**Recommendation:** Merge after checks
**Confidence:** Medium

### Executive summary

This PR updates one runtime container image from `python:3.13-alpine` to `python:3.14-alpine` and pins it to digest `sha256:5a824eb82cc7...`. Upstream data shows this is effectively a Python minor-line jump (3.13.x → 3.14.x), which carries language/runtime behavior change risk beyond a patch update. In this repo, usage is isolated to a single observability exporter script that depends only on Python stdlib, which limits blast radius. Merge is reasonable after a short runtime smoke check in-cluster.

### Update inventory

| Dependency | Ecosystem | Change | Scope | Local role | Risk |
|---|---|---|---|---|---|
| `python` | Docker/OCI (Official Image) | `3.13-alpine` → `3.14-alpine@sha256:5a824eb82cc75361f98611f3cfc5091ea33f10a6ccea4d4ebdabbc523b9a1614` | minor | runtime | Yellow |

### Important upstream changes

- [behavior] Python 3.14 release introduces substantial runtime/language updates vs 3.13 (official “What’s new in Python 3.14”).
- [feature] 3.14 highlights include deferred annotation evaluation (PEP 649/749), stdlib multiple interpreters (PEP 734), template string literals (PEP 750), and zstd stdlib support (PEP 784).
- [behavior] Docker Official Images currently map `3.14-alpine` to the 3.14 line (currently 3.14.5), while `3.13-alpine` maps to 3.13.13; this is a full minor-line jump plus patch-stream drift.
- [security] CPython 3.14 changelog/NEWS includes security fixes in the 3.14 cycle; moving to the actively patched line is generally favorable.
- [unknown] CPython does not publish GitHub Releases entries in the usual format; upstream assessment used Python docs/changelog + tags + Docker Official Images metadata instead.

### Local impact

- PR changes only `kubernetes/apps/observability/github-billing-exporter/app/deployment.yaml` image reference.
- Repository-wide search found this is the only `python:` container image reference under `kubernetes/`.
- Workload runs a custom script from `kubernetes/apps/observability/github-billing-exporter/app/configmap.yaml` using only stdlib modules (`urllib`, `http.server`, `datetime`, etc.), so risk from third-party package ABI breakage is low.
- This is an observability exporter (non-stateful) with readiness/liveness probes; rollback is straightforward by reverting the image tag.
- Supply-chain posture improves because the new image is digest-pinned (old value was tag-only).

### Pre-merge checks

- [ ] Confirm image pull succeeds in-cluster for `python:3.14-alpine@sha256:5a824...` (no registry/policy denial).
- [ ] After Flux reconciliation, verify `github-billing-exporter` pod reaches Ready and remains stable (no CrashLoopBackOff).
- [ ] Confirm `/healthz` and `/metrics` endpoints respond and `github_billing_exporter_last_scrape_success` remains `1`.
- [ ] Verify Prometheus scrape continuity for this target (no sustained scrape failures after rollout).
- [ ] Keep rollback plan ready: revert to prior image tag if runtime regression appears.

### Evidence reviewed

- PR: `feat(container): update image python ( 3.13 ➔ 3.14 )`; labels: `area/kubernetes`, `renovate/container`, `type/minor`, `dependencies`; diff summary: 1 file changed, 1 insertion/1 deletion.
- Files in repo:
  - `kubernetes/apps/observability/github-billing-exporter/app/deployment.yaml`
  - `kubernetes/apps/observability/github-billing-exporter/app/configmap.yaml`
  - `kubernetes/apps/observability/github-billing-exporter/ks.yaml`
- Upstream sources checked:
  - https://hub.docker.com/v2/namespaces/library/repositories/python/tags/3.13-alpine
  - https://hub.docker.com/v2/namespaces/library/repositories/python/tags/3.14-alpine
  - https://raw.githubusercontent.com/docker-library/official-images/master/library/python
  - https://docs.python.org/3/whatsnew/3.14.html
  - https://docs.python.org/3.14/whatsnew/changelog.html
  - https://api.github.com/repos/python/cpython/tags?per_page=30
  - https://raw.githubusercontent.com/python/cpython/v3.14.0/Misc/NEWS.d/3.14.0.rst
- Notable uncertainty: Could not derive an exact per-arch runtime delta beyond upstream tag/digest metadata; confidence reduced to Medium accordingly.
