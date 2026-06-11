#!/bin/sh
# Ongoing reconcile — runs as the scoped config-admin role via Kubernetes auth (NO root).
# Re-asserts policies, k8s auth roles, identity, and OIDC config idempotently. The one-time
# root-only setup (KV mount, enabling auth methods, revoking root) is done by init.sh on a
# fresh cluster, or by the one-time transition on an already-initialised instance.
export BAO_ADDR="http://openbao.security.svc.cluster.local:8200"

JWT="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
BAO_TOKEN="$(bao write -field=token auth/kubernetes/login role=openbao-config jwt="${JWT}" 2>/dev/null)"
if [ -z "${BAO_TOKEN}" ]; then
  echo "config-admin role not present yet (run the one-time bootstrap); retry next run"
  exit 0
fi
export BAO_TOKEN

n=0
until bao status >/dev/null 2>&1; do
  n=$((n + 1)); [ "$n" -gt 40 ] && { echo "still sealed; retry next run"; exit 0; }
  sleep 3
done

echo "==> policies"
bao policy write admins /scripts/admins.hcl
bao policy write external-secrets /scripts/external-secrets.hcl
bao policy write snapshot /scripts/snapshot.hcl
bao policy write external-secrets-push /scripts/push.hcl
bao policy write config-admin /scripts/config-admin.hcl

echo "==> kubernetes roles"
bao write auth/kubernetes/role/external-secrets \
  bound_service_account_names=external-secrets bound_service_account_namespaces=security \
  policies=external-secrets ttl=1h >/dev/null
bao write auth/kubernetes/role/external-secrets-push \
  bound_service_account_names=external-secrets bound_service_account_namespaces=security \
  policies=external-secrets-push ttl=1h >/dev/null
bao write auth/kubernetes/role/openbao-snapshot \
  bound_service_account_names=openbao-snapshot bound_service_account_namespaces=security \
  policies=snapshot ttl=10m >/dev/null
bao write auth/kubernetes/role/openbao-config \
  bound_service_account_names=openbao-config bound_service_account_namespaces=security \
  policies=config-admin ttl=20m >/dev/null

echo "==> OIDC (client_secret read from Authentik; no SOPS)"
SAT="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
K8S_RESP="$(wget -qO- --no-check-certificate --header="Authorization: Bearer ${SAT}" \
  https://kubernetes.default.svc/api/v1/namespaces/authentik/secrets/authentik-secret 2>/dev/null)"
AK_TOKEN="$(printf '%s' "${K8S_RESP}" | grep -o '"AUTHENTIK_BOOTSTRAP_TOKEN": *"[^"]*"' | sed 's/.*: *"//; s/"$//' | base64 -d 2>/dev/null)"
AK_RESP=""
[ -n "${AK_TOKEN}" ] && AK_RESP="$(wget -qO- --header="Authorization: Bearer ${AK_TOKEN}" \
  'http://authentik-server.authentik.svc.cluster.local/api/v3/providers/oauth2/?search=openbao' 2>/dev/null)"
CS="$(printf '%s' "${AK_RESP}" | grep -o '"client_secret": *"[^"]*"' | head -1 | sed 's/.*: *"//; s/"$//')"
echo "   debug: k8s_resp_len=${#K8S_RESP} is_secret=$(printf '%s' "${K8S_RESP}" | grep -c '"kind":"Secret"') ak_token=$([ -n "${AK_TOKEN}" ] && echo set || echo EMPTY) ak_resp_len=${#AK_RESP} cs=$([ -n "${CS}" ] && echo set || echo EMPTY) domain=${SECRET_DOMAIN:-EMPTY}"
printf '%s' "${K8S_RESP}" | grep -q '"kind":"Secret"' || echo "   debug-k8s-resp: $(printf '%s' "${K8S_RESP}" | head -c 400 | tr '\n' ' ')"
if [ -n "${CS}" ] && [ -n "${SECRET_DOMAIN:-}" ]; then
  bao write auth/oidc/config \
    oidc_discovery_url="https://authentik.${SECRET_DOMAIN}/application/o/openbao/" \
    oidc_client_id=openbao oidc_client_secret="${CS}" default_role=default >/dev/null
  bao write auth/oidc/role/default \
    user_claim=sub groups_claim=groups token_policies=default \
    oidc_scopes="openid,profile,email,groups" \
    allowed_redirect_uris="https://openbao.${SECRET_DOMAIN}/ui/vault/auth/oidc/oidc/callback,http://localhost:8250/oidc/callback" >/dev/null
  echo "   oidc configured"
else
  echo "   oidc skipped (Authentik token/client_secret/domain unavailable, or oidc not enabled)"
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

echo "==> config converged (scoped config-admin; no root)"
