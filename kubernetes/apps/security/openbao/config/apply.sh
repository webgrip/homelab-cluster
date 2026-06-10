#!/bin/sh
# Idempotent OpenBao governance-as-code. Run hourly by the openbao-config CronJob,
# authenticating via Kubernetes auth (ServiceAccount openbao-config -> config-admin policy).
# Manages POLICIES + IDENTITY only. Auth plumbing (KV mount, k8s/oidc auth config) is the
# one-time bootstrap ceremony (it needs root / the OIDC client_secret). No secrets here.
set -eu
export BAO_ADDR="http://openbao.security.svc.cluster.local:8200"

JWT="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
BAO_TOKEN="$(bao write -field=token auth/kubernetes/login role=openbao-config jwt="$JWT")"
export BAO_TOKEN

echo "==> policies"
bao policy write admins /config/admins.hcl
bao policy write external-secrets /config/external-secrets.hcl
bao policy write config-admin /config/config-admin.hcl

echo "==> identity: external 'openbao-admins' group (policy: admins)"
bao write identity/group name=openbao-admins type=external policies=admins >/dev/null
GID="$(bao read -field=id identity/group/name/openbao-admins)"

# Map the Authentik 'homelab-admins' group -> openbao-admins via the OIDC mount accessor.
ACC="$(bao auth list | awk '$1 == "oidc/" { print $3 }')"
if [ -n "${ACC}" ]; then
  if bao write identity/group-alias name=homelab-admins mount_accessor="${ACC}" canonical_id="${GID}" 2>/dev/null; then
    echo "   group-alias homelab-admins -> openbao-admins created"
  else
    echo "   group-alias already present (ok)"
  fi
else
  echo "   NOTE: oidc auth not enabled yet; skipping group-alias (run the OIDC ceremony first)"
fi

echo "==> governance applied"
