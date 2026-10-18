#!/bin/sh
set -eu

api="$FORGEJO_URL/api/v1"
admin="$ADMIN_USERNAME:$ADMIN_PASSWORD"
bot="$BOT_USERNAME:$BOT_PASSWORD"
wanted_scopes='["read:user","write:issue","write:repository"]'
max_repo_pages=20

curl() { command curl --connect-timeout 10 --max-time "${CURL_TIMEOUT:-30}" "$@"; }
kubectl() { timeout 30 kubectl "$@"; }

desired_user_settings() {
  jq -n '{
    login_name: env.BOT_USERNAME,
    source_id: 0,
    email: env.BOT_EMAIL,
    password: env.BOT_PASSWORD,
    must_change_password: false,
    restricted: true,
    visibility: "private",
    admin: false,
    allow_create_organization: false,
    max_repo_creation: 0
  }'
}

ensure_user() {
  code="$(curl -sS -o /dev/null -w '%{http_code}' -u "$admin" "$api/users/$BOT_USERNAME")"
  case "$code" in
    200) ;;
    404)
      echo "creating user $BOT_USERNAME"
      jq -n '{username: env.BOT_USERNAME, email: env.BOT_EMAIL, password: env.BOT_PASSWORD, must_change_password: false, restricted: true, visibility: "private"}' \
        | curl -fsS -o /dev/null -u "$admin" -H 'Content-Type: application/json' -X POST -d @- "$api/admin/users"
      ;;
    *)
      echo "unexpected status $code probing user $BOT_USERNAME" >&2
      exit 1
      ;;
  esac
  desired_user_settings \
    | curl -fsS -o /dev/null -u "$admin" -H 'Content-Type: application/json' -X PATCH -d @- "$api/admin/users/$BOT_USERNAME"
}

ensure_write_collaborator() {
  printf '%s' '{"permission":"write"}' \
    | curl -fsS -o /dev/null -u "$admin" -H 'Content-Type: application/json' -X PUT -d @- "$api/repos/$REPO/collaborators/$BOT_USERNAME"
}

reachable_repositories() {
  all='[]'
  page=1
  while [ "$page" -le "$max_repo_pages" ]; do
    batch="$(curl -fsS -u "$bot" "$api/user/repos?limit=50&page=$page")"
    [ "$(printf '%s' "$batch" | jq 'length')" -gt 0 ] || break
    all="$(printf '%s\n%s' "$all" "$batch" | jq -s 'add')"
    page=$((page + 1))
  done
  printf '%s' "$all" | jq -c '[.[] | {repo: .full_name, admin: .permissions.admin, push: .permissions.push}]'
}

assert_reaches_only_target_repo() {
  reachable="$(reachable_repositories)"
  echo "repositories $BOT_USERNAME can reach: $reachable"
  if ! printf '%s' "$reachable" \
    | jq -e --arg repo "$REPO" 'length == 1 and .[0].repo == $repo and .[0].push == true and .[0].admin == false' >/dev/null; then
    echo "access guard failed: $BOT_USERNAME must reach exactly $REPO, with write and without admin" >&2
    exit 1
  fi
}

stored_token() {
  kubectl -n "$NAMESPACE" get secret "$TOKEN_SECRET" -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true
}

token_is_current() {
  candidate="$1"
  [ -n "$candidate" ] || return 1
  login="$(curl -fsS -H "Authorization: token $candidate" "$api/user" | jq -r '.login // empty')" || return 1
  [ "$login" = "$BOT_USERNAME" ] || return 1
  last_eight="$(printf '%s' "$candidate" | tail -c 8)"
  curl -fsS -u "$bot" "$api/users/$BOT_USERNAME/tokens?limit=50" \
    | jq -e --arg name "$TOKEN_NAME" --arg last "$last_eight" --argjson want "$wanted_scopes" \
      'any(.[]; .name == $name and .token_last_eight == $last and ((.scopes // []) | sort) == ($want | sort))' >/dev/null
}

mint_token() {
  curl -sS -o /dev/null -u "$bot" -X DELETE "$api/users/$BOT_USERNAME/tokens/$TOKEN_NAME" || true
  minted="$(jq -n --arg name "$TOKEN_NAME" --argjson scopes "$wanted_scopes" '{name: $name, scopes: $scopes}' \
    | curl -fsS -u "$bot" -H 'Content-Type: application/json' -X POST -d @- "$api/users/$BOT_USERNAME/tokens" \
    | jq -r '.sha1 // empty')"
  if [ -z "$minted" ]; then
    echo "token mint failed" >&2
    exit 1
  fi
  kubectl -n "$NAMESPACE" create secret generic "$TOKEN_SECRET" --from-literal="token=$minted" --dry-run=client -o yaml \
    | kubectl apply -f - >/dev/null
  echo "minted token $TOKEN_NAME and wrote Secret $TOKEN_SECRET"
}

ensure_token() {
  if token_is_current "$(stored_token)"; then
    echo "stored token $TOKEN_NAME still authenticates with its scopes; no change"
  else
    mint_token
  fi
}

revoke_unowned_tokens() {
  curl -fsS -u "$bot" "$api/users/$BOT_USERNAME/tokens?limit=50" \
    | jq -r --arg keep "$TOKEN_NAME" '.[] | select(.name != $keep) | .name' \
    | while read -r stale; do
        [ -n "$stale" ] || continue
        curl -fsS -o /dev/null -u "$bot" -X DELETE "$api/users/$BOT_USERNAME/tokens/$(printf '%s' "$stale" | jq -sRr @uri)"
        echo "revoked token $stale"
      done
}

ensure_user
ensure_write_collaborator
assert_reaches_only_target_repo
ensure_token
revoke_unowned_tokens
echo "$BOT_USERNAME provisioner converged"
