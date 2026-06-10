# Used by the openbao-config CronJob to manage policies + identity as code.
# Deliberately scoped to governance paths — NOT a full admin.
path "sys/policies/acl/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "identity/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "sys/auth" {
  capabilities = ["read"]
}
path "auth/+/role/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
