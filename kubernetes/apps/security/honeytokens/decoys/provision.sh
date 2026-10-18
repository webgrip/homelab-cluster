#!/bin/sh
set -eu

api="$FORGEJO_URL/api/v1"
admin="$ADMIN_USERNAME:$ADMIN_PASSWORD"

fail() {
  echo "$1" >&2
  exit 1
}

forgejo() {
  method=$1
  path=$2
  shift 2
  curl -sS -o /tmp/body.json -w '%{http_code}' -u "$admin" -X "$method" \
    -H 'Content-Type: application/json' "$@" "$api$path"
}

ensure_canary_user() {
  user=$1
  code=$(forgejo GET "/users/$user")
  case "$code" in
    200) ;;
    404)
      password=$(head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)
      body=$(jq -cn --arg u "$user" --arg e "$user@$EMAIL_DOMAIN" --arg p "$password" \
        '{username: $u, email: $e, password: $p, must_change_password: false, restricted: true, visibility: "private"}')
      code=$(forgejo POST /admin/users -d "$body")
      [ "$code" = 201 ] || fail "creating $user answered $code"
      echo "created canary user $user" >&2 ;;
    *) fail "looking up $user answered $code" ;;
  esac
  code=$(forgejo PATCH "/admin/users/$user" \
    -d '{"restricted": true, "visibility": "private", "max_repo_creation": 0, "admin": false, "allow_create_organization": false}')
  [ "$code" = 200 ] || fail "restricting $user answered $code"
}

stored_token() {
  kubectl -n "$NAMESPACE" get secret "$TOKEN_SECRET" -o "jsonpath={.data.$1}" 2>/dev/null | base64 -d 2>/dev/null || true
}

current_token() {
  placement=$1
  user=$2
  stored=$(stored_token "$placement")
  code=$(forgejo GET "/users/$user/tokens")
  [ "$code" = 200 ] || fail "listing tokens of $user answered $code"
  live_last_eight=$(jq -r --arg n "$TOKEN_NAME" '.[] | select(.name == $n) | .token_last_eight' /tmp/body.json)
  if [ -n "$stored" ] && [ -n "$live_last_eight" ] && [ "${stored#"${stored%????????}"}" = "$live_last_eight" ]; then
    printf '%s' "$stored"
    return
  fi
  code=$(forgejo DELETE "/users/$user/tokens/$TOKEN_NAME")
  case "$code" in
    204|404) ;;
    *) fail "retiring the token of $user answered $code" ;;
  esac
  code=$(forgejo POST "/users/$user/tokens" -d "$(jq -cn --arg n "$TOKEN_NAME" '{name: $n, scopes: ["read:user", "read:repository"]}')")
  [ "$code" = 201 ] || fail "minting a token for $user answered $code"
  minted=$(jq -r '.sha1 // empty' /tmp/body.json)
  [ -n "$minted" ] || fail "the token minted for $user came back empty"
  echo "minted a fresh decoy token for $user" >&2
  printf '%s' "$minted"
}

ensure_canary_user "$WORKSPACE_USER"
ensure_canary_user "$REPOSITORY_USER"
ensure_canary_user "$ESCAPE_USER"

workspace_token=$(current_token workspace "$WORKSPACE_USER")
repository_token=$(current_token repository "$REPOSITORY_USER")
escape_token=$(current_token escape "$ESCAPE_USER")

kubectl -n "$NAMESPACE" create secret generic "$TOKEN_SECRET" \
  --from-literal="workspace=$workspace_token" \
  --from-literal="repository=$repository_token" \
  --from-literal="escape=$escape_token" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
echo "Secret $TOKEN_SECRET holds the three decoy Forgejo tokens"
