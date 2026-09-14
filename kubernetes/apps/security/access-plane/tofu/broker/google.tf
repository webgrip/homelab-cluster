data "vault_kv_secret_v2" "google" {
  count = var.google_login ? 1 : 0
  mount = "secret"
  name  = "authentik/google-oauth"
}

data "authentik_flow" "source_authentication" {
  slug = "default-source-authentication"
}

resource "authentik_source_oauth" "google" {
  count = var.google_login ? 1 : 0

  name                = "Google"
  slug                = "google"
  provider_type       = "google"
  consumer_key        = data.vault_kv_secret_v2.google[0].data["client_id"]
  consumer_secret     = data.vault_kv_secret_v2.google[0].data["client_secret"]
  enabled             = true
  user_matching_mode  = "email_link"
  additional_scopes   = "email profile"
  authentication_flow = data.authentik_flow.source_authentication.id
}

resource "authentik_flow" "webgrip_authentication" {
  count = var.google_login ? 1 : 0

  name           = "WebGrip Authentication"
  title          = "Sign in to WebGrip"
  slug           = "webgrip-authentication"
  designation    = "authentication"
  authentication = "require_unauthenticated"
}

resource "authentik_stage_identification" "webgrip" {
  count = var.google_login ? 1 : 0

  name               = "webgrip-identification"
  user_fields        = []
  sources            = [authentik_source_oauth.google[0].id]
  show_source_labels = true
}

resource "authentik_flow_stage_binding" "webgrip_identification" {
  count = var.google_login ? 1 : 0

  target = authentik_flow.webgrip_authentication[0].uuid
  stage  = authentik_stage_identification.webgrip[0].id
  order  = 10
}

resource "authentik_brand" "webgrip" {
  count = var.google_login ? 1 : 0

  domain              = "authentik.${var.SECRET_DOMAIN}"
  default             = false
  branding_title      = "WebGrip"
  flow_authentication = authentik_flow.webgrip_authentication[0].uuid
}
