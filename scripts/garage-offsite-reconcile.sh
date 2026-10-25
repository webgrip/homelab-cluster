#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 plan|apply [state.yaml]" >&2
  exit 64
}

mode="${1:-}"
[[ "$mode" == plan || "$mode" == apply ]] || usage
state_file="${2:-$(git rev-parse --show-toplevel)/garage-fsn1/state.yaml}"
[[ -f "$state_file" ]] || { echo "missing state file: $state_file" >&2; exit 1; }

for tool in jq yq curl bao; do
  command -v "$tool" >/dev/null 2>&1 || { echo "missing tool: $tool (run through mise exec --)" >&2; exit 1; }
done

state="$(yq -o=json '.' "$state_file")"
host="$(jq -r '.host' <<<"$state")"
pending=0
applied=0

to_bytes() {
  jq -nr --arg v "$1" '
    ($v | capture("^(?<n>[0-9]+)(?<u>B|KiB|MiB|GiB|TiB|KB|MB|GB|TB)$")) as $m
    | {B: 1, KiB: 1024, MiB: 1048576, GiB: 1073741824, TiB: 1099511627776,
       KB: 1000, MB: 1000000, GB: 1000000000, TB: 1000000000000}[$m.u] * ($m.n | tonumber)
    | floor'
}

human() {
  jq -nr --argjson b "$1" '
    if $b == null then "none"
    elif $b < 1073741824 then "\($b / 1048576 * 100 | round / 100) MiB"
    else "\($b / 1073741824 * 100 | round / 100) GiB" end'
}

remote_admin() {
  local method="$1" path="$2"
  local remote
  remote="set -a; . /etc/garage/env; set +a; curl -sS -X $method -H \"Authorization: Bearer \$GARAGE_ADMIN_TOKEN\" -H 'Content-Type: application/json' --data-binary @- -w '\n%{http_code}' $(printf '%q' "http://127.0.0.1:3903$path")"
  ssh -o BatchMode=yes "$host" "$remote"
}

local_admin() {
  local method="$1" path="$2"
  curl -sS -X "$method" -H "Authorization: Bearer $GARAGE_ADMIN_TOKEN" -H 'Content-Type: application/json' \
    --data-binary @- -w '\n%{http_code}' "$GARAGE_ADMIN_URL$path"
}

admin() {
  local method="$1" path="$2" body="${3:-}"
  local out code
  if [[ -n "${GARAGE_ADMIN_URL:-}" ]]; then
    out="$(printf '%s' "$body" | local_admin "$method" "$path")"
  else
    out="$(printf '%s' "$body" | remote_admin "$method" "$path")"
  fi
  code="${out##*$'\n'}"
  out="${out%$'\n'*}"
  if [[ "$code" != 2* ]]; then
    printf '%s %s failed with HTTP %s: %s\n' "$method" "${path%%\?*}" "$code" "$(jq -r '.message // .' <<<"$out" 2>/dev/null | head -c 300)" >&2
    return 1
  fi
  printf '%s' "$out"
}

change() {
  pending=$((pending + 1))
  printf '%s\n' "$1"
}

require_healthy() {
  local health status
  health="$(admin GET /v2/GetClusterHealth)"
  status="$(jq -r '.status' <<<"$health")"
  if [[ "$status" != healthy ]]; then
    echo "garage reports cluster status '$status'; refusing to change anything until it is healthy" >&2
    exit 3
  fi
}

bucket_info() {
  admin GET "/v2/GetBucketInfo?globalAlias=$1" 2>/dev/null || true
}

reconcile_buckets() {
  local name max_size declared headroom info bytes live_max live_objects effective note
  headroom="$(to_bytes "$(jq -r '.quotaHeadroom' <<<"$state")")"
  while IFS=$'\t' read -r name max_size; do
    info="$(bucket_info "$name")"
    if [[ -z "$info" ]]; then
      change "+ bucket $name"
      if [[ "$mode" == apply ]]; then
        info="$(admin POST /v2/CreateBucket "$(jq -nc --arg a "$name" '{globalAlias: $a}')")"
        applied=$((applied + 1))
      else
        info='{"bytes":0,"quotas":{"maxSize":null,"maxObjects":null}}'
      fi
    fi
    declared="$(to_bytes "$max_size")"
    bytes="$(jq -r '.bytes' <<<"$info")"
    live_max="$(jq -r '.quotas.maxSize' <<<"$info")"
    live_objects="$(jq -c '.quotas.maxObjects' <<<"$info")"
    effective="$declared"
    note=""
    if (( bytes + headroom > declared )); then
      effective=$(( (bytes + headroom + 1073741823) / 1073741824 * 1073741824 ))
      note=" (held above the declared $(human "$declared"): usage $(human "$bytes") + headroom $(human "$headroom"))"
    fi
    if [[ "$live_max" != "$effective" ]]; then
      change "~ quota $name: $(human "$live_max") -> $(human "$effective")$note"
      if [[ "$mode" == apply ]]; then
        admin POST "/v2/UpdateBucket?id=$(jq -r '.id' <<<"$info")" \
          "$(jq -nc --argjson s "$effective" --argjson o "$live_objects" '{quotas: {maxSize: $s, maxObjects: $o}}')" >/dev/null
        applied=$((applied + 1))
      fi
    elif [[ -n "$note" ]]; then
      printf '= quota %s: %s%s\n' "$name" "$(human "$effective")" "$note"
    fi
  done < <(jq -r '.buckets[] | [.name, .maxSize] | @tsv' <<<"$state")
}

vault_put_key() {
  local key_json="$1" path="$2" bucket="$3"
  jq -r '.secretAccessKey' <<<"$key_json" | bao kv put "secret/$path" \
    S3_ACCESS_KEY_ID="$(jq -r '.accessKeyId' <<<"$key_json")" \
    S3_SECRET_ACCESS_KEY=- \
    S3_REGION="$(jq -r '.region' <<<"$state")" \
    S3_ENDPOINT="$(jq -r '.endpoint' <<<"$state")" \
    S3_BUCKET="$bucket" >/dev/null
}

reconcile_key_identity() {
  local name="$1" path="$2" bucket="$3" keys="$4" matches id vault_id key_json
  matches="$(jq -r --arg n "$name" '[.[] | select(.name == $n)] | length' <<<"$keys")"
  if (( matches > 1 )); then
    echo "key name '$name' is used by $matches Garage keys; resolve the duplicate by hand before reconciling" >&2
    exit 4
  fi
  if (( matches == 0 )); then
    change "+ key $name${path:+ -> secret/$path}"
    if [[ "$mode" == apply ]]; then
      key_json="$(admin POST /v2/CreateKey "$(jq -nc --arg n "$name" '{name: $n}')")"
      applied=$((applied + 1))
      [[ -n "$path" ]] && vault_put_key "$key_json" "$path" "$bucket"
      unset key_json
    fi
    return 0
  fi
  [[ -n "$path" ]] || return 0
  id="$(jq -r --arg n "$name" '.[] | select(.name == $n) | .id' <<<"$keys")"
  vault_id="$(bao kv get -field=S3_ACCESS_KEY_ID "secret/$path" 2>/dev/null || true)"
  if [[ -z "$vault_id" ]]; then
    change "+ vault secret/$path for existing key $name"
    if [[ "$mode" == apply ]]; then
      key_json="$(admin GET "/v2/GetKeyInfo?id=$id&showSecretKey=true")"
      vault_put_key "$key_json" "$path" "$bucket"
      unset key_json
      applied=$((applied + 1))
    fi
  elif [[ "$vault_id" != "$id" ]]; then
    echo "secret/$path holds access key $vault_id but Garage key '$name' is $id; refusing to guess which is right" >&2
    exit 5
  fi
}

reconcile_keys() {
  local keys name path bucket
  keys="$(admin GET /v2/ListKeys)"
  while IFS=$'\t' read -r name path bucket; do
    reconcile_key_identity "$name" "$path" "$bucket" "$keys"
  done < <(jq -r '.keys[] | [.name, (.vault.path // ""), (.vault.bucket // "")] | @tsv' <<<"$state")
}

reconcile_grants() {
  local keys key_name key_id bucket info live want allow deny
  keys="$(admin GET /v2/ListKeys)"
  while IFS=$'\t' read -r key_name bucket want; do
    key_id="$(jq -r --arg n "$key_name" 'first(.[] | select(.name == $n) | .id) // ""' <<<"$keys")"
    info="$(bucket_info "$bucket")"
    if [[ -z "$key_id" || -z "$info" ]]; then
      [[ "$want" != '{"read":false,"write":false,"owner":false}' ]] && change "~ grant $key_name on $bucket: $(jq -r 'to_entries | map(select(.value) | .key) | join(",")' <<<"$want")"
      continue
    fi
    live="$(jq -c --arg k "$key_id" 'first(.keys[] | select(.accessKeyId == $k) | .permissions) // {"read":false,"write":false,"owner":false}' <<<"$info")"
    allow="$(jq -nc --argjson w "$want" --argjson l "$live" '{read: ($w.read and ($l.read | not)), write: ($w.write and ($l.write | not)), owner: ($w.owner and ($l.owner | not))}')"
    deny="$(jq -nc --argjson w "$want" --argjson l "$live" '{read: (($w.read | not) and $l.read), write: (($w.write | not) and $l.write), owner: (($w.owner | not) and $l.owner)}')"
    if [[ "$allow" != '{"read":false,"write":false,"owner":false}' ]]; then
      change "~ allow $key_name on $bucket: +$(jq -r 'to_entries | map(select(.value) | .key) | join(",+")' <<<"$allow")"
      if [[ "$mode" == apply ]]; then
        admin POST /v2/AllowBucketKey "$(jq -nc --arg b "$(jq -r '.id' <<<"$info")" --arg k "$key_id" --argjson p "$allow" '{bucketId: $b, accessKeyId: $k, permissions: $p}')" >/dev/null
        applied=$((applied + 1))
      fi
    fi
    if [[ "$deny" != '{"read":false,"write":false,"owner":false}' ]]; then
      change "~ deny $key_name on $bucket: -$(jq -r 'to_entries | map(select(.value) | .key) | join(",-")' <<<"$deny")"
      if [[ "$mode" == apply ]]; then
        admin POST /v2/DenyBucketKey "$(jq -nc --arg b "$(jq -r '.id' <<<"$info")" --arg k "$key_id" --argjson p "$deny" '{bucketId: $b, accessKeyId: $k, permissions: $p}')" >/dev/null
        applied=$((applied + 1))
      fi
    fi
  done < <(jq -r '
      [.buckets[].name] as $buckets
      | .keys[] | .name as $k | (.grants // {}) as $g
      | $buckets[] | . as $b
      | [$k, $b, ({read: (($g[$b] // []) | index("read") != null),
                   write: (($g[$b] // []) | index("write") != null),
                   owner: (($g[$b] // []) | index("owner") != null)} | tojson)]
      | @tsv' <<<"$state")
}

report_unmanaged() {
  local buckets keys
  buckets="$(admin GET /v2/ListBuckets | jq -r --argjson s "$state" '[.[] | (.globalAliases // [])[]] - [$s.buckets[].name] | .[]')"
  keys="$(admin GET /v2/ListKeys | jq -r --argjson s "$state" '[.[].name] - [$s.keys[].name] | unique | .[]')"
  [[ -n "$buckets" ]] && printf 'unmanaged bucket, left untouched: %s\n' $buckets
  [[ -n "$keys" ]] && printf 'unmanaged key, left untouched: %s\n' $keys
  return 0
}

require_healthy
reconcile_buckets
reconcile_keys
reconcile_grants
report_unmanaged

if [[ "$mode" == plan ]]; then
  if (( pending > 0 )); then
    echo "plan: $pending change(s) pending; run: mise exec -- just garage-offsite-apply"
    exit 2
  fi
  echo "plan: garage-fsn1 matches $state_file"
else
  echo "apply: $applied change(s) applied; verifying"
  exec "$0" plan "$state_file"
fi
