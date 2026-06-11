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
