#!/bin/sh
# Auto-config: applies the full OpenBao configuration idempotently using the root
# token from the openbao-keys Secret. Self-heals drift and re-converges after a
# fresh re-init. No human steps, no SOPS.  (OIDC auth config lives elsewhere.)
export BAO_ADDR="http://openbao.security.svc.cluster.local:8200"

if [ -z "${ROOT_TOKEN:-}" ]; then
  echo "openbao-keys not present yet (init not finished); will retry next run"
  exit 0
fi
export BAO_TOKEN="${ROOT_TOKEN}"

# Wait until unsealed (the unsealer runs independently).
n=0
until bao status >/dev/null 2>&1; do
  n=$((n + 1)); [ "$n" -gt 40 ] && { echo "still sealed; retry next run"; exit 0; }
  sleep 3
done

echo "==> KV v2 at secret/"
bao secrets list -format=json 2>/dev/null | grep -q '"secret/"' || bao secrets enable -path=secret kv-v2

echo "==> kubernetes auth"
bao auth list -format=json 2>/dev/null | grep -q '"kubernetes/"' || bao auth enable kubernetes
bao write auth/kubernetes/config kubernetes_host="https://kubernetes.default.svc" >/dev/null

echo "==> policies"
bao policy write admins /config/admins.hcl
bao policy write external-secrets /config/external-secrets.hcl

echo "==> kubernetes role for ESO"
bao write auth/kubernetes/role/external-secrets \
  bound_service_account_names=external-secrets \
  bound_service_account_namespaces=security \
  policies=external-secrets ttl=1h >/dev/null

echo "==> identity: external 'openbao-admins' group (policy admins) <- Authentik 'homelab-admins'"
bao write identity/group name=openbao-admins type=external policies=admins >/dev/null
GID="$(bao read -field=id identity/group/name/openbao-admins)"
ACC="$(bao auth list 2>/dev/null | awk '$1 == "oidc/" { print $3 }')"
if [ -n "${ACC}" ]; then
  bao write identity/group-alias name=homelab-admins mount_accessor="${ACC}" canonical_id="${GID}" 2>/dev/null \
    && echo "   group-alias created" || echo "   group-alias already present"
else
  echo "   oidc auth not enabled yet; skipping group-alias"
fi

echo "==> config converged"
