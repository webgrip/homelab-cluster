#!/usr/bin/env bash
set -euo pipefail

trace_urls=("https://1.1.1.1/cdn-cgi/trace" "https://1.0.0.1/cdn-cgi/trace")

public_ipv4_from() {
  curl -4 -fsS --connect-timeout 5 --max-time 10 "$1" | sed -n 's/^ip=//p'
}

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

address=""
for url in "${trace_urls[@]}"; do
  address="$(public_ipv4_from "$url" || true)"
  [[ -n "$address" ]] && break
done
is_public_ipv4 "$address" \
  || { echo "Cloudflare trace gave no public IPv4 address (got '${address}'); keeping the published record" >&2; exit 1; }

desired="$(jq -cS -n --arg ip "$address" --arg names "$WAN_HOSTNAMES" --argjson ttl "$RECORD_TTL" '
  $names | split(",") | map(gsub("\\s"; "") | select(length > 0)) | unique
  | map({dnsName: ., recordType: "A", recordTTL: $ttl, targets: [$ip],
         providerSpecific: [{name: "external-dns.alpha.kubernetes.io/cloudflare-proxied", value: "false"}]})')"
[[ "$(jq 'length' <<<"$desired")" -gt 0 ]] || { echo "WAN_HOSTNAMES names no hostname" >&2; exit 1; }

published="$(kubectl get dnsendpoint "$ENDPOINT_NAME" -n "$NAMESPACE" -o json 2>/dev/null | jq -cS '.spec.endpoints' || echo null)"
if [[ "$published" == "$desired" ]]; then
  echo "unchanged: ${address} for ${WAN_HOSTNAMES}"
  exit 0
fi

jq -n --arg name "$ENDPOINT_NAME" --arg ns "$NAMESPACE" --argjson endpoints "$desired" '{
  apiVersion: "externaldns.k8s.io/v1alpha1",
  kind: "DNSEndpoint",
  metadata: {name: $name, namespace: $ns, labels: {"app.kubernetes.io/name": "wan-address"}},
  spec: {endpoints: $endpoints}}' \
  | kubectl apply --server-side --field-manager=wan-address --force-conflicts -f - >/dev/null
echo "published ${address} for ${WAN_HOSTNAMES}"
