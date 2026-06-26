#!/usr/bin/env bash
# forgejo-sync.sh — bring a Forgejo repo's settings to parity with its GitHub origin.
#
# Actions (idempotent, each checks current state first):
#   actions  — enable the Forgejo Actions unit (has_actions) when GitHub has Actions enabled
#   prs      — enable the Pull Requests unit (has_pull_requests). Converting a pull-mirror to a
#              regular repo leaves PRs DISABLED (mirrors are read-only), which makes Renovate skip
#              the repo ("pull requests are disabled") and blocks any normal PR. Always-on parity.
#   mirror   — add a Forgejo -> GitHub push-mirror (auto-backup) if none points at github.com
#   protect  — protect `main`: mirror GitHub's rule if it has one, else a minimal safe rule
#              (block force-push + deletion, keep direct-push — does NOT require PRs)
#
# SAFE BY DEFAULT: prints the intended mutations and exits. Pass --apply to actually write.
#
# Requires:
#   FORGEJO_TOKEN   Forgejo PAT, scope write:repository (+ admin to set protection). Never printed.
#   gh              GitHub CLI, authenticated (for reading GitHub state).
#   GH_MIRROR_TOKEN GitHub PAT (classic, scope `repo`) — ONLY needed for `mirror`. Never printed.
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
ONLY="actions,prs,mirror,protect"
REPOS=()

die() { echo "ERROR: $*" >&2; exit 1; }
have() { echo ",$ONLY," | grep -q ",$1,"; }

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
  mapfile -t REPOS < <(fj "$FORGEJO_API/orgs/$ORG/repos?limit=100" 2>/dev/null \
    | python3 -c 'import sys,json;[print(r["name"]) for r in json.load(sys.stdin) if not r.get("mirror") and not r.get("fork")]' 2>/dev/null || true)
  [ ${#REPOS[@]} -gt 0 ] || die "--all: could not list org repos (token needs read:organization scope, or pass --repo <name>)"
fi

sync_actions() {
  local r="$1"
  local gh_on fj_on
  gh_on=$(gh api "repos/$ORG/$r/actions/permissions" -q .enabled 2>/dev/null || echo "")
  fj_on=$(fj "$FORGEJO_API/repos/$ORG/$r" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("has_actions"))')
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

echo "forgejo-sync: org=$ORG only=$ONLY apply=$APPLY repos=${REPOS[*]}"
for r in "${REPOS[@]}"; do
  echo "== $r =="
  have actions && sync_actions "$r"
  have prs     && sync_prs     "$r"
  have mirror  && sync_mirror  "$r"
  have protect && sync_protect "$r"
done
echo "done.${APPLY:+}"
[ "$APPLY" = 1 ] || echo "(dry-run — re-run with --apply to write)"
