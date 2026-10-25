resource "authentik_flow" "passkey_setup" {
  name           = "Set up a passkey"
  title          = "Set up a passkey or security key"
  slug           = "webgrip-passkey-setup"
  designation    = "stage_configuration"
  authentication = "require_authenticated"
}

resource "authentik_stage_authenticator_webauthn" "passkey" {
  name                     = "webgrip-passkey"
  friendly_name            = "Passkey or security key"
  user_verification        = "required"
  resident_key_requirement = "preferred"
  configure_flow           = authentik_flow.passkey_setup.uuid
}

resource "authentik_flow_stage_binding" "passkey_setup" {
  target = authentik_flow.passkey_setup.uuid
  stage  = authentik_stage_authenticator_webauthn.passkey.id
  order  = 0
}

resource "authentik_stage_authenticator_validate" "passkey_required" {
  name                       = "webgrip-passkey-required"
  device_classes             = ["webauthn"]
  not_configured_action      = "deny"
  webauthn_user_verification = "required"
  last_auth_threshold        = "seconds=0"
}

resource "authentik_flow" "passkey_authorization" {
  name           = "Authorize with a passkey"
  title          = "Confirm with your passkey"
  slug           = "webgrip-passkey-authorization"
  designation    = "authorization"
  authentication = "require_authenticated"
}

resource "authentik_flow_stage_binding" "passkey_authorization" {
  target = authentik_flow.passkey_authorization.uuid
  stage  = authentik_stage_authenticator_validate.passkey_required.id
  order  = 0
}
