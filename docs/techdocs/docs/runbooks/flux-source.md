# Runbook: Flux source (GitOps source of truth)

The cluster reconciles from the **in-cluster Forgejo** over its internal Service URL
([ADR-0011](../adr/adr-0011-flux-source-forgejo.md)); GitHub is a **downstream force-push-mirror**
kept as the cold-bootstrap and break-glass source
([ADR-0012](../adr/adr-0012-external-bootstrap-fallback-source.md)). Cut over 2026-07-13
([RFC](../rfc/rfc-flux-forgejo-source.md), Vikunja #77).

## Facts

- Source of truth: `http://forgejo-http.forgejo.svc.cluster.local:3000/webgrip/homelab-cluster.git`
  — set in `kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml`
  (`values.instance.sync.url`), rendered by flux-operator into `GitRepository/flux-system`.
- Break-glass source: `https://github.com/webgrip/homelab-cluster.git` — kept current by the
  Forgejo→GitHub push-mirror (`sync_on_commit`, 8h fallback interval).
- Read auth: none (repo is public-read on both hosts); no `pullSecret`.
- Webhooks → Receiver `github-webhook` (`type: github` — Forgejo payloads are compatible):
  a Forgejo repo webhook targets the Receiver's **internal** Service URL; the old GitHub repo
  webhook targets `flux-webhook.${SECRET_DOMAIN}`. **Keep both** — the GitHub one is what makes
  break-glass reconciles instant.
- The push-mirror runs `git push --mirror` (**force**): anything pushed to GitHub outside
  break-glass is silently overwritten by the next relay. GitHub is read-only by convention.

## Fast triage — cluster stopped picking up commits

```sh
# 1. Is the source Ready, and which host is it reading?
flux get sources git -n flux-system
kubectl get gitrepository flux-system -n flux-system -o jsonpath='{.spec.url}{"\n"}{.status.artifact.revision}{"\n"}'

# 2. Forgejo down? Running workloads keep running on the last-applied state (degrade, not outage).
kubectl get pods -n forgejo -l app=forgejo

# 3. Webhook path dead but polling alive? Reconciles happen but only every interval.
kubectl logs -n flux-system deploy/notification-controller --since=10m | grep receiver-server
```

## Break-glass: repoint Flux at GitHub (Forgejo outage)

Patch the **FluxInstance, not the generated GitRepository** — flux-operator reverts direct edits
to the GitRepository via server-side-apply; the FluxInstance patch sticks (the flux-instance
HelmRelease does not run drift detection, so helm won't revert it either — until the next chart
upgrade, which is fine: by then you've either restored Forgejo or committed the change).

```sh
# 1. Repoint (the one sanctioned imperative exception to GitOps-only):
kubectl -n flux-system patch fluxinstance flux --type merge \
  -p '{"spec":{"sync":{"url":"https://github.com/webgrip/homelab-cluster.git"}}}'

# 2. Confirm recovery — Ready=True with a github.com URL:
flux reconcile source git flux-system -n flux-system
flux get sources git -n flux-system

# 3. Fix whatever killed Forgejo (commits now flow: push to GitHub `github` remote directly —
#    during break-glass GitHub temporarily IS the source of truth; the push-mirror is wedged
#    anyway while Forgejo is down, so nothing overwrites you).

# 4. Once Forgejo is healthy again: sync it back from GitHub (it missed the break-glass
#    commits!) BEFORE repointing. Push the GitHub-era commits to Forgejo:
git fetch github && git push origin github/main:main

# 5. Repoint forward:
kubectl -n flux-system patch fluxinstance flux --type merge \
  -p '{"spec":{"sync":{"url":"http://forgejo-http.forgejo.svc.cluster.local:3000/webgrip/homelab-cluster.git"}}}'
flux get sources git -n flux-system
```

Drill log: see the dated entries at the bottom of this file.

## Mirror-direction recovery (Forgejo restored after break-glass)

Step 4 above is the critical one: **never** let the push-mirror fire while GitHub holds commits
Forgejo lacks — `--mirror` force-push would destroy them. If in doubt, compare before repointing:

```sh
git fetch origin github
git rev-parse origin/main github/main   # equal, or github strictly ahead → push github→origin first
```

## Cold bootstrap (rebuild from bare Talos)

The bootstrap source must exist before the cluster does — that is GitHub, per ADR-0012.
`scripts/bootstrap-apps.sh` + `flux bootstrap` run against the GitHub URL with the bootstrap-time
deploy key (repo-root `github-deploy.key`, git-ignored). After Forgejo is reconciled and healthy,
repoint as in step 5 above.

## Known tripwires

- **Zero-trust rollout:** the Forgejo→Receiver webhook targets
  `webhook-receiver.flux-system.svc` directly. When the `forgejo` namespace goes default-deny,
  that egress dies **silently** (reconciles fall back to the poll interval). The netpol change
  must allow forgejo→flux-system:80. (Tracked on the network-policy backlog.)
- **Renovate:** this repo is updated by the `webgrip-forgejo` RenovateJob (cron `47 */6` UTC).
  The GitHub job's explicit list must never re-include Forgejo-leading repos — Renovate branch
  automerge on a downstream mirror is silently destroyed by the relay.
- **Push-mirror health is silent:** `last_error` empty + fresh `last_update` is the only signal
  (`GET /api/v1/repos/webgrip/homelab-cluster/push_mirrors`). Staleness alerting is a pending
  follow-up; until it lands, check after any Forgejo maintenance.
