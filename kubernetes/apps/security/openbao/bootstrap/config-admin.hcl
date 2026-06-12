# Scoped policy for the openbao-config CronJob. Can manage governance (policies, auth
# roles, identity, OIDC config) but DELIBERATELY cannot read secrets (no secret/data),
# cannot mount engines / enable auth methods, and is not root.
path "sys/policies/acl/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "identity/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "auth/+/role/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "auth/oidc/config" {
  capabilities = ["create", "read", "update"]
}
path "sys/auth" {
  capabilities = ["read"]
}
# Manage the database secrets engine's CONNECTIONS and ROLES (dynamic DB credentials —
# RFC: Dynamic Database Credentials / ADR-0010). Deliberately NOT sys/mounts: config-admin
# manages the engine's config, it does not mount it (init.sh / break-glass root does that).
# Issuing creds (database/creds/*) is granted to the external-secrets policy, not here.
path "database/config/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "database/roles/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "database/rotate-root/*" {
  capabilities = ["update"]
}
path "database/reset/*" {
  capabilities = ["update"]
}
