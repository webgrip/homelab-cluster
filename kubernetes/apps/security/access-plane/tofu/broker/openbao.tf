resource "vault_jwt_auth_backend" "oidc" {
  path               = "oidc"
  type               = "oidc"
  oidc_discovery_url = "https://authentik.${var.SECRET_DOMAIN}/application/o/openbao/"
  oidc_client_id     = "openbao"
  oidc_client_secret = authentik_provider_oauth2.app["openbao"].client_secret
  default_role       = "default"

  lifecycle {
    prevent_destroy = true
  }
}

resource "vault_jwt_auth_backend_role" "default" {
  backend      = vault_jwt_auth_backend.oidc.path
  role_name    = "default"
  role_type    = "oidc"
  user_claim   = "sub"
  groups_claim = "groups"
  oidc_scopes  = ["openid", "profile", "email", "groups"]
  allowed_redirect_uris = [
    "https://openbao.${var.SECRET_DOMAIN}/ui/vault/auth/oidc/oidc/callback",
    "http://localhost:8250/oidc/callback",
  ]
  token_policies = ["default"]
}

resource "vault_identity_group" "openbao_admins" {
  name     = "openbao-admins"
  type     = "external"
  policies = ["admins"]
}

resource "vault_identity_group_alias" "homelab_admins" {
  name           = "homelab-admins"
  mount_accessor = vault_jwt_auth_backend.oidc.accessor
  canonical_id   = vault_identity_group.openbao_admins.id
}
