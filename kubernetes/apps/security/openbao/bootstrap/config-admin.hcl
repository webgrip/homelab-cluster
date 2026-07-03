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
# Forgejo Actions OIDC (JWT auth method mounted at auth/forgejo). config-admin configures
# it but does not mount it (root/break-glass enables the mount); roles are covered by
# auth/+/role/* above.
path "auth/forgejo/config" {
  capabilities = ["create", "read", "update"]
}
path "sys/auth" {
  capabilities = ["read"]
}
# Manage the database secrets engine's CONNECTIONS and ROLES (dynamic DB credentials —
# RFC: Dynamic Database Credentials / ADR-0016).
# Issuing creds (database/creds/*) is granted to the external-secrets policy, not here.
#
# NARROW mount grant (ADR-0016, decided 2026-06/07): init.sh mounts `database` only on a
# FRESH cluster; on an already-bootstrapped cluster there is no live root and generate-root
# returns 405 here, so config-admin mounts the engine itself. Scoped to database* ONLY (not
# sys/mounts/*), and reversible — config-admin can already self-escalate via sys/policies/acl/*,
# so this explicit grant is little real new exposure. It does NOT let config-admin mount other
# engines.
path "sys/mounts/database" {
  capabilities = ["create", "read", "update"]
}
path "sys/mounts/database/*" {
  capabilities = ["create", "read", "update"]
}
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
