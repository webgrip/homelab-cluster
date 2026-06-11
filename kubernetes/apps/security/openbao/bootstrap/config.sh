#!/bin/sh
# Auto-config: applies the full OpenBao configuration idempotently using the root
# token from openbao-keys. Self-heals drift, re-converges after a fresh re-init.
# SECRET_DOMAIN comes from the openbao-domain ConfigMap (envFrom); ${SECRET_DOMAIN}
# below is shell env expansion (this ks has no Flux substituteFrom).
export BAO_ADDR="http://openbao.security.svc.cluster.local:8200"

if [ -z "${ROOT_TOKEN:-}" ]; then
  echo "openbao-keys not present yet (init not finished); will retry next run"
  exit 0
fi
export BAO_TOKEN="${ROOT_TOKEN}"

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
bao policy write snapshot /config/snapshot.hcl

echo "==> kubernetes roles (ESO read, raft snapshot)"
bao write auth/kubernetes/role/external-secrets \
  bound_service_account_names=external-secrets bound_service_account_namespaces=security \
  policies=external-secrets ttl=1h >/dev/null
bao write auth/kubernetes/role/openbao-snapshot \
  bound_service_account_names=openbao-snapshot bound_service_account_namespaces=security \
  policies=snapshot ttl=10m >/dev/null

echo "==> OIDC (client_secret read from Authentik; no SOPS)"
SAT="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
AK_TOKEN="$(wget -qO- --no-check-certificate --header="Authorization: Bearer ${SAT}" \
  https://kubernetes.default.svc/api/v1/namespaces/authentik/secrets/authentik-secret 2>/dev/null \
  | grep -o '"AUTHENTIK_BOOTSTRAP_TOKEN":"[^"]*"' | sed 's/.*:"//; s/"//' | base64 -d 2>/dev/null)"
CS=""
[ -n "${AK_TOKEN}" ] && CS="$(wget -qO- --header="Authorization: Bearer ${AK_TOKEN}" \
  'http://authentik-server.authentik.svc.cluster.local/api/v3/providers/oauth2/?name=openbao-oidc' 2>/dev/null \
  | grep -o '"client_secret":"[^"]*"' | head -1 | sed 's/.*:"//; s/"//')"
if [ -n "${CS}" ] && [ -n "${SECRET_DOMAIN:-}" ]; then
  bao auth list 2>/dev/null | awk '{print $1}' | grep -q '^oidc/$' || bao auth enable oidc
  bao write auth/oidc/config \
    oidc_discovery_url="https://authentik.${SECRET_DOMAIN}/application/o/openbao/" \
    oidc_client_id=openbao oidc_client_secret="${CS}" default_role=default >/dev/null
  bao write auth/oidc/role/default \
    user_claim=sub groups_claim=groups token_policies=default \
    oidc_scopes="openid,profile,email,groups" \
    allowed_redirect_uris="https://openbao.${SECRET_DOMAIN}/ui/vault/auth/oidc/oidc/callback,http://localhost:8250/oidc/callback" >/dev/null
  echo "   oidc configured"
else
  echo "   oidc skipped (Authentik token/client_secret/domain unavailable)"
fi

echo "==> identity: external 'openbao-admins' group (policy admins) <- Authentik 'homelab-admins'"
bao write identity/group name=openbao-admins type=external policies=admins >/dev/null
GID="$(bao read -field=id identity/group/name/openbao-admins)"
ACC="$(bao auth list 2>/dev/null | awk '$1 == "oidc/" { print $3 }')"
if [ -n "${ACC}" ]; then
  bao write identity/group-alias name=homelab-admins mount_accessor="${ACC}" canonical_id="${GID}" 2>/dev/null \
    && echo "   group-alias created" || echo "   group-alias already present"
else
  echo "   oidc not enabled yet; skipping group-alias"
fi

echo "==> config converged"
