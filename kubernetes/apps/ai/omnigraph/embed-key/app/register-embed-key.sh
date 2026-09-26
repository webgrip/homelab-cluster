#!/bin/sh
set -eu
EMBED_KEY=$(cat "$EMBED_KEY_FILE")
LITELLM_MASTER_KEY=$(cat "$MASTER_KEY_FILE")
case "$EMBED_KEY" in
  sk-?*) ;;
  *) echo "omnigraph-embed-key holds no sk- key yet; failing so the retry label reschedules this Job" >&2; exit 1 ;;
esac
desired=$(jq -cn \
  --arg alias "$KEY_ALIAS" \
  --arg model "$EMBED_MODEL" \
  --arg duration "$BUDGET_DURATION" \
  --argjson budget "$MAX_BUDGET" \
  --argjson rpm "$RPM_LIMIT" \
  --argjson tpm "$TPM_LIMIT" \
  '{key_alias: $alias, models: [$model], max_budget: $budget, budget_duration: $duration, rpm_limit: $rpm, tpm_limit: $tpm, metadata: {owner: "omnigraph", purpose: "query and backfill embeddings"}}')
self_lookup() {
  curl -sS -o /tmp/self.json -w '%{http_code}' -H "Authorization: Bearer $EMBED_KEY" "$LITELLM_URL/key/info"
}
in_spec() {
  jq -e --argjson want "$desired" '
    .info.key_alias == $want.key_alias
    and .info.models == $want.models
    and .info.max_budget == $want.max_budget
    and .info.budget_duration == $want.budget_duration
    and .info.rpm_limit == $want.rpm_limit
    and .info.tpm_limit == $want.tpm_limit' /tmp/self.json >/dev/null
}
admin_call() {
  code=$(printf '%s' "$desired" | jq -c --arg key "$EMBED_KEY" '. + {key: $key}' \
    | curl -sS -o /tmp/admin.json -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
        --data-binary @- "$LITELLM_URL/key/$1")
  if [ "$code" != 200 ]; then
    echo "key/$1 answered $code ($(jq -r '.error.type // "no error type"' /tmp/admin.json 2>/dev/null))" >&2
    exit 1
  fi
}
retire_alias() {
  code=$(jq -cn --arg alias "$KEY_ALIAS" '{key_aliases: [$alias]}' \
    | curl -sS -o /tmp/retire.json -w '%{http_code}' -X POST \
        -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
        --data-binary @- "$LITELLM_URL/key/delete")
  case "$code" in
    200) echo "retired the previous key registered as $KEY_ALIAS" ;;
    404) ;;
    *) echo "key/delete answered $code" >&2; exit 1 ;;
  esac
}
code=$(self_lookup)
case "$code" in
  200)
    if in_spec; then
      echo "key $KEY_ALIAS is registered and in spec"
      exit 0
    fi
    echo "key $KEY_ALIAS drifted from spec; updating"
    admin_call update ;;
  400|401|403|404)
    echo "key $KEY_ALIAS is not registered (self-lookup $code); generating"
    retire_alias
    admin_call generate ;;
  *)
    echo "self-lookup answered $code; LiteLLM is not ready" >&2
    exit 1 ;;
esac
code=$(self_lookup)
if [ "$code" = 200 ] && in_spec; then
  echo "key $KEY_ALIAS converged: models=$(jq -c .info.models /tmp/self.json) max_budget=$(jq .info.max_budget /tmp/self.json)"
  exit 0
fi
echo "key $KEY_ALIAS did not converge (self-lookup $code)" >&2
exit 1
