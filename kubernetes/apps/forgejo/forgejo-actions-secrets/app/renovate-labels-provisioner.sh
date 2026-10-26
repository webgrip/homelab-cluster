#!/bin/sh
set -eu

api="$FORGEJO_URL/api/v1"
admin="$ADMIN_USERNAME:$ADMIN_PASSWORD"
max_pages=20

curl() { command curl --connect-timeout 10 --max-time "${CURL_TIMEOUT:-30}" "$@"; }

existing_labels() {
  page=1
  while [ "$page" -le "$max_pages" ]; do
    batch="$(curl -fsS -u "$admin" "$api/orgs/$ORG/labels?limit=50&page=$page")"
    [ "$(printf '%s' "$batch" | jq 'length')" -gt 0 ] || return 0
    printf '%s\n' "$batch" | jq -c '.[]'
    page=$((page + 1))
  done
  echo "more than $max_pages pages of labels on $ORG" >&2
  exit 1
}

normalized_color() { printf '%s' "$1" | tr 'A-F' 'a-f' | sed 's/^#*/#/'; }

converge() {
  current="$1"
  wanted="$2"
  name="$(printf '%s' "$wanted" | jq -r '.name')"
  body="$(printf '%s' "$wanted" | jq -c '{name, color, description, exclusive: false}')"
  id="$(printf '%s' "$current" | jq -r --arg name "$name" 'select(.name == $name) | .id' | head -n 1)"
  if [ -z "$id" ]; then
    curl -fsS -o /dev/null -u "$admin" -H 'Content-Type: application/json' -X POST -d "$body" "$api/orgs/$ORG/labels"
    echo "created $ORG label $name"
    return 0
  fi
  have="$(printf '%s' "$current" | jq -c --arg name "$name" 'select(.name == $name) | {color, description}' | head -n 1)"
  have_color="$(normalized_color "$(printf '%s' "$have" | jq -r '.color')")"
  want_color="$(normalized_color "$(printf '%s' "$wanted" | jq -r '.color')")"
  if [ "$have_color" = "$want_color" ] && [ "$(printf '%s' "$have" | jq -r '.description')" = "$(printf '%s' "$wanted" | jq -r '.description')" ]; then
    return 0
  fi
  curl -fsS -o /dev/null -u "$admin" -H 'Content-Type: application/json' -X PATCH -d "$body" "$api/orgs/$ORG/labels/$id"
  echo "updated $ORG label $name"
}

retire() {
  current="$1"
  name="$2"
  id="$(printf '%s' "$current" | jq -r --arg name "$name" 'select(.name == $name) | .id' | head -n 1)"
  [ -n "$id" ] || return 0
  curl -fsS -o /dev/null -u "$admin" -X DELETE "$api/orgs/$ORG/labels/$id"
  echo "deleted $ORG label $name"
}

current="$(existing_labels)"
jq -r '.[]' "$RETIRED_FILE" | while IFS= read -r name; do
  retire "$current" "$name"
done
jq -c '.[]' "$LABELS_FILE" | while IFS= read -r wanted; do
  converge "$current" "$wanted"
done

missing="$(existing_labels | jq -s --slurpfile wanted "$LABELS_FILE" '[$wanted[0][].name] - [.[].name]')"
[ "$missing" = "[]" ] || { echo "labels still missing on $ORG after converge: $missing" >&2; exit 1; }
lingering="$(existing_labels | jq -s --slurpfile retired "$RETIRED_FILE" '[.[].name] - ([.[].name] - $retired[0])')"
[ "$lingering" = "[]" ] || { echo "retired labels still on $ORG: $lingering" >&2; exit 1; }
echo "renovate labels converged on $ORG"
