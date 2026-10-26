#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
app="$repo_root/kubernetes/apps/forgejo/forgejo-actions-secrets/app"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"

cat > "$work/bin/curl" <<'FAKE'
#!/bin/sh
method=GET
body=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -d) body="$2"; shift 2 ;;
    -u|-H|-o|-w|--connect-timeout|--max-time) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
path="${url#http://forgejo.test/api/v1}"
state="$FAKE_STATE"
echo "$method ${path%%\?*}" >> "$state/calls"
case "$method $path" in
  "GET /orgs/webgrip/labels?limit=50&page=1")
    cat "$state/labels.json" ;;
  "GET /orgs/webgrip/labels?limit=50&page="*)
    echo '[]' ;;
  "POST /orgs/webgrip/labels")
    [ -f "$state/refuse-create" ] && exit 22
    next="$(jq 'map(.id) | max // 0 | . + 1' "$state/labels.json")"
    jq --argjson label "$body" --argjson id "$next" '. + [$label + {id: $id}]' "$state/labels.json" > "$state/labels.new"
    mv "$state/labels.new" "$state/labels.json" ;;
  "PATCH /orgs/webgrip/labels/"*)
    id="${path##*/}"
    jq --argjson label "$body" --argjson id "$id" 'map(if .id == $id then $label + {id: $id} else . end)' "$state/labels.json" > "$state/labels.new"
    mv "$state/labels.new" "$state/labels.json" ;;
  "DELETE /orgs/webgrip/labels/"*)
    id="${path##*/}"
    jq --argjson id "$id" 'map(select(.id != $id))' "$state/labels.json" > "$state/labels.new"
    mv "$state/labels.new" "$state/labels.json" ;;
  *)
    exit 22 ;;
esac
FAKE
chmod +x "$work/bin/curl"

run_case() {
  rm -rf "$work/state" && mkdir -p "$work/state"
  printf '%s' "$1" > "$work/state/labels.json"
  [ "${2:-}" = refuse-create ] && touch "$work/state/refuse-create"
  PATH="$work/bin:$PATH" FAKE_STATE="$work/state" FORGEJO_URL=http://forgejo.test ADMIN_USERNAME=a ADMIN_PASSWORD=p \
    ORG=webgrip LABELS_FILE="$app/renovate-labels.json" RETIRED_FILE="$app/renovate-labels-retired.json" sh "$app/renovate-labels-provisioner.sh" > "$work/state/out" 2>&1
}

fail() { echo "FAIL: $*" >&2; cat "$work/state/out" >&2; exit 1; }
writes() { grep -cE '^(POST|PATCH|DELETE) ' "$work/state/calls" || true; }
wanted_count="$(jq length "$app/renovate-labels.json")"

run_case '[]' || fail "an org without labels did not converge"
[ "$(writes)" = "$wanted_count" ] || fail "an org without labels did not get every label created"
converged="$(cat "$work/state/labels.json")"

run_case "$converged" || fail "a converged org failed"
[ "$(writes)" = 0 ] || fail "a converged org was written to"

upper="$(printf '%s' "$converged" | jq 'map(.color |= ascii_upcase)')"
run_case "$upper" || fail "an org with upper-case colours failed"
[ "$(writes)" = 0 ] || fail "a colour that differs only in case was rewritten"

drifted="$(printf '%s' "$converged" | jq 'map(if .name == "automerge" then .color = "#000000" else . end) + [{"id": 99, "name": "kept-by-someone-else", "color": "#ffffff", "description": ""}]')"
run_case "$drifted" || fail "an org with a drifted label failed"
[ "$(grep -c '^PATCH ' "$work/state/calls")" = 1 ] || fail "a drifted label was not patched exactly once"
jq -e 'any(.[]; .name == "automerge" and .color == "#2da44e")' "$work/state/labels.json" >/dev/null || fail "the drifted colour was not restored"
jq -e 'any(.[]; .name == "kept-by-someone-else")' "$work/state/labels.json" >/dev/null || fail "a label the file does not list was removed"

retired="$(printf '%s' "$converged" | jq '. + [{"id": 98, "name": "rebase", "color": "#8250df", "description": ""}]')"
run_case "$retired" || fail "an org carrying a retired label failed"
[ "$(grep -c '^DELETE /orgs/webgrip/labels/98' "$work/state/calls")" = 1 ] || fail "a retired label was not deleted"
! jq -e 'any(.[]; .name == "rebase")' "$work/state/labels.json" >/dev/null || fail "the retired label is still on the org"
! jq -e 'any(.[]; .name == "rebase")' "$app/renovate-labels.json" >/dev/null || fail "a retired label is also a wanted label"

if run_case '[]' refuse-create; then fail "a refused create passed"; fi

echo "renovate-labels-provisioner: all cases pass"
