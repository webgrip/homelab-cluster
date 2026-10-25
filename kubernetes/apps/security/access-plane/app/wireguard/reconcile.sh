#!/usr/bin/env bash
set -euo pipefail

: "${WG_ENDPOINT:?WG_ENDPOINT must name the host:port devices connect to}"
: "${WG_PEER_DNS:?WG_PEER_DNS must name the resolver devices use}"
: "${WG_ALLOWED_IPS:?WG_ALLOWED_IPS must name the networks routed through the tunnel}"

api="${OPNSENSE_URL}/api/wireguard"
peer_prefix="ap-"

opnsense() {
  local method="$1" path="$2" body="${3:-}"
  local args=(--fail-with-body -sS --connect-timeout 10 --max-time 30
    --pinnedpubkey "$OPNSENSE_PINNED_PUBKEY" --insecure
    -u "${OPNSENSE_API_KEY}:${OPNSENSE_API_SECRET}" -X "$method")
  if [[ -n "$body" ]]; then
    args+=(-H 'Content-Type: application/json' -d "$body")
  fi
  curl "${args[@]}" "${api}/${path}"
}

expect_saved() {
  jq -e '.result == "saved" or .result == "deleted"' >/dev/null <<<"$1" \
    || { echo "OPNsense refused: $1" >&2; exit 1; }
}

desired="$(yq -o=json '.' "$MODEL_PEOPLE" | jq --arg p "$peer_prefix" '[.people[]
  | select(.kind != "machine" and .status == "active")
  | . as $person
  | (.wireguard // [])[]
  | {name: ($p + $person.id + "-" + .device), pubkey: .public_key}]')"

servers="$(opnsense GET client/listServers)"
if [[ -n "${WG_SERVER_NAME:-}" ]]; then
  server_uuid="$(jq -r --arg n "$WG_SERVER_NAME" '.rows[] | select(.name == $n) | .uuid' <<<"$servers")"
else
  [[ "$(jq '.rows | length' <<<"$servers")" == 1 ]] \
    || { echo "OPNsense has $(jq '.rows | length' <<<"$servers") WireGuard instances; set WG_SERVER_NAME" >&2; exit 1; }
  server_uuid="$(jq -r '.rows[0].uuid' <<<"$servers")"
fi
[[ -n "$server_uuid" ]] || { echo "WireGuard instance ${WG_SERVER_NAME:-} not found" >&2; exit 1; }
server_name="$(jq -r --arg u "$server_uuid" '.rows[] | select(.uuid == $u) | .name' <<<"$servers")"

existing="$(opnsense POST client/searchClient '{"current":1,"rowCount":-1}' \
  | jq --arg p "$peer_prefix" '[.rows[] | select(.name | startswith($p))]')"

changed=0

while read -r peer; do
  name="$(jq -r .name <<<"$peer")"
  pubkey="$(jq -r .pubkey <<<"$peer")"
  current="$(jq --arg n "$name" '.[] | select(.name == $n)' <<<"$existing")"
  if [[ -z "$current" ]]; then
    address="$(opnsense GET "client/getServerInfo/${server_uuid}" | jq -r '.address | split(",") | map(select(contains(":") | not)) | first // empty')"
    [[ -n "$address" ]] || { echo "no free tunnel address on ${server_name}" >&2; exit 1; }
    body="$(jq -nc --arg name "$name" --arg pubkey "$pubkey" --arg address "$address" --arg server "$server_uuid" \
      '{client: {enabled: "1", name: $name, pubkey: $pubkey, tunneladdress: $address, servers: $server, keepalive: "25"}}')"
    expect_saved "$(opnsense POST client/addClient "$body")"
    echo "added ${name} at ${address}"
    changed=1
    continue
  fi
  in_sync="$(jq --arg pubkey "$pubkey" --arg name "$server_name" --arg uuid "$server_uuid" \
    '.pubkey == $pubkey and .enabled == "1" and ((.servers // "") | split(",") | map(ltrimstr(" ")) | any(. == $name or . == $uuid))' <<<"$current")"
  if [[ "$in_sync" != "true" ]]; then
    uuid="$(jq -r .uuid <<<"$current")"
    address="$(jq -r .tunneladdress <<<"$current")"
    body="$(jq -nc --arg name "$name" --arg pubkey "$pubkey" --arg address "$address" --arg server "$server_uuid" \
      '{client: {enabled: "1", name: $name, pubkey: $pubkey, tunneladdress: $address, servers: $server, keepalive: "25"}}')"
    expect_saved "$(opnsense POST "client/setClient/${uuid}" "$body")"
    echo "updated ${name}"
    changed=1
  fi
done < <(jq -c '.[]' <<<"$desired")

while read -r stale; do
  [[ -n "$stale" ]] || continue
  uuid="$(jq -r .uuid <<<"$stale")"
  expect_saved "$(opnsense POST "client/delClient/${uuid}" '{}')"
  echo "removed $(jq -r .name <<<"$stale")"
  changed=1
done < <(jq -c --argjson desired "$desired" '.[] | select(.name as $n | $desired | map(.name) | index($n) | not)' <<<"$existing")

if [[ "$changed" == 1 ]]; then
  jq -e '.status == "ok"' >/dev/null <<<"$(opnsense POST service/reconfigure '{}')" \
    || { echo "OPNsense did not apply the WireGuard change" >&2; exit 1; }
  echo "applied on ${server_name}"
fi

info="$(opnsense GET "client/getServerInfo/${server_uuid}")"
peers="$(opnsense POST client/searchClient '{"current":1,"rowCount":-1}' \
  | jq --arg p "$peer_prefix" '[.rows[] | select(.name | startswith($p))]')"
configs="$(jq -n --argjson peers "$peers" --argjson info "$info" \
  --arg endpoint "$WG_ENDPOINT" --arg dns "$WG_PEER_DNS" --arg allowed "$WG_ALLOWED_IPS" '
  [$peers[] | {key: .name, value: ([
    "[Interface]",
    "PrivateKey = <the private key that stays on this device>",
    "Address = \(.tunneladdress)",
    "DNS = \($dns)",
    (if ($info.mtu // "") != "" then "MTU = \($info.mtu)" else empty end),
    "",
    "[Peer]",
    "PublicKey = \($info.pubkey)",
    "Endpoint = \($endpoint)",
    "AllowedIPs = \($allowed)",
    "PersistentKeepalive = 25",
    ""] | join("\n"))}] | from_entries')"

kubectl create configmap "$PEER_CONFIGMAP" -n "$NAMESPACE" --dry-run=client -o json \
  | jq --argjson data "$configs" '.data = $data' \
  | kubectl apply -f - >/dev/null
echo "wrote $(jq 'length' <<<"$configs") peer configurations to ConfigMap ${PEER_CONFIGMAP}"
