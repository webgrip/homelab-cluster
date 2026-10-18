#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
provisioner="${PLOEG_RELEASE_PROVISIONER:-$repo_root/kubernetes/apps/forgejo/forgejo-actions-secrets/app/ploeg-release-provisioner.sh}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"

cat > "$work/bin/curl" <<'FAKE'
#!/bin/sh
method=GET
out=""
write_out=""
auth=""
header=""
body=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -o) out="$2"; shift 2 ;;
    -w) write_out="$2"; shift 2 ;;
    -u) auth="$2"; shift 2 ;;
    -H) header="$header|$2"; shift 2 ;;
    -d) [ "$2" = "@-" ] && body="$(cat)"; shift 2 ;;
    --connect-timeout|--max-time) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
path="${url#*/api/v1}"
echo "$method $path" >> "$FAKE_DIR/calls"
status=200
response='{}'
case "$method $path" in
  "GET /users/ploeg-release")
    [ "$FAKE_USER_EXISTS" = yes ] || status=404 ;;
  "GET /user")
    case "$header" in
      *"token $FAKE_LIVE_TOKEN"*) response='{"login":"ploeg-release"}' ;;
      *) status=401 ;;
    esac ;;
  "GET /user/repos?limit=50&page=1") response="$FAKE_REPOS_PAGE1" ;;
  "GET /user/repos?limit=50&page=2") response="${FAKE_REPOS_PAGE2:-[]}" ;;
  "GET /user/repos?"*) response='[]' ;;
  "GET /users/ploeg-release/tokens?limit=50")
    response="[{\"name\":\"ploeg-release-hook\",\"token_last_eight\":\"$(printf '%s' "$FAKE_LIVE_TOKEN" | tail -c 8)\",\"scopes\":[\"write:repository\",\"write:issue\",\"read:user\"]}]" ;;
  "POST /users/ploeg-release/tokens") response='{"sha1":"freshly-minted-token-0001"}' ;;
esac
if [ -n "$write_out" ]; then
  printf '%s' "$status"
  exit 0
fi
if [ "$status" -ge 400 ]; then
  echo "curl: (22) The requested URL returned error: $status" >&2
  exit 22
fi
if [ "$out" != /dev/null ]; then
  printf '%s' "$response"
fi
FAKE

cat > "$work/bin/kubectl" <<'FAKE'
#!/bin/sh
case "$*" in
  *"get secret"*)
    [ -n "$FAKE_STORED_TOKEN" ] || exit 1
    printf '%s' "$FAKE_STORED_TOKEN" | base64 ;;
  *"create secret"*) echo "$*" ;;
  *"apply -f -"*) cat > "$FAKE_DIR/applied" ;;
esac
FAKE
chmod +x "$work/bin/curl" "$work/bin/kubectl"

unfold_write='{"full_name":"webgrip/unfold","permissions":{"admin":false,"push":true,"pull":true}}'
unfold_admin='{"full_name":"webgrip/unfold","permissions":{"admin":true,"push":true,"pull":true}}'
other_read='{"full_name":"webgrip/homelab-cluster","permissions":{"admin":false,"push":false,"pull":true}}'

failures=0
fail() {
  echo "FAIL: $1"
  failures=$((failures + 1))
}

run_case() {
  rm -f "$work/calls" "$work/applied" "$work/output"
  : > "$work/calls"
  set +e
  env PATH="$work/bin:$PATH" FAKE_DIR="$work" \
    FORGEJO_URL=http://forgejo.test REPO=webgrip/unfold NAMESPACE=forgejo \
    BOT_USERNAME=ploeg-release BOT_EMAIL=ploeg-release@webgrip.dev BOT_PASSWORD=bot-pass \
    ADMIN_USERNAME=admin ADMIN_PASSWORD=admin-pass \
    TOKEN_NAME=ploeg-release-hook TOKEN_SECRET=ploeg-release-token \
    FAKE_USER_EXISTS="$1" FAKE_STORED_TOKEN="$2" FAKE_LIVE_TOKEN="$3" \
    FAKE_REPOS_PAGE1="$4" FAKE_REPOS_PAGE2="${5:-[]}" \
    sh "$provisioner" > "$work/output" 2>&1
  exit_code=$?
  set -e
}

expect_pass() {
  [ "$exit_code" -eq 0 ] || { fail "$1: expected exit 0, got $exit_code"; cat "$work/output"; }
}

expect_guard_failure() {
  [ "$exit_code" -ne 0 ] || fail "$1: expected the access guard to fail the run"
  grep -q 'access guard failed' "$work/output" || { fail "$1: missing access guard message"; cat "$work/output"; }
  if grep -q '^POST /users/ploeg-release/tokens' "$work/calls"; then
    fail "$1: minted a token although the access guard failed"
  fi
}

minted() { grep -q '^POST /users/ploeg-release/tokens' "$work/calls"; }

run_case yes stored-token-abcdefgh stored-token-abcdefgh "[$unfold_write]"
expect_pass "converged state"
minted && fail "converged state: a valid stored token was re-minted"
grep -q 'no change' "$work/output" || fail "converged state: expected the no-change line"

run_case yes stored-token-abcdefgh live-token-ijklmnop "[$unfold_write]"
expect_pass "rejected stored token"
minted || fail "rejected stored token: expected a fresh mint"
grep -q 'token=freshly-minted-token-0001' "$work/applied" 2>/dev/null || fail "rejected stored token: Secret not written"

run_case yes "" stored-token-abcdefgh "[$unfold_write]"
expect_pass "missing Secret"
minted || fail "missing Secret: expected a fresh mint"

run_case no "" "" "[$unfold_write]"
expect_pass "deleted user"
grep -q '^POST /admin/users$' "$work/calls" || fail "deleted user: user was not recreated"
minted || fail "deleted user: expected a fresh mint"

run_case yes stored-token-abcdefgh stored-token-abcdefgh "[$unfold_write,$other_read]"
expect_guard_failure "a second repository"

run_case yes stored-token-abcdefgh stored-token-abcdefgh "[$unfold_write]" "[$other_read]"
expect_guard_failure "a second repository on page two"

run_case yes stored-token-abcdefgh stored-token-abcdefgh "[$unfold_admin]"
expect_guard_failure "admin on the target repository"

run_case yes stored-token-abcdefgh stored-token-abcdefgh "[]"
expect_guard_failure "no access to the target repository"

if [ "$failures" -gt 0 ]; then
  exit 1
fi
echo "PASS: ploeg-release provisioner keeps a valid token, re-mints a rejected one, recreates a deleted user, and fails unless it reaches exactly webgrip/unfold with write"
