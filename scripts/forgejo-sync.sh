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
#   protect  — ADR-0050 delivery contract: protect `main` (+ `development` if the branch exists).
#              Direct push only for $PUSH_WHITELIST (default `webgrip-ci`: semantic-release commits
#              the release bump + tag back to the branch, so the old "protection breaks releases"
#              blocker is solved by the whitelist, not by leaving repos open). Merges only for
#              $MERGE_WHITELIST (default `ryangr0,renovate`: owner + Renovate automerge).
#              `agent-builder` is deliberately in NEITHER list — the fleet delivers via PRs
#              (ADR-0048) and never merges its own work. Existing rules are CONVERGED (PATCH),
#              not skipped. Still OPT-IN (not in the default set): roll out deliberately — one
#              repo, verify a real release cuts, then --all. Overrides per run, e.g. the homelab
#              GitOps repo (owner trunk-pushes, no release bot — ADR-0050):
#                PUSH_WHITELIST=ryangr0 MERGE_WHITELIST=ryangr0,renovate \
#                STATUS_CHECK_CONTEXTS='e2e / Lint & static validation (pull_request),e2e / Flux-local render (pull_request),e2e / Kyverno Chainsaw (KinD) (pull_request),e2e / Validate Renovate config (pull_request)' \
#                  scripts/forgejo-sync.sh --repo homelab-cluster --only protect --apply
#              NOTE the `renovate` in MERGE_WHITELIST: this override previously read
#              MERGE_WHITELIST=ryangr0, which would have revoked Renovate's ability to merge its
#              own PRs on the one repo where automerge does all the dependency work. The owner
#              trunk-pushes here, but Renovate still merges.
#              STATUS_CHECK_CONTEXTS is what actually makes CI a gate — see sync_protect().
#              Deliberately NOT `renovate/stability-days`: that is Renovate's own soak status, and
#              requiring it would block a human merging during a soak window.
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
ONLY="actions,prs,releases,settings,mirror,webhook"   # protect is OPT-IN (deliberate rollout — see header)
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
# gh is only needed for GitHub-reading actions (`actions` parity); protect/prs/releases/webhook
# are pure-Forgejo. Die only when a selected action actually reads GitHub.
if have actions; then command -v gh >/dev/null || die "gh not found (needed for --only actions; use --only protect,... to skip)"; fi

fj()  { curl -fsS -H "Authorization: token $FORGEJO_TOKEN" -H "Content-Type: application/json" "$@"; }
note() { echo "  $*"; }
mut()  { # mut <description> <curl-args...>
  local desc="$1"; shift
  if [ "$APPLY" = 1 ]; then note "APPLY: $desc"; fj "$@" >/dev/null && note "  ok" || note "  FAILED"
  else note "DRY-RUN would: $desc"; fi
}

# PAGINATED: this org holds 100+ repos once GitHub mirrors are counted — a single limit=100 fetch
# silently dropped everything past page one (ploeg was invisible to --all until 2026-07-26).
if [ ${#REPOS[@]} -eq 0 ]; then
  page=1
  while :; do
    raw=$(fj "$FORGEJO_API/orgs/$ORG/repos?limit=50&page=$page" 2>/dev/null) || break
    n=$(printf '%s' "$raw" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
    [ "$n" -gt 0 ] || break
    # while-read, not mapfile — bash 3.2 (stock macOS) has no mapfile (2026-07-12)
    while IFS= read -r repo_name; do
      [ -n "$repo_name" ] && REPOS+=("$repo_name")
    done < <(printf '%s' "$raw" \
      | python3 -c 'import sys,json;[print(r["name"]) for r in json.load(sys.stdin) if not r.get("mirror") and not r.get("fork") and not r.get("private")]' 2>/dev/null || true)
    page=$((page + 1))
  done
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

DEFAULT_MERGE_STYLE="${DEFAULT_MERGE_STYLE:-merge}"
DEFAULT_DELETE_BRANCH_AFTER_MERGE="${DEFAULT_DELETE_BRANCH_AFTER_MERGE:-true}"

sync_settings() {
  local r="$1" current desired drift merge_style_disabled
  current=$(fj "$FORGEJO_API/repos/$ORG/$r")
  desired=$(python3 -c '
import sys,json
print(json.dumps({"default_delete_branch_after_merge":sys.argv[1]=="true","default_merge_style":sys.argv[2]}))' \
    "$DEFAULT_DELETE_BRANCH_AFTER_MERGE" "$DEFAULT_MERGE_STYLE")
  drift=$(printf '%s' "$current" | python3 -c '
import sys,json
cur,want=json.load(sys.stdin),json.loads(sys.argv[1])
print("; ".join(f"{k}: {json.dumps(cur.get(k))} -> {json.dumps(v)}" for k,v in want.items() if cur.get(k)!=v))' "$desired")
  merge_style_disabled=$(printf '%s' "$current" | python3 -c '
import sys,json
style=sys.argv[1]
flag={"merge":"allow_merge_commits","rebase":"allow_rebase","rebase-merge":"allow_rebase_explicit","squash":"allow_squash_merge","fast-forward-only":"allow_fast_forward_only_merge"}.get(style)
print(bool(flag) and json.load(sys.stdin).get(flag) is False)' "$DEFAULT_MERGE_STYLE")
  if [ "$merge_style_disabled" = "True" ]; then
    note "settings: WARN $r disallows merge style '$DEFAULT_MERGE_STYLE', so defaulting to it offers a disabled button"
  fi
  if [ -z "$drift" ]; then
    note "settings: already converged (default_delete_branch_after_merge=$DEFAULT_DELETE_BRANCH_AFTER_MERGE default_merge_style=$DEFAULT_MERGE_STYLE)"
  else
    mut "converge settings on $r ($drift)" -X PATCH "$FORGEJO_API/repos/$ORG/$r" -d "$desired"
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

# ADR-0050 whitelists. Overridable per run; comma-separated usernames. NEVER add agent-builder.
# development gets the owner too: trunk-based development happens THERE on product repos
# (main is release-bot-only), and semantic-release RC channels commit version bumps back to it.
PUSH_WHITELIST="${PUSH_WHITELIST:-webgrip-ci}"
DEV_PUSH_WHITELIST="${DEV_PUSH_WHITELIST:-webgrip-ci,ryangr0}"
MERGE_WHITELIST="${MERGE_WHITELIST:-ryangr0,renovate}"
# Comma-separated required status-check contexts. EMPTY = omit the keys entirely (the historical
# behaviour, and why other repos' hand-set checks survive a converge PATCH — see sync_protect).
STATUS_CHECK_CONTEXTS="${STATUS_CHECK_CONTEXTS:-}"

sync_protect() {
  local r="$1" b body exists push_list
  for b in main development; do
    # main always exists; development only on repos that cut RCs from it.
    push_list="$PUSH_WHITELIST"
    if [ "$b" = development ]; then
      fj "$FORGEJO_API/repos/$ORG/$r/branches/$b" >/dev/null 2>&1 || continue
      push_list="$DEV_PUSH_WHITELIST"
    fi
    # Any rule blocks force-push + deletion; the contract lives in the whitelists.
    # Status checks stay OPT-IN via $STATUS_CHECK_CONTEXTS, because Forgejo check names differ per
    # repo and several repos have them set by hand. When the var is empty we omit the two keys
    # ENTIRELY rather than sending false — a converge PATCH carrying enable_status_check:false
    # would silently wipe those hand-set contexts.
    #
    # WHY THIS MATTERS (2026-08-04): required status checks are the ONLY thing in Forgejo that
    # makes CI a merge gate. Branch-protection rules are what the merge path — including the
    # background auto-merge job — actually consults. With no contexts required, a red PR is
    # mergeable and `platformAutomerge` would merge it the moment it is scheduled, without
    # waiting for e2e. Contexts must match the reported names EXACTLY: forgejo#9288 means a
    # pattern matching zero tasks counts as MATCHED, so a typo yields a rule that looks correct
    # in the UI and gates nothing. Always mutation-test both directions after applying.
    body=$(python3 -c '
import sys,json
b,push,merge,checks=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]
rule={
    "rule_name": b,
    "enable_push": True,
    "enable_push_whitelist": True,
    "push_whitelist_usernames": [u for u in push.split(",") if u],
    "enable_merge_whitelist": True,
    "merge_whitelist_usernames": [u for u in merge.split(",") if u],
}
ctx=[c.strip() for c in checks.split(",") if c.strip()]
if ctx:
    rule["enable_status_check"]=True
    rule["status_check_contexts"]=ctx
print(json.dumps(rule))' "$b" "$push_list" "$MERGE_WHITELIST" "$STATUS_CHECK_CONTEXTS")
    # Listing rules needs repo ADMIN scope; on 403 assume absent (POST; a duplicate 409s harmlessly).
    exists=$(fj "$FORGEJO_API/repos/$ORG/$r/branch_protections" 2>/dev/null \
      | python3 -c 'import sys,json;bn=sys.argv[1];print(any((x.get("rule_name") or x.get("branch_name"))==bn for x in json.load(sys.stdin)))' "$b" 2>/dev/null || echo False)
    if [ "$exists" = "True" ]; then
      mut "converge protection $r:$b (push={$push_list} merge={$MERGE_WHITELIST} checks={${STATUS_CHECK_CONTEXTS:-none}})" \
        -X PATCH "$FORGEJO_API/repos/$ORG/$r/branch_protections/$b" -d "$body"
    else
      mut "protect $r:$b (push={$push_list} merge={$MERGE_WHITELIST} checks={${STATUS_CHECK_CONTEXTS:-none}})" \
        -X POST "$FORGEJO_API/repos/$ORG/$r/branch_protections" -d "$body"
    fi
  done
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
  have settings && sync_settings "$r"
  have mirror   && sync_mirror   "$r"
  have protect && sync_protect "$r"
  have webhook && sync_webhook "$r"
done
echo "done.${APPLY:+}"
[ "$APPLY" = 1 ] || echo "(dry-run — re-run with --apply to write)"
