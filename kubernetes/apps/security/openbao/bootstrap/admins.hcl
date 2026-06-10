# Full administrative access for human operators, granted via the external identity
# group "openbao-admins" (aliased from Authentik "homelab-admins"). Gated by Authentik
# login + MFA. Single-admin homelab; tighten if users grow.
path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "patch", "sudo"]
}
