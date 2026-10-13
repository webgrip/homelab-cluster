#!/bin/sh
set -eu
LITELLM_MASTER_KEY=$(cat "$MASTER_KEY_FILE")
desired=$(jq -cn \
  --arg id "$TEAM_ID" \
  --arg alias "$TEAM_ALIAS" \
  --argjson groups "$MCP_ACCESS_GROUPS" \
  --arg owner "$TEAM_OWNER" \
  --arg purpose "$TEAM_PURPOSE" \
  '{team_id: $id, team_alias: $alias, models: [], max_budget: null, budget_duration: null, tpm_limit: null, rpm_limit: null, blocked: false, object_permission: {mcp_access_groups: $groups}, metadata: {owner: $owner, purpose: $purpose}}')
lookup() {
  curl -sS -o /tmp/team.json -w '%{http_code}' -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    "$LITELLM_URL/team/info?team_id=$TEAM_ID&key_limit=1"
}
in_spec() {
  jq -e --argjson want "$desired" '
    .team_info as $have
    | $have.team_alias == $want.team_alias
    and ($have.models // []) == $want.models
    and $have.max_budget == null
    and $have.tpm_limit == null
    and $have.rpm_limit == null
    and ($have.blocked // false) == false
    and (($have.object_permission.mcp_access_groups // []) | sort) == ($want.object_permission.mcp_access_groups | sort)' /tmp/team.json >/dev/null
}
admin_call() {
  code=$(printf '%s' "$desired" \
    | curl -sS -o /tmp/admin.json -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
        --data-binary @- "$LITELLM_URL/team/$1")
  if [ "$code" != 200 ]; then
    echo "team/$1 answered $code ($(jq -c '.error // .detail // "no error body"' /tmp/admin.json 2>/dev/null))" >&2
    exit 1
  fi
}
code=$(lookup)
case "$code" in
  200)
    if in_spec; then
      echo "team $TEAM_ID is registered and in spec"
      exit 0
    fi
    echo "team $TEAM_ID drifted from spec; updating" ;;
  404)
    echo "team $TEAM_ID is not registered; creating"
    admin_call new
    code=$(lookup)
    if [ "$code" = 200 ] && in_spec; then
      echo "team $TEAM_ID created in spec"
      exit 0
    fi
    echo "team $TEAM_ID was created with LiteLLM's default_team_params; clearing them" ;;
  *)
    echo "team/info answered $code; LiteLLM is not ready" >&2
    exit 1 ;;
esac
admin_call update
code=$(lookup)
if [ "$code" = 200 ] && in_spec; then
  echo "team $TEAM_ID converged: $(jq -c '.team_info | {team_alias, models, max_budget, budget_duration, tpm_limit, rpm_limit, mcp_access_groups: .object_permission.mcp_access_groups}' /tmp/team.json)"
  exit 0
fi
echo "team $TEAM_ID did not converge (team/info $code): $(jq -c '.team_info | {models, max_budget, tpm_limit, rpm_limit, blocked, mcp_access_groups: .object_permission.mcp_access_groups}' /tmp/team.json 2>/dev/null)" >&2
exit 1
