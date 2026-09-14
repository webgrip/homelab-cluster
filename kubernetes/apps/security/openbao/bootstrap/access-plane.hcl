path "sys/auth" {
  capabilities = ["read"]
}
path "sys/auth/oidc" {
  capabilities = ["read"]
}
path "sys/auth/oidc/tune" {
  capabilities = ["read", "update"]
}
path "auth/oidc/config" {
  capabilities = ["create", "read", "update"]
}
path "auth/oidc/role/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "identity/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "sys/policies/acl/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "secret/data/authentik/app" {
  capabilities = ["read"]
}
path "secret/data/authentik/google-oauth" {
  capabilities = ["read"]
}
path "secret/data/+/oidc" {
  capabilities = ["read"]
}
path "secret/data/grafana/oauth" {
  capabilities = ["read"]
}
path "secret/data/cloudflare/access-oidc" {
  capabilities = ["read"]
}
