#!/usr/bin/env bash
# forgejo-sync.sh — bring a Forgejo repo's settings to parity with its GitHub origin.
#
# Actions (idempotent, each checks current state first):
#   actions  — enable the Forgejo Actions unit (has_actions) when GitHub has Actions enabled,
#              EXCEPT for reusable-workflow library repos in ACTIONS_OFF_REPOS (forced off)
#   prs      — enable the Pull Requests unit (has_pull_requests). Converting a pull-mirror to a
#              regular repo leaves PRs DISABLED (mirrors are read-only), which makes Renovate skip
#              the repo ("pull requests are disabled") and blocks any normal PR. Always-on parity.
#   releases — enable the Releases unit (has_releases). Un-mirroring leaves it OFF too, so the
#              Releases tab/API 404s and in-cluster CI (semantic-release via the Gitea plugin) has no
#              Releases tab to publish into. Git tags mirror over, but Release OBJECTS do not — and
#              historical GitHub releases never backfill; this only enables the unit for new ones.
#              Always-on parity.
#   mirror   — add a Forgejo -> GitHub push-mirror (auto-backup) if none points at github.com
#   protect  — protect `main`: mirror GitHub's rule if it has one, else a minimal safe rule
#              (block force-push + deletion, keep direct-push — does NOT require PRs).
#              OPT-IN (not in the default set): a Forgejo-leading repo's CI commits the
#              semantic-release `chore(release)` bump + tag DIRECTLY to main, so mirroring GitHub's
#              "require PR + approval" rule (enable_push:false) REJECTS the bot and breaks releases.
#              Forgejo-leading repos run UNPROTECTED, matching webgrip/infrastructure. Use `protect`
#              only on a repo where humans gate main and no bot pushes.
#   webhook  — register a Forgejo repo webhook -> the renovate-operator receiver so ticking a
#              Dependency-Dashboard / PR checkbox triggers an immediate Renovate run (not the 6h cron).
#              Idempotent: matches an existing hook by receiver URL; creates if missing, refreshes if
#              present. The operator's native webhook.forgejo.sync is broken on Forgejo 15, so we do
#              it per-repo (the documented Forgejo way). See jobs/README.md.
#
# SAFE BY DEFAULT: prints the intended mutations and exits. Pass --apply to actually write.
#
# Requires:
#   FORGEJO_TOKEN   Forgejo PAT, scope write:repository (+ repo admin for `protect` and `webhook`). Never printed.
#   gh              GitHub CLI, authenticated (for reading GitHub state).
#   GH_MIRROR_TOKEN GitHub PAT (classic, scope `repo`) — ONLY needed for `mirror`. Never printed.
#   RENOVATE_WEBHOOK_AUTH_TOKEN  bearer the hook sends to the receiver — ONLY for `webhook`. Optional:
#              if unset and kubectl is configured, falls back to Secret renovate/renovate-webhook-auth
#              key `token`. Never printed.
#
# Usage:
#   scripts/forgejo-sync.sh --repo workflows                 # dry-run, all actions, one repo
#   scripts/forgejo-sync.sh --repo workflows --apply
#   scripts/forgejo-sync.sh --all --only actions,mirror --apply
#   scripts/forgejo-sync.sh --repo renovate-config --only protect --apply
set -euo pipefail

FORGEJO_API="https://forgejo.webgrip.dev/api/v1"
GITHUB_HOST="github.com"
ORG="webgrip"
APPLY=0
ONLY="actions,prs,releases,mirror,webhook"   # protect is OPT-IN (breaks CI commit-back — see header)
REPOS=()
# Reusable-workflow LIBRARY repos: their workflows are `on: workflow_call` and run in the *caller*
# repo, never here. Keep the Forgejo Actions unit OFF for these even though GitHub has it on, so
# pushes/PRs don't spawn stray in-repo runs (disabling the unit does NOT break `uses:` consumers —
# the caller's runner resolves+executes the reusable workflow).
ACTIONS_OFF_REPOS="workflows"
# Renovate webhook receiver. Forgejo is IN-CLUSTER, so the hook targets the operator Service directly
# (http, port 8082) — no envoy-external hairpin / public round-trip needed. The ?namespace=&job= params
# route the inbound event to the Forgejo RenovateJob.
RENOVATE_WEBHOOK_URL="http://renovate-operator.renovate.svc.cluster.local:8082/webhook/v1/forgejo?namespace=renovate&job=webgrip-forgejo"

die() { echo "ERROR: $*" >&2; exit 1; }
have() { echo ",$ONLY," | grep -q ",$1,"; }
is_actions_off() { echo " $ACTIONS_OFF_REPOS " | grep -q " $1 "; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPOS+=("$2"); shift 2 ;;
    --all)  shift ;;            # repo list resolved below
    --only) ONLY="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

[ -n "${FORGEJO_TOKEN:-}" ] || die "FORGEJO_TOKEN not set (Forgejo Settings -> Applications -> generate, scope write:repository)"
command -v gh >/dev/null || die "gh not found"

fj()  { curl -fsS -H "Authorization: token $FORGEJO_TOKEN" -H "Content-Type: application/json" "$@"; }
note() { echo "  $*"; }
mut()  { # mut <description> <curl-args...>
  local desc="$1"; shift
  if [ "$APPLY" = 1 ]; then note "APPLY: $desc"; fj "$@" >/dev/null && note "  ok" || note "  FAILED"
  else note "DRY-RUN would: $desc"; fi
}

# Resolve --all to every non-fork, non-mirror repo in the org (mirrors aren't ours to manage yet).
if [ ${#REPOS[@]} -eq 0 ]; then
  # while-read, not mapfile — bash 3.2 (stock macOS) has no mapfile (2026-07-12)
  while IFS= read -r repo_name; do
    [ -n "$repo_name" ] && REPOS+=("$repo_name")
  done < <(fj "$FORGEJO_API/orgs/$ORG/repos?limit=100" 2>/dev/null \
    | python3 -c 'import sys,json;[print(r["name"]) for r in json.load(sys.stdin) if not r.get("mirror") and not r.get("fork")]' 2>/dev/null || true)
  [ ${#REPOS[@]} -gt 0 ] || die "--all: could not list org repos (token needs read:organization scope, or pass --repo <name>)"
fi

sync_actions() {
  local r="$1"
  local gh_on fj_on
  fj_on=$(fj "$FORGEJO_API/repos/$ORG/$r" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("has_actions"))')
  if is_actions_off "$r"; then            # reusable-workflow library: force the unit OFF
    if [ "$fj_on" = "True" ]; then
      mut "DISABLE Actions on $r (reusable-workflow library — runs belong in caller repos)" \
          -X PATCH "$FORGEJO_API/repos/$ORG/$r" -d '{"has_actions":false}'
    else
      note "actions: kept off ($r is a reusable-workflow library)"
    fi
    return
  fi
  gh_on=$(gh api "repos/$ORG/$r/actions/permissions" -q .enabled 2>/dev/null || echo "")
  if [ "$gh_on" = "true" ] && [ "$fj_on" != "True" ]; then
    mut "enable Actions unit on $r (GitHub=on, Forgejo=off)" \
        -X PATCH "$FORGEJO_API/repos/$ORG/$r" -d '{"has_actions":true}'
  else
    note "actions: nothing to do (GitHub=$gh_on, Forgejo has_actions=$fj_on)"
  fi
}

sync_prs() {
  local r="$1"
  local on
  on=$(fj "$FORGEJO_API/repos/$ORG/$r" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("has_pull_requests"))')
  if [ "$on" != "True" ]; then
    mut "enable Pull Requests unit on $r (was disabled — un-mirror leaves it off; Renovate skips PR-less repos)" \
        -X PATCH "$FORGEJO_API/repos/$ORG/$r" -d '{"has_pull_requests":true}'
  else
    note "prs: already enabled"
  fi
}

sync_releases() {
  local r="$1"
  local on
  on=$(fj "$FORGEJO_API/repos/$ORG/$r" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("has_releases"))')
  if [ "$on" != "True" ]; then
    mut "enable Releases unit on $r (was disabled — un-mirror leaves it off; CI semantic-release publishes Releases)" \
        -X PATCH "$FORGEJO_API/repos/$ORG/$r" -d '{"has_releases":true}'
  else
    note "releases: already enabled"
  fi
}

sync_mirror() {
  local r="$1"
  local exists
  exists=$(fj "$FORGEJO_API/repos/$ORG/$r/push_mirrors" \
    | python3 -c "import sys,json;print(any('$GITHUB_HOST' in m.get('remote_address','') for m in json.load(sys.stdin)))" 2>/dev/null || echo False)
  if [ "$exists" = "True" ]; then note "mirror: already mirrors to $GITHUB_HOST"; return; fi
  [ -n "${GH_MIRROR_TOKEN:-}" ] || { note "mirror: SKIP — GH_MIRROR_TOKEN not set (GitHub PAT, scope repo)"; return; }
  if [ -z "${GH_MIRROR_USER:-}" ]; then  # resolve token owner once; that's the auth username GitHub wants
    GH_MIRROR_USER=$(curl -fsS -H "Authorization: token $GH_MIRROR_TOKEN" https://api.github.com/user 2>/dev/null \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["login"])' 2>/dev/null || echo "")
  fi
  [ -n "$GH_MIRROR_USER" ] || { note "mirror: SKIP — GH_MIRROR_TOKEN invalid (api.github.com/user failed)"; return; }
  local body
  body=$(python3 -c "import json;print(json.dumps({'remote_address':'https://$GITHUB_HOST/$ORG/$r.git','remote_username':'$GH_MIRROR_USER','remote_password':'__TOKEN__','interval':'8h0m0s','sync_on_commit':True}))")
  if [ "$APPLY" = 1 ]; then
    note "APPLY: add push-mirror $r -> $GITHUB_HOST"
    fj -X POST "$FORGEJO_API/repos/$ORG/$r/push_mirrors" \
       -d "${body/__TOKEN__/$GH_MIRROR_TOKEN}" >/dev/null && note "  ok" || note "  FAILED"
  else
    note "DRY-RUN would: add push-mirror $r -> $GITHUB_HOST (sync_on_commit, 8h fallback)"
  fi
}

sync_protect() {
  local r="$1"
  local existing
  existing=$(fj "$FORGEJO_API/repos/$ORG/$r/branch_protections" \
    | python3 -c 'import sys,json;print(any(b.get("rule_name")=="main" or b.get("branch_name")=="main" for b in json.load(sys.stdin)))' 2>/dev/null || echo False)
  if [ "$existing" = "True" ]; then note "protect: main already protected"; return; fi
  # Read GitHub's rule (if any) to decide strict-vs-baseline.
  # NB: gh prints the error body to stdout on 404, so keep the fallback OUTSIDE the
  # command substitution — `|| echo {}` inside would concatenate two JSON docs.
  local ghp; ghp=$(gh api "repos/$ORG/$r/branches/main/protection" 2>/dev/null) || ghp='{}'
  # Strict iff GitHub requires PR reviews. We DON'T copy status_check_contexts: those are
  # GitHub job names and would deadlock Forgejo merges (Forgejo checks are named differently).
  local body
  body=$(echo "$ghp" | python3 -c '
import sys,json
g=json.load(sys.stdin)
rpr=g.get("required_pull_request_reviews")
strict=bool(rpr)
rule={"rule_name":"main","enable_push":not strict}   # any rule => force-push & deletion blocked
if rpr:
    rule["required_approvals"]=rpr.get("required_approving_review_count",1)
print(json.dumps(rule))')
  echo "$ghp" | grep -q required_status_checks && \
    note "  note: GitHub required status checks here — NOT copied (Forgejo job names differ); re-add under Forgejo check names once CI has run"
  local kind; kind=$([ "$(echo "$body" | grep -c required_approvals)" -gt 0 ] && echo "strict (mirrors GitHub)" || echo "baseline (no-force-push/no-delete, direct-push kept)")
  if [ "$APPLY" = 1 ]; then
    note "APPLY: protect main on $r — $kind"
    fj -X POST "$FORGEJO_API/repos/$ORG/$r/branch_protections" -d "$body" >/dev/null && note "  ok" || note "  FAILED"
  else
    note "DRY-RUN would: protect main on $r — $kind : $body"
  fi
}

# Resolve the receiver bearer token once (env wins; else the in-cluster Secret). Never printed.
# Lazy: only invoked from sync_webhook, so a no-webhook run never needs kubectl or the token.
WEBHOOK_TOKEN=""
resolve_webhook_token() {
  [ -n "$WEBHOOK_TOKEN" ] && return 0
  if [ -n "${RENOVATE_WEBHOOK_AUTH_TOKEN:-}" ]; then
    WEBHOOK_TOKEN="$RENOVATE_WEBHOOK_AUTH_TOKEN"
  else
    command -v kubectl >/dev/null || { note "webhook: SKIP — no RENOVATE_WEBHOOK_AUTH_TOKEN and no kubectl"; return 1; }
    WEBHOOK_TOKEN="$(kubectl -n renovate get secret renovate-webhook-auth -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    [ -n "$WEBHOOK_TOKEN" ] || { note "webhook: SKIP — could not read Secret renovate/renovate-webhook-auth (kubectl context? RBAC?)"; return 1; }
  fi
  WEBHOOK_TOKEN="${WEBHOOK_TOKEN%%,*}"   # Secret may hold a comma-separated list; embed exactly ONE
}

sync_webhook() {
  local r="$1"
  resolve_webhook_token || return 0       # SKIP already noted; non-fatal so other repos/actions proceed
  local base="${RENOVATE_WEBHOOK_URL%%\?*}"
  # Dedupe on the URL PREFIX (before '?') so adding/removing query params never spawns a duplicate hook.
  local id
  id=$(fj "$FORGEJO_API/repos/$ORG/$r/hooks" 2>/dev/null \
    | python3 -c "import sys,json;h=json.load(sys.stdin);print(next((str(x['id']) for x in h if x.get('config',{}).get('url','').split('?')[0]=='$base'),''))" 2>/dev/null || echo "")
  # __TOKEN__ placeholder so the bearer never appears in any echo/dry-run line (like sync_mirror).
  # NB: authorization_header is a TOP-LEVEL field in the Forgejo hook API, NOT a config key — Forgejo
  # silently drops unknown config keys, so nesting it sends NO Authorization header → receiver 401s.
  local body
  body=$(python3 -c "import json;print(json.dumps({'type':'forgejo','config':{'url':'$RENOVATE_WEBHOOK_URL','content_type':'json','http_method':'POST'},'events':['issues','pull_request'],'active':True,'authorization_header':'Bearer __TOKEN__'}))")
  if [ -z "$id" ]; then
    if [ "$APPLY" = 1 ]; then
      note "APPLY: create Renovate webhook on $r"
      fj -X POST "$FORGEJO_API/repos/$ORG/$r/hooks" -d "${body/__TOKEN__/$WEBHOOK_TOKEN}" >/dev/null && note "  ok" || note "  FAILED"
    else
      note "DRY-RUN would: create Renovate webhook on $r -> $base (events: issues,pull_request)"
    fi
  else
    # Hook exists. Forgejo masks authorization_header on GET, so we can't diff the token — a PATCH
    # always re-sets url/events/active and the bearer (this also doubles as the token-rotation refresh).
    if [ "$APPLY" = 1 ]; then
      note "APPLY: refresh Renovate webhook on $r (id $id)"
      fj -X PATCH "$FORGEJO_API/repos/$ORG/$r/hooks/$id" -d "${body/__TOKEN__/$WEBHOOK_TOKEN}" >/dev/null && note "  ok" || note "  FAILED"
    else
      note "webhook: already registered on $r (id $id) — would refresh config/token"
    fi
  fi
}

echo "forgejo-sync: org=$ORG only=$ONLY apply=$APPLY repos=${REPOS[*]}"
for r in "${REPOS[@]}"; do
  echo "== $r =="
  have actions  && sync_actions  "$r"
  have prs      && sync_prs      "$r"
  have releases && sync_releases "$r"
  have mirror   && sync_mirror   "$r"
  have protect && sync_protect "$r"
  have webhook && sync_webhook "$r"
done
echo "done.${APPLY:+}"
[ "$APPLY" = 1 ] || echo "(dry-run — re-run with --apply to write)"
