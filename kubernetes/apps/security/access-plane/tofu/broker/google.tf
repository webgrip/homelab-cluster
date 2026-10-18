data "vault_kv_secret_v2" "google" {
  count = var.google_login ? 1 : 0
  mount = "secret"
  name  = "authentik/google-oauth"
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
  authentication_flow = authentik_flow.webgrip_source_authentication[0].uuid

  lifecycle {
    ignore_changes = [access_token_url, authorization_url, oidc_jwks_url, profile_url]
  }
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
  sources            = [authentik_source_oauth.google[0].uuid]
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

  lifecycle {
    ignore_changes = [branding_favicon, branding_logo]
  }
}

resource "authentik_flow" "webgrip_source_authentication" {
  count = var.google_login ? 1 : 0

  name           = "WebGrip source authentication"
  title          = "Signing in to WebGrip"
  slug           = "webgrip-source-authentication"
  designation    = "authentication"
  authentication = "require_unauthenticated"
}

resource "authentik_stage_user_login" "webgrip_source" {
  count = var.google_login ? 1 : 0

  name                     = "webgrip-source-login"
  session_duration         = "hours=12"
  remember_me_offset       = "seconds=0"
  terminate_other_sessions = false
}

resource "authentik_flow_stage_binding" "webgrip_source_login" {
  count = var.google_login ? 1 : 0

  target = authentik_flow.webgrip_source_authentication[0].uuid
  stage  = authentik_stage_user_login.webgrip_source[0].id
  order  = 0
}

resource "authentik_policy_expression" "webgrip_source_only_sso" {
  count = var.google_login ? 1 : 0

  name       = "webgrip-source-authentication-if-sso"
  expression = "return ak_is_sso_flow"
}

resource "authentik_policy_binding" "webgrip_source_only_sso" {
  count = var.google_login ? 1 : 0

  target  = authentik_flow.webgrip_source_authentication[0].uuid
  policy  = authentik_policy_expression.webgrip_source_only_sso[0].id
  order   = 0
  enabled = true
}
