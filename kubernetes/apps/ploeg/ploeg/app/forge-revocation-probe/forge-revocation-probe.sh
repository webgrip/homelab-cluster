#!/bin/sh
set -u

forge="$FORGE_URL"
bot="$FORGE_BOT"
name="ploeg-revocation-probe-$(date +%s)"
replays=5
failures=0
token=""

pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

basic() { curl -sS --max-time 15 -u "$bot:$FORGEJO_BOT_PASSWORD" "$@"; }
with_token() { curl -sS --max-time 15 -o /dev/null -w '%{http_code}' -H "Authorization: token $token" "$1"; }
git_with_token() { curl -sS --max-time 15 -o /dev/null -w '%{http_code}' -u "$bot:$token" "$1"; }
now_ms() { awk '{ printf "%d", $1 * 1000 }' /proc/uptime; }

revoke() { basic -o /dev/null -w '%{http_code}' -X DELETE "$forge/api/v1/users/$bot/tokens/$name"; }
cleanup() { [ -n "$token" ] && revoke >/dev/null 2>&1; }
trap cleanup EXIT

echo "forge-revocation-probe forge=$forge bot=$bot version=$(curl -sS --max-time 15 "$forge/api/v1/version")"

token=$(basic -H 'Content-Type: application/json' -X POST "$forge/api/v1/users/$bot/tokens" \
  -d "{\"name\":\"$name\",\"scopes\":[\"read:user\",\"read:repository\"]}" | sed -n 's/.*"sha1":"\([0-9a-f]*\)".*/\1/p')
if [ -z "$token" ]; then
  echo "FAIL could not mint a token for $bot"
  exit 1
fi
pass "minted token $name"

code=$(with_token "$forge/api/v1/user")
[ "$code" = 200 ] && pass "before revoke: API /user -> $code" || fail "before revoke: API /user -> $code"
code=$(git_with_token "$forge/$GIT_REPO.git/info/refs?service=git-upload-pack")
[ "$code" = 200 ] && pass "before revoke: git discovery $GIT_REPO -> $code" || fail "before revoke: git discovery $GIT_REPO -> $code"

started=$(now_ms)
code=$(revoke)
revoked=$(now_ms)
[ "$code" = 204 ] && pass "revoke -> $code in $((revoked - started)) ms" || fail "revoke -> $code"

i=1
while [ "$i" -le "$replays" ]; do
  code=$(with_token "$forge/api/v1/user")
  at=$(($(now_ms) - revoked))
  [ "$code" = 401 ] && pass "replay $i: API /user -> $code at +$at ms" || fail "replay $i: API /user -> $code at +$at ms"
  code=$(git_with_token "$forge/$GIT_REPO.git/info/refs?service=git-upload-pack")
  [ "$code" = 401 ] && pass "replay $i: git discovery -> $code" || fail "replay $i: git discovery -> $code"
  i=$((i + 1))
done
token=""

if basic "$forge/api/v1/users/$bot/tokens" | grep -q "\"name\":\"$name\""; then
  fail "token $name still listed for $bot"
else
  pass "token $name no longer listed for $bot"
fi

if [ "$failures" -ne 0 ]; then
  echo "forge-revocation-probe FAILED ($failures)"
  exit 1
fi
echo "forge-revocation-probe passed"
