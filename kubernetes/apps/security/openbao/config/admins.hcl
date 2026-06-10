# Full administrative access for human operators. Granted via the external identity
# group "openbao-admins", which is aliased from the Authentik "homelab-admins" group —
# so access is gated by Authentik login + MFA. (Single-admin homelab; tighten if users grow.)
path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "patch", "sudo"]
}
