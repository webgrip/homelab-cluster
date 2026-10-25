#!/usr/bin/env bash
set -euo pipefail

device_ips="$(kubectl get secret "$STATE_SECRET" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.data.device_ips // empty' | base64 -d 2>/dev/null || true)"
[[ -n "$device_ips" ]] || { echo "${STATE_SECRET} holds no device_ips yet; the gateway has not joined the tailnet"; exit 0; }

address="$(jq -r '[.[] | select(test("^100\\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\\.[0-9]+\\.[0-9]+$"))] | first // empty' <<<"$device_ips")"
[[ -n "$address" ]] || { echo "no tailnet IPv4 address in ${device_ips}" >&2; exit 1; }

desired="$(jq -cS -n --arg ip "$address" --arg name "$GATEWAY_HOSTNAME" --argjson ttl "$RECORD_TTL" '
  [{dnsName: $name, recordType: "A", recordTTL: $ttl, targets: [$ip],
    providerSpecific: [{name: "external-dns.alpha.kubernetes.io/cloudflare-proxied", value: "false"}]}]')"

published="$(kubectl get dnsendpoint "$ENDPOINT_NAME" -n "$NAMESPACE" -o json 2>/dev/null | jq -cS '.spec.endpoints' || echo null)"
if [[ "$published" == "$desired" ]]; then
  echo "unchanged: ${GATEWAY_HOSTNAME} -> ${address}"
  exit 0
fi

jq -n --arg name "$ENDPOINT_NAME" --arg ns "$NAMESPACE" --argjson endpoints "$desired" '{
  apiVersion: "externaldns.k8s.io/v1alpha1",
  kind: "DNSEndpoint",
  metadata: {name: $name, namespace: $ns, labels: {"app.kubernetes.io/name": "unfold-gateway-address"}},
  spec: {endpoints: $endpoints}}' \
  | kubectl apply --server-side --field-manager=unfold-gateway-address --force-conflicts -f - >/dev/null
echo "published ${GATEWAY_HOSTNAME} -> ${address}"
