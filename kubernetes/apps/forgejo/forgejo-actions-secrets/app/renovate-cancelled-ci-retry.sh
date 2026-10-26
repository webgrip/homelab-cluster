#!/bin/sh
set -eu

api="$FORGEJO_URL/api/v1"
admin="$ADMIN_USERNAME:$ADMIN_PASSWORD"
max_pages=20
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

curl() { command curl --connect-timeout 10 --max-time "${CURL_TIMEOUT:-30}" "$@"; }

paged() {
  case "$1" in *\?*) separator='&' ;; *) separator='?' ;; esac
  page=1
  while [ "$page" -le "$max_pages" ]; do
    batch="$(curl -fsS -u "$admin" "$1${separator}limit=50&page=$page")"
    [ "$(printf '%s' "$batch" | jq 'length')" -gt 0 ] || return 0
    printf '%s\n' "$batch" | jq -c '.[]'
    page=$((page + 1))
  done
  echo "more than $max_pages pages at $1" >&2
  return 1
}

repositories() {
  paged "$api/orgs/$ORG/repos" | jq -r 'select(.archived | not) | select(.has_pull_requests) | .name'
}

renovate_pulls() {
  paged "$api/repos/$ORG/$1/pulls?state=open" \
    | jq -r --arg bot "$RENOVATE_USER" --arg label "$REBASE_LABEL" \
      'select(.user.login == $bot) | select([.labels[]?.name] | index($label) | not) | "\(.number) \(.head.sha)"'
}

only_cancelled_and_settled() {
  jq -e --argjson min "$MIN_AGE_MINUTES" '
    def epoch:
      sub("\\.[0-9]+"; "") as $t
      | if ($t | endswith("Z")) then ($t | fromdateiso8601)
        else ($t[0:19] + "Z" | fromdateiso8601)
          - (($t[20:22] | tonumber) * 3600 + ($t[23:25] | tonumber) * 60) * (if $t[19:20] == "+" then 1 else -1 end)
        end;
    def failed: select(.status == "failure" or .status == "error");
    (.statuses // []) as $s
    | ($s | length) > 0
    and ([$s[] | select(.status == "pending")] | length) == 0
    and ([$s[] | failed] | length) > 0
    and ([$s[] | failed | select(.description != "Has been cancelled")] | length) == 0
    and ([$s[] | .updated_at | epoch] | max) < (now - $min * 60)
  ' >/dev/null
}

rebase_label_id() {
  id="$(paged "$api/repos/$ORG/$1/labels" | jq -r --arg label "$REBASE_LABEL" 'select(.name == $label) | .id' | head -n 1)"
  if [ -z "$id" ]; then
    id="$(jq -nc --arg label "$REBASE_LABEL" '{name: $label, color: "#8250df", description: "Asks Renovate to rebase this pull request on its next run; Renovate removes it"}' \
      | curl -fsS -u "$admin" -H 'Content-Type: application/json' -X POST -d @- "$api/repos/$ORG/$1/labels" | jq -er '.id')"
    echo "created label $REBASE_LABEL on $ORG/$1" >&2
  fi
  printf '%s' "$id"
}

repositories > "$work/repos"
retried=0
while read -r repo; do
  renovate_pulls "$repo" > "$work/pulls"
  while read -r number sha; do
    if [ "$retried" -ge "$MAX_RETRIES" ]; then
      echo "retry cap $MAX_RETRIES reached"
      break 2
    fi
    if curl -fsS -u "$admin" "$api/repos/$ORG/$repo/commits/$sha/status" | only_cancelled_and_settled; then
      label_id="$(rebase_label_id "$repo")"
      jq -nc --argjson id "$label_id" '{labels: [$id]}' \
        | curl -fsS -o /dev/null -u "$admin" -H 'Content-Type: application/json' -X POST -d @- "$api/repos/$ORG/$repo/issues/$number/labels"
      echo "asked Renovate to rebase $ORG/$repo#$number: every failed check on $sha was cancelled"
      retried=$((retried + 1))
    fi
  done < "$work/pulls"
done < "$work/repos"
echo "renovate cancelled-CI retry done: $retried pull request(s) labelled $REBASE_LABEL"
