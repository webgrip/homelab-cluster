#!/usr/bin/env bash
set -euo pipefail

is_public_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  local a=$((10#${BASH_REMATCH[1]})) b=$((10#${BASH_REMATCH[2]}))
  local c=$((10#${BASH_REMATCH[3]})) d=$((10#${BASH_REMATCH[4]}))
  ((a <= 255 && b <= 255 && c <= 255 && d <= 255)) || return 1
  ((a == 0 || a == 10 || a == 127 || a >= 224)) && return 1
  ((a == 100 && b >= 64 && b <= 127)) && return 1
  ((a == 169 && b == 254)) && return 1
  ((a == 172 && b >= 16 && b <= 31)) && return 1
  ((a == 192 && b == 168)) && return 1
  return 0
}

address_from_secret() {
  jq -r --arg key "$1" '.data[$key] // empty' <<<"$secret" | base64 -d 2>/dev/null | tr -d '\r\n ' || true
}

secret="$(kubectl get secret "$ADDRESS_SECRET" -n "$NAMESPACE" -o json 2>/dev/null || true)"
[[ -n "$secret" ]] || { echo "${ADDRESS_SECRET} does not exist yet; the Unfold apply has not written an address; keeping the published record"; exit 0; }

published_endpoints="$(kubectl get dnsendpoint "$ENDPOINT_NAME" -n "$NAMESPACE" -o json 2>/dev/null | jq -c '.spec.endpoints // []' || echo '[]')"

production="$(address_from_secret ipv4)"
if ! is_public_ipv4 "$production"; then
  production="$(jq -r --arg name "$PRODUCTION_HOSTNAME" '[.[] | select(.dnsName == $name) | .targets[0]][0] // empty' <<<"$published_endpoints")"
fi
drill="$(address_from_secret drill_ipv4)"
is_public_ipv4 "$drill" || drill=""

[[ -n "$production" ]] || { echo "no production address in ${ADDRESS_SECRET} or the published record; nothing to publish"; exit 0; }

desired="$(jq -cS -n --arg prod_name "$PRODUCTION_HOSTNAME" --arg prod_ip "$production" \
  --arg drill_name "$DRILL_HOSTNAME" --arg drill_ip "$drill" --argjson ttl "$RECORD_TTL" '
  def record($name; $ip): {dnsName: $name, recordType: "A", recordTTL: $ttl, targets: [$ip],
    providerSpecific: [{name: "external-dns.alpha.kubernetes.io/cloudflare-proxied", value: "false"}]};
  [record($prod_name; $prod_ip)] + (if $drill_ip == "" then [] else [record($drill_name; $drill_ip)] end)')"

if [[ "$(jq -cS . <<<"$published_endpoints")" == "$desired" ]]; then
  echo "unchanged: ${PRODUCTION_HOSTNAME} -> ${production}${drill:+, ${DRILL_HOSTNAME} -> ${drill}}"
  exit 0
fi

jq -n --arg name "$ENDPOINT_NAME" --arg ns "$NAMESPACE" --argjson endpoints "$desired" '{
  apiVersion: "externaldns.k8s.io/v1alpha1",
  kind: "DNSEndpoint",
  metadata: {name: $name, namespace: $ns, labels: {"app.kubernetes.io/name": "unfold-headscale-address"}},
  spec: {endpoints: $endpoints}}' \
  | kubectl apply --server-side --field-manager=unfold-headscale-address --force-conflicts -f - >/dev/null
echo "published ${PRODUCTION_HOSTNAME} -> ${production}${drill:+, ${DRILL_HOSTNAME} -> ${drill}}"
