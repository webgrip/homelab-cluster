# Runbook: Renovate

Use this when Renovate alerts are firing (for example `RenovateOperatorDeploymentUnavailable`, `RenovateProjectRunFailed`, `RenovateProjectDependencyIssues`) or Renovate PRs stop appearing.

## Fast triage

**Step 1 — operator / controller**

- `kubectl -n renovate get pods -o wide`
- `kubectl -n renovate logs deploy/renovate-operator --tail=200`

**Step 2 — per-repo run outcomes on the RenovateJob CR** (fastest signal; the MCP read-only role can't list these — use kubectl)

```bash
mise exec -- kubectl get renovatejob -n renovate webgrip-gitops -o json \
  | jq '.status.projects[] | {name, lastRun, status, prActivity, logIssues}'
```

**Step 3 — worker-pod debug logs.** Worker pods (`webgrip-<job>-<repo>-<hash>`) persist **~30 minutes** until the `renovate-job-cleanup` cron deletes them; their logs are NOT shipped to VictoriaLogs. Both jobs run `LOG_LEVEL: debug`; output is bunyan JSON:

```bash
kubectl logs -n renovate <worker-pod> --tail=-1 | grep '^{' \
  | jq -rc 'select(.level >= 40) | {branch, msg, artifactErrors}'
# per-branch trace:
#   jq -rc 'select(.branch=="renovate/<branch>") | [.level, .msg] | @tsv'
```

**Step 4 — Dependency Dashboard.** Renovate runs against **both forges** (GitHub + Forgejo), each repo has its own dashboard issue

- Look for authentication errors, rate limiting, or failing managers.
- A ticked approval that "did nothing" = the branch produced zero changes (see signatures below); the tick is consumed and the item re-renders unchecked. Re-tick after fixing the cause.

**Step 5 — Flux status** (if Renovate is deployed via GitOps)

- See the Flux runbook: [docs/techdocs/docs/runbooks/flux.md](flux.md)

## Force a run

The operator's schedule endpoint takes the RenovateJob name and a URL-encoded project. **Without `job=` only the gitops job's projects are scheduled** — the Forgejo job must be addressed explicitly:

```bash
kubectl -n renovate port-forward svc/renovate-operator 18082:8082 &
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:18082/webhook/v1/schedule?job=webgrip-forgejo&namespace=renovate&project=webgrip%2Finfrastructure"
```

(Token: `renovate-webhook-auth` secret. The `renovate-trigger` agent wraps this.)

Note: editing a dashboard issue on Forgejo fires a webhook run near-instantly, but that run can read the **pre-click** issue body — checkbox ticks are honored by the *next* run.

## All PRs red at once: OCI digest drift

If `verify-oci-digests` FAILs the same file on main **and** every PR, an upstream chart tag was re-pushed (coredns `1.46.0` has shipped three digests). Confirm against the registry, then let the automerged digest PR fix it (or bump the pin by hand — precedent: `72f52195`, `796989d0`):

```bash
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:<org>/<chart>:pull" | jq -r .token)
curl -s -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{header_json}' \
  "https://ghcr.io/v2/<org>/<chart>/manifests/<tag>" | jq -r '."docker-content-digest"[0]'
```

Since renovate-config v1.5.0 + the repo's digest-automerge rule this self-heals; a wedge recurring means that pipeline broke.

## Known failure signatures (worker-pod log → cause)

| Signature | Cause | Fix |
|---|---|---|
| `Digest is not updated` on `renovate.json` / `webgrip/renovate-config` | Global `pinDigests: true` tried to digest-pin the preset reference; the replace never applies and **aborts the whole grouped branch** | renovate-config ≥ v1.5.1 (`pinDigests: false` for the preset package) |
| `Digest is not updated` on `.mise.toml` / `aqua:*` | Same class: the mise manager can't write digests into aqua entries | renovate-config ≥ v1.5.2 (digest updates disabled for the mise manager) |
| `artifactErrors` + `Command failed: ./scripts/update-oci-digests.sh` on **every** branch | The postUpgradeTask 401'd against Harbor (public projects still require an anonymous bearer token) and died at the first harbor-proxied chart | fixed in `scripts/lib/oci.sh` (`/service/token?service=harbor-registry`); if it recurs, run the script locally |
| `Cannot find replaceString in current file content` → `No files to commit` | Multi-ARG Dockerfile FROM composition (`${REGISTRY}/img:${VER}-suffix`): the dockerfile manager resolves ARGs at extraction, then can't find the resolved string in the raw file — the update **silently no-ops** | own the ARG with an annotated-ARG regex manager and disable the dockerfile manager for that file (see webgrip/infrastructure `renovate.json`) |
| PR shows "branch already included / nothing to merge", only a "Manually merged" button | Zombie group-branch: a merged PR's branch survived, the group got a new update, Renovate reopened a PR on the stale branch without pushing | Renovate self-heals next run (closes PR, deletes branch); prevent with delete-branch-after-merge |
| `Update has not passed minimum release age` | Release younger than soak (patch 1d / minor 3d / major 14d). Not an error; on the Forgejo path the PR still opens with a pending `renovate/stability-days` status | check the tag age with `curl -s https://hub.docker.com/v2/repositories/library/<img>/tags/<tag>` piped to `jq -r .last_updated` |

## Common causes

- Token expired / revoked (GitHub app token / PAT).
- Repository permissions changed.
- Renovate image updated but config incompatible.
- Cluster resource pressure causing restarts.

## Forgejo path gotchas

The in-cluster Renovate also runs against Forgejo (`webgrip-forgejo` RenovateJob). Two failure modes are silent — Renovate keeps running, it just quietly does nothing for the affected repos.

- **Un-mirrored repos have the Pull Requests unit OFF, so Renovate skips them.** Converting a `gitea-mirror` pull-mirror to a regular repo leaves `has_pull_requests=false` (mirrors are read-only). Renovate then logs `Skipping repository <r> because pull requests are disabled` and excludes it — the repo is *discovered but skipped*. Also note autodiscovery **can only seed `status.projects` on the cron** (`47 */6`); the per-project webhook path can't add a *new* project mid-cron. Fix / restore PR-unit parity for every de-mirrored repo:

  ```bash
  scripts/forgejo-sync.sh --all --only prs --apply
  ```

- **The webhook `authorization_header` must be a TOP-LEVEL field, not a `config` key.** On the Forgejo hook API, `authorization_header` is top-level; Forgejo silently drops unknown `config` keys, so nesting it sends NO `Authorization` header and the operator receiver 401s. Diagnose via the hook's UI "Recent Deliveries" (it shows the sent headers + response code). The per-repo webhook is registered by `scripts/forgejo-sync.sh --only webhook` and points at the internal Service (`http://renovate-operator.renovate.svc.cluster.local:8082/webhook/v1/forgejo?…`), not the envoy-external hairpin.

Debugging trick for "which repos are skipped and why": `renovate --autodiscover --write-discovered-repos` with `LOG_LEVEL=debug`.

## More detail

- Full Renovate docs/config: [docs/techdocs/docs/renovate.md](../general/renovate.md)
- Forgejo migration design: [RFC — Renovate on Forgejo](../rfc/rfc-renovate-forgejo.md)
