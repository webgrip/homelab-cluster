#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
app="$repo_root/kubernetes/apps/forgejo/forgejo-actions-secrets/app"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/state"

cat > "$work/bin/curl" <<'FAKE'
#!/bin/sh
method=GET
url=""
body=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -d) [ "$2" = @- ] && body="$(cat)" || body="$2"; shift 2 ;;
    -u|-H|-o|-w|--connect-timeout|--max-time) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
state="$FAKE_STATE"
path="${url#http://forgejo.test/api/v1}"
page="$(printf '%s' "$path" | sed -n 's/.*[?&]page=\([0-9]*\).*/\1/p')"
route="${path%%\?*}"
echo "$method $route" >> "$state/calls"
case "$method $route" in
  "GET /orgs/webgrip/repos")
    [ "$page" = 1 ] && cat "$state/repos.json" || echo '[]' ;;
  "GET /repos/webgrip/"*"/pulls")
    repo="${route#/repos/webgrip/}"; repo="${repo%/pulls}"
    [ "$page" = 1 ] && cat "$state/pulls-$repo.json" || echo '[]' ;;
  "GET /repos/webgrip/"*"/commits/"*"/status")
    sha="${route%/status}"; sha="${sha##*/}"
    cat "$state/status-$sha.json" ;;
  "POST /repos/webgrip/"*"/issues/"*"/labels")
    echo "${route#/repos/webgrip/} $body" >> "$state/labelled" ;;
  "GET /repos/webgrip/"*"/labels")
    [ "$page" = 1 ] && cat "$state/repo-labels.json" || echo '[]' ;;
  "POST /repos/webgrip/"*"/labels")
    jq --argjson label "$body" '. + [$label + {id: 501}]' "$state/repo-labels.json" > "$state/repo-labels.new"
    mv "$state/repo-labels.new" "$state/repo-labels.json"
    echo '{"id": 501}' ;;
  *)
    exit 22 ;;
esac
FAKE
chmod +x "$work/bin/curl"

iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
iso_plus_two() { date -u -d "@$(($1 + 7200))" +%Y-%m-%dT%H:%M:%S+02:00; }
now="$(date +%s)"
old="$(iso $((now - 5400)))"
recent="$(iso $((now - 600)))"
old_offset="$(iso_plus_two $((now - 5400)))"
recent_offset="$(iso_plus_two $((now - 1800)))"

status() { jq -nc --arg s "$1" --arg d "$2" --arg t "$3" '{statuses: [{status: "success", description: "Successful in 1m", updated_at: $t}, {status: $s, description: $d, updated_at: $t}]}'; }
pull() { jq -nc --argjson n "$1" --arg sha "$2" --arg user "$3" --argjson labels "$4" '{number: $n, head: {sha: $sha}, user: {login: $user}, labels: $labels}'; }

reset() {
  rm -rf "$work/state" && mkdir -p "$work/state"
  echo '[{"name":"app","archived":false,"has_pull_requests":true},{"name":"old","archived":true,"has_pull_requests":true}]' > "$work/state/repos.json"
  echo '[]' > "$work/state/pulls-old.json"
  echo '[]' > "$work/state/repo-labels.json"
}

run() {
  PATH="$work/bin:$PATH" FAKE_STATE="$work/state" FORGEJO_URL=http://forgejo.test ADMIN_USERNAME=a ADMIN_PASSWORD=p \
    ORG=webgrip RENOVATE_USER=renovate REBASE_LABEL=rebase MIN_AGE_MINUTES=60 MAX_RETRIES="${1:-10}" \
    sh "$app/renovate-cancelled-ci-retry.sh" > "$work/state/out" 2>&1
}

fail() { echo "FAIL: $*" >&2; cat "$work/state/out" >&2; exit 1; }
labelled() { [ -f "$work/state/labelled" ] && grep -q "^app/issues/$1/labels " "$work/state/labelled"; }

reset
jq -s . > "$work/state/pulls-app.json" <<JSON
$(pull 1 cancelled renovate '[]')
$(pull 2 red renovate '[]')
$(pull 3 pending renovate '[]')
$(pull 4 fresh renovate '[]')
$(pull 5 queued renovate '[{"name":"rebase"}]')
$(pull 6 human ryangr0 '[]')
$(pull 7 offsetold renovate '[]')
$(pull 8 offsetfresh renovate '[]')
JSON
status failure 'Has been cancelled' "$old" > "$work/state/status-cancelled.json"
status failure 'Failing after 3m' "$old" > "$work/state/status-red.json"
status failure 'Has been cancelled' "$old" | jq --arg t "$old" '.statuses += [{status: "pending", description: "Waiting to run", updated_at: $t}]' > "$work/state/status-pending.json"
status failure 'Has been cancelled' "$recent" > "$work/state/status-fresh.json"
status failure 'Has been cancelled' "$old" > "$work/state/status-queued.json"
status failure 'Has been cancelled' "$old" > "$work/state/status-human.json"
status failure 'Has been cancelled' "$old_offset" > "$work/state/status-offsetold.json"
status failure 'Has been cancelled' "$recent_offset" > "$work/state/status-offsetfresh.json"

run || fail "the retry run failed"
labelled 1 || fail "a Renovate PR whose only failures were cancelled long ago was not labelled"
labelled 7 || fail "a settled cancellation stamped with a +02:00 offset was not labelled"
for n in 2 3 4 5 6 8; do
  ! labelled "$n" || fail "PR #$n was labelled"
done
! grep -q '/repos/webgrip/old/' "$work/state/calls" || fail "an archived repository was read"
! grep -q '/commits/queued/' "$work/state/calls" || fail "a PR already labelled rebase was checked again"

grep -q '^app/issues/1/labels {"labels":\[501\]}$' "$work/state/labelled" || fail "the PR was not labelled with the repository label's id"
[ "$(grep -c '^POST /repos/webgrip/app/labels$' "$work/state/calls")" = 1 ] || fail "the repository rebase label was not created exactly once"
grep -q '^POST /repos/webgrip/app/labels$' "$work/state/calls" && ! grep -q '/orgs/webgrip/labels' "$work/state/calls" || fail "the org label was used: Renovate cannot remove an org label from a pull request"

run 1 || fail "a capped run failed"
[ "$(wc -l < "$work/state/labelled")" -eq 3 ] || fail "the retry cap did not stop at one more label"

reset
echo '[]' > "$work/state/pulls-app.json"
run || fail "an org without Renovate PRs failed"
[ ! -f "$work/state/labelled" ] || fail "an org without Renovate PRs got labels"

echo "renovate-cancelled-ci-retry: all cases pass"
