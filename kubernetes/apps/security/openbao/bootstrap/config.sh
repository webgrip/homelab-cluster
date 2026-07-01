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
bao policy write cosign-signer /scripts/cosign-signer.hcl
bao policy write cosign-pub-reader /scripts/cosign-pub-reader.hcl

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
# Read-only role for the publisher that mirrors the cosign Transit public key into a ConfigMap.
bao write auth/kubernetes/role/cosign-pub-publisher \
  bound_service_account_names=cosign-pub-publisher bound_service_account_namespaces=security \
  policies=cosign-pub-reader ttl=10m >/dev/null

# Forgejo Actions OIDC -> Transit signing (JWT auth). Per-workflow identity: only the
# infrastructure release-publish flow can mint a sign-only token — tighter than a shared runner
# ServiceAccount, and fork PRs can't get a token at all. NB: Forgejo cannot emit a `release`
# Actions event for a CI-created release, so on_release_published is triggered via workflow_dispatch
# on a branch (main / release/*) — hence event_name=workflow_dispatch + ref=refs/heads/* here, NOT
# the GitHub-shaped event=release/ref=refs/tags/*. (Harden later by also binding the `workflow`
# claim to on_release_published once its exact value is confirmed from the job's printed claims.)
# Token iss is https://forgejo.<domain>/api/actions. Configuring the mount config needs it enabled
# first (root/break-glass: bao auth enable -path=forgejo jwt).
if [ -n "${SECRET_DOMAIN:-}" ]; then
  if bao write auth/forgejo/config \
       oidc_discovery_url="https://forgejo.${SECRET_DOMAIN}/api/actions" \
       default_role="cosign-signer" >/dev/null 2>&1; then
    # bound_claims is a MAP. The CLI won't convert an inline `bound_claims={...}` kv arg into
    # one ("expected map, got string"), so write the whole role as JSON via stdin. list fields
    # (bound_audiences, token_policies) are arrays for the same reason.
    if bao write auth/forgejo/role/cosign-signer - >/dev/null <<'JSON'
{
  "role_type": "jwt",
  "user_claim": "sub",
  "bound_audiences": ["openbao-cosign"],
  "bound_claims_type": "glob",
  "bound_claims": {"repository": "webgrip/infrastructure", "event_name": "workflow_dispatch", "ref": "refs/heads/*"},
  "token_policies": ["cosign-signer"],
  "token_ttl": "10m"
}
JSON
    then
      echo "   forgejo jwt auth + cosign-signer role configured"
    else
      echo "   WARN: forgejo cosign-signer role write FAILED (auth/forgejo mount present, role not created)"
    fi
  else
    echo "   forgejo jwt auth mount not present yet (break-glass: bao auth enable -path=forgejo jwt)"
  fi
fi

echo "==> OIDC (client_secret read from Authentik; no SOPS)"
SAT="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
K8S_RESP="$(wget -qO- --no-check-certificate --header="Authorization: Bearer ${SAT}" \
  https://kubernetes.default.svc/api/v1/namespaces/authentik/secrets/authentik-secret 2>/dev/null)"
AK_TOKEN="$(printf '%s' "${K8S_RESP}" | grep -o '"AUTHENTIK_BOOTSTRAP_TOKEN": *"[^"]*"' | sed 's/.*: *"//; s/"$//' | base64 -d 2>/dev/null)"
AK_RESP=""
[ -n "${AK_TOKEN}" ] && AK_RESP="$(wget -qO- --header="Authorization: Bearer ${AK_TOKEN}" \
  'http://authentik-server.authentik.svc.cluster.local/api/v3/providers/oauth2/?search=openbao' 2>/dev/null)"
CS="$(printf '%s' "${AK_RESP}" | grep -o '"client_secret": *"[^"]*"' | head -1 | sed 's/.*: *"//; s/"$//')"
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

echo "==> database engine (dynamic Postgres creds — ADR-0010)"
# Mount the database engine on the RUNNING cluster if init.sh (fresh-only) never did.
# config-admin holds a narrow sys/mounts/database* grant (see config-admin.hcl).
if ! bao secrets list -format=json 2>/dev/null | grep -q '"database/"'; then
  bao secrets enable -path=database database 2>/dev/null \
    && echo "   database engine mounted" \
    || echo "   WARN: database engine mount FAILED (check sys/mounts/database* grant)"
fi

# freshrss-db connection + role. config-admin CANNOT read KV, so the vault_admin password
# arrives as a mounted Secret file (see config-cronjob.yaml). Skip cleanly until it exists.
FRESHRSS_VA_PW="$(cat /db-admin/freshrss/password 2>/dev/null || true)"
if [ -n "${FRESHRSS_VA_PW}" ]; then
  # Idempotent upsert. connection_url {{username}}/{{password}} are OpenBao templates it fills
  # from the username/password fields below. NB: no rotate-root — CNPG owns this password.
  bao write database/config/freshrss-db \
    plugin_name=postgresql-database-plugin \
    allowed_roles="freshrss" \
    connection_url="postgresql://{{username}}:{{password}}@freshrss-db-rw.freshrss.svc.cluster.local:5432/freshrss?sslmode=require" \
    username="vault_admin" \
    password="${FRESHRSS_VA_PW}" >/dev/null 2>&1 \
    && echo "   freshrss-db connection configured" \
    || echo "   WARN: freshrss-db connection write FAILED (netpol? vault_admin in PG yet? TLS?)"

  # Ephemeral login role: member of freshrss, TTL-bounded. Revocation is DEFENSIVE — a bare
  # DROP ROLE fails if the role owns objects or has live sessions, so terminate + reassign +
  # drop-owned first (order matters).
  bao write database/roles/freshrss \
    db_name=freshrss-db \
    default_ttl="1h" \
    max_ttl="2h" \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT freshrss TO \"{{name}}\";" \
    revocation_statements="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = '{{name}}'; REASSIGN OWNED BY \"{{name}}\" TO freshrss; DROP OWNED BY \"{{name}}\"; DROP ROLE IF EXISTS \"{{name}}\";" \
    >/dev/null 2>&1 \
    && echo "   freshrss role configured" \
    || echo "   WARN: freshrss role write FAILED"
else
  echo "   freshrss vault_admin password not mounted yet; skipping db config (retry next run)"
fi

echo "==> config converged (scoped config-admin; no root)"
