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
bao policy write snapshot /scripts/snapshot.hcl
bao policy write config-admin /scripts/config-admin.hcl
bao policy write cosign-signer /scripts/cosign-signer.hcl
bao policy write cosign-pub-reader /scripts/cosign-pub-reader.hcl
bao policy write access-plane /scripts/access-plane.hcl
bao policy write ci-unfold /scripts/ci-unfold.hcl
bao policy write ci-twente-dev /scripts/ci-twente-dev.hcl
bao policy write ci-cloudflare /scripts/ci-cloudflare.hcl
bao policy write ci-cloudflare-registrar /scripts/ci-cloudflare-registrar.hcl
bao policy write ci-unfold-cluster /scripts/ci-unfold-cluster.hcl
bao policy write ci-unfold-cluster-etcd-check /scripts/ci-unfold-cluster-etcd-check.hcl
bao policy write unfold-main-reader /scripts/unfold-main-reader.hcl
bao policy write forgejo-repo-config /scripts/forgejo-repo-config.hcl
bao policy write github-config-ploeg-hq /scripts/github-config-ploeg-hq.hcl
bao policy write github-config-webgrip /scripts/github-config-webgrip.hcl
bao policy write github-secrets-bridge /scripts/github-secrets-bridge.hcl
bao policy write github-mirrors /scripts/github-mirrors.hcl
bao policy write renovate-github-app-token-ploeg-hq /scripts/renovate-github-app-token-ploeg-hq.hcl
bao policy write renovate-github-app-token-wellhead-dev /scripts/renovate-github-app-token-wellhead-dev.hcl
bao policy write homelab-etcd-age-keygen /scripts/homelab-etcd-age-keygen.hcl

echo "==> kubernetes roles"
for retired in external-secrets external-secrets-push; do
  bao delete "auth/kubernetes/role/$retired" >/dev/null 2>&1
  bao policy delete "$retired" >/dev/null 2>&1
done
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
bao write auth/kubernetes/role/access-plane \
  bound_service_account_names=access-plane-runner bound_service_account_namespaces=security \
  policies=access-plane ttl=30m >/dev/null
bao write auth/kubernetes/role/forgejo-repo-config \
  bound_service_account_names=forgejo-repo-config-runner bound_service_account_namespaces=repo-config \
  policies=forgejo-repo-config ttl=30m >/dev/null
bao write auth/kubernetes/role/github-config-ploeg-hq \
  bound_service_account_names=github-config-ploeg-hq-runner bound_service_account_namespaces=github-config \
  policies=github-config-ploeg-hq ttl=30m >/dev/null
bao write auth/kubernetes/role/github-config-webgrip \
  bound_service_account_names=github-config-webgrip-runner bound_service_account_namespaces=github-config \
  policies=github-config-webgrip ttl=30m >/dev/null
bao write auth/kubernetes/role/github-secrets-bridge \
  bound_service_account_names=github-secrets-bridge bound_service_account_namespaces=github-secrets-bridge \
  policies=github-secrets-bridge ttl=10m >/dev/null
bao write auth/kubernetes/role/github-mirrors \
  bound_service_account_names=github-mirrors bound_service_account_namespaces=github-config \
  policies=github-mirrors ttl=10m >/dev/null
bao write auth/kubernetes/role/renovate-github-app-token-ploeg-hq \
  bound_service_account_names=renovate-github-app-token-ploeg-hq bound_service_account_namespaces=renovate \
  policies=renovate-github-app-token-ploeg-hq ttl=10m >/dev/null
bao write auth/kubernetes/role/renovate-github-app-token-wellhead-dev \
  bound_service_account_names=renovate-github-app-token-wellhead-dev bound_service_account_namespaces=renovate \
  policies=renovate-github-app-token-wellhead-dev ttl=10m >/dev/null
bao write auth/kubernetes/role/homelab-etcd-age-keygen \
  bound_service_account_names=homelab-etcd-age-keygen bound_service_account_namespaces=backup \
  policies=homelab-etcd-age-keygen ttl=5m >/dev/null

echo "==> per-namespace ESO roles (each namespace reads only the paths its ExternalSecrets name)"
sh /scripts/eso-grants.sh

# Forgejo Actions OIDC -> Transit signing (JWT auth). Per-workflow identity: only the
# release-publish flows of the explicitly listed repos can mint a sign-only token — tighter
# than a shared runner ServiceAccount, and fork PRs can't get a token at all. Adding a repo
# to signing = adding it to the bound_claims repository list below (deliberate one-line PR). NB: releases are cut with the
# webgrip-ci bot PAT, so Forgejo DOES emit a native `release` event (only same-token actions
# are loop-suppressed) — on_release_published now runs event_name=release on ref=refs/tags/*.
# (Harden later by also binding the `workflow` claim to on_release_published once its exact
# value is confirmed from the job's printed claims.)
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
  "bound_claims": {"repository": ["webgrip/infrastructure", "webgrip/glide", "webgrip/unfold", "webgrip/omnigraph-explorer", "webgrip/brain-tools", "webgrip/semantic-release-config", "webgrip/talos-kata-extension"], "event_name": ["release", "workflow_dispatch"], "ref": ["refs/tags/*", "refs/heads/main"]},
  "token_policies": ["cosign-signer"],
  "token_ttl": "10m"
}
JSON
    then
      echo "   forgejo jwt auth + cosign-signer role configured"
    else
      echo "   WARN: forgejo cosign-signer role write FAILED (auth/forgejo mount present, role not created)"
    fi
    write_ci_read_role() {
      if bao write "auth/forgejo/role/$1" - >/dev/null <<JSON
{
  "role_type": "jwt",
  "user_claim": "sub",
  "bound_audiences": ["openbao-ci"],
  "bound_claims_type": "string",
  "bound_claims": {"repository": ["$2"], "event_name": ["push", "pull_request", "schedule", "workflow_dispatch"]},
  "token_policies": ["$1"],
  "token_ttl": "10m",
  "token_max_ttl": "10m"
}
JSON
      then
        echo "   forgejo jwt role $1 configured for $2"
      else
        echo "   WARN: forgejo jwt role $1 write FAILED"
      fi
    }
    write_ci_read_role ci-unfold webgrip/unfold
    write_ci_read_role ci-twente-dev webgrip/twente.dev
    write_ci_read_role ci-cloudflare webgrip/cloudflare
    if bao write auth/forgejo/role/ci-cloudflare-registrar - >/dev/null <<JSON
{
  "role_type": "jwt",
  "user_claim": "sub",
  "bound_audiences": ["openbao-ci"],
  "bound_claims_type": "string",
  "bound_claims": {"repository": ["webgrip/cloudflare"], "ref": ["refs/heads/main", "main"], "event_name": ["push"], "actor": ["ryangr0"], "workflow": ["apply.yml"], "run_attempt": ["1"]},
  "token_policies": ["ci-cloudflare-registrar"],
  "token_ttl": "5m",
  "token_max_ttl": "5m",
  "token_num_uses": 10
}
JSON
    then
      echo "   forgejo jwt role ci-cloudflare-registrar configured for webgrip/cloudflare main"
    else
      echo "   WARN: forgejo jwt role ci-cloudflare-registrar write FAILED"
    fi
    if bao write auth/forgejo/role/ci-unfold-cluster - >/dev/null <<JSON
{
  "role_type": "jwt",
  "user_claim": "sub",
  "bound_audiences": ["openbao-ci"],
  "bound_claims_type": "string",
  "bound_claims": {"repository": ["webgrip/unfold-cluster"], "ref": ["refs/heads/main", "main"], "event_name": ["push", "workflow_dispatch"], "actor": ["ryangr0"], "run_attempt": ["1"]},
  "token_policies": ["ci-unfold-cluster"],
  "token_ttl": "10m",
  "token_max_ttl": "10m"
}
JSON
    then
      echo "   forgejo jwt role ci-unfold-cluster configured for webgrip/unfold-cluster main"
    else
      echo "   WARN: forgejo jwt role ci-unfold-cluster write FAILED"
    fi
    if bao write auth/forgejo/role/ci-unfold-cluster-etcd-check - >/dev/null <<JSON
{
  "role_type": "jwt",
  "user_claim": "sub",
  "bound_audiences": ["openbao-ci"],
  "bound_claims_type": "string",
  "bound_claims": {"repository": ["webgrip/unfold-cluster"], "ref": ["refs/heads/main", "main"], "event_name": ["schedule"], "actor": ["forgejo-actions"], "workflow": ["etcd-backup-check.yml"], "run_attempt": ["1"]},
  "token_policies": ["ci-unfold-cluster-etcd-check"],
  "token_ttl": "10m",
  "token_max_ttl": "10m"
}
JSON
    then
      echo "   forgejo jwt role ci-unfold-cluster-etcd-check configured for the webgrip/unfold-cluster schedule"
    else
      echo "   WARN: forgejo jwt role ci-unfold-cluster-etcd-check write FAILED"
    fi
  else
    echo "   forgejo jwt auth mount not present yet (break-glass: bao auth enable -path=forgejo jwt)"
  fi
fi

echo "==> unfold-main cluster (JWT auth on its service-account key)"
if ! bao auth list -format=json 2>/dev/null | grep -q '"jwt-unfold-main/"'; then
  bao auth enable -path=jwt-unfold-main jwt >/dev/null 2>&1 \
    && echo "   jwt-unfold-main mounted" \
    || echo "   WARN: jwt-unfold-main mount FAILED (check the sys/auth/jwt-unfold-main grant)"
fi
if bao write auth/jwt-unfold-main/config \
     jwt_validation_pubkeys=@/scripts/unfold-main-service-account.pem \
     bound_issuer="https://10.64.0.10:6443" >/dev/null 2>&1; then
  if bao write auth/jwt-unfold-main/role/unfold-main-external-secrets - >/dev/null <<'JSON'
{
  "role_type": "jwt",
  "user_claim": "sub",
  "bound_audiences": ["openbao-homelab"],
  "bound_subject": "system:serviceaccount:external-secrets:openbao-homelab",
  "token_policies": ["unfold-main-reader"],
  "token_ttl": "10m",
  "token_max_ttl": "10m"
}
JSON
  then
    echo "   jwt-unfold-main role unfold-main-external-secrets configured"
  else
    echo "   WARN: jwt-unfold-main role write FAILED"
  fi
else
  echo "   WARN: jwt-unfold-main config write FAILED"
fi

echo "==> database engine (dynamic Postgres creds — ADR-0016)"
# Mount the database engine on the RUNNING cluster if init.sh (fresh-only) never did.
# config-admin holds a narrow sys/mounts/database* grant (see config-admin.hcl).
if ! bao read sys/mounts/database >/dev/null 2>&1; then
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

  # Ephemeral login role, TTL-bounded. Creation grants object privileges via `SET ROLE freshrss`
  # (vault_admin is a MEMBER of freshrss via CNPG managed.roles inRoles — declarative, in Git), NOT
  # `GRANT freshrss TO ...`. The membership form needs vault_admin to hold ADMIN OPTION on freshrss
  # (PG16+), which only a superuser can grant — a manual, non-reproducible bootstrap step. Granting
  # object privileges as the owner needs no admin option and no superuser, so the whole role is
  # reproducible from Git on a fresh cluster. Revocation is DEFENSIVE — a bare DROP ROLE fails if the
  # role owns objects or has live sessions, so terminate + reassign + drop-owned first (order matters).
  bao write database/roles/freshrss \
    db_name=freshrss-db \
    default_ttl="1h" \
    max_ttl="2h" \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; SET ROLE freshrss; GRANT USAGE, CREATE ON SCHEMA public TO \"{{name}}\"; GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO \"{{name}}\"; GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO \"{{name}}\"; RESET ROLE;" \
    revocation_statements="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = '{{name}}'; REASSIGN OWNED BY \"{{name}}\" TO freshrss; DROP OWNED BY \"{{name}}\"; DROP ROLE IF EXISTS \"{{name}}\";" \
    >/dev/null 2>&1 \
    && echo "   freshrss role configured" \
    || echo "   WARN: freshrss role write FAILED"
else
  echo "   freshrss vault_admin password not mounted yet; skipping db config (retry next run)"
fi

echo "==> config converged (scoped config-admin; no root)"
