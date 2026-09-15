ephemeral "vault_kv_secret_v2" "authentik" {
  mount = "secret"
  name  = "authentik/app"
}

data "vault_kv_secret_v2" "oidc_client" {
  for_each = {
    grafana            = "grafana/oauth"
    backstage          = "backstage/oidc"
    forgejo            = "forgejo/oidc"
    harbor             = "harbor/oidc"
    vikunja            = "vikunja/oidc"
    litellm            = "litellm/oidc"
    cloudflare-access  = "cloudflare/access-oidc"
    longhorn           = "authentik/longhorn-oidc"
    cluster-dashboards = "authentik/dashboards-oidc"
  }
  mount = "secret"
  name  = each.value
}

data "authentik_flow" "authentication" {
  slug = "homelab-authentication"
}

data "authentik_flow" "authorization_explicit_consent" {
  slug = "default-provider-authorization-explicit-consent"
}

data "authentik_flow" "invalidation" {
  slug = "default-provider-invalidation-flow"
}

data "authentik_certificate_key_pair" "self_signed" {
  name              = "authentik Self-signed Certificate"
  fetch_certificate = false
  fetch_key         = false
}

data "authentik_property_mapping_provider_scope" "standard" {
  managed_list = [
    "goauthentik.io/providers/oauth2/scope-openid",
    "goauthentik.io/providers/oauth2/scope-profile",
    "goauthentik.io/providers/oauth2/scope-email",
  ]
}

ephemeral "vault_kv_secret_v2" "harbor_admin" {
  mount = "secret"
  name  = "harbor/admin"
}

data "vault_kv_secret_v2" "ntfy" {
  mount = "secret"
  name  = "ntfy/auth"
}
