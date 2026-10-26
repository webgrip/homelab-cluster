mock_provider "authentik" {
  mock_resource "authentik_user" {
    defaults = {
      id = "12"
    }
  }
  mock_resource "authentik_provider_oauth2" {
    defaults = {
      id = "11"
    }
  }
  mock_data "authentik_users" {
    defaults = {
      users = []
    }
  }
  mock_data "authentik_property_mapping_provider_scope" {
    defaults = {
      ids = ["openid", "profile", "email", "offline_access"]
    }
  }
}

mock_provider "vault" {
  mock_data "vault_kv_secret_v2" {
    defaults = {
      data = {
        client_secret                       = "mock"
        client_id                           = "mock"
        key                                 = "mock"
        secret                              = "mock"
        GF_AUTH_GENERIC_OAUTH_CLIENT_ID     = "mock"
        GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET = "mock"
        AUTH_OIDC_CLIENT_ID                 = "mock"
        AUTH_OIDC_CLIENT_SECRET             = "mock"
        topic                               = "mock"
        token                               = "mock"
        url                                 = "mock"
        alertmanager_token                  = "mock"
        username                            = "mock"
        password                            = "mock"
      }
    }
  }
}

mock_provider "harbor" {}

variables {
  SECRET_DOMAIN = "example.invalid"
  vault_token   = "mock"
}

run "the_tailnet_login_demands_a_passkey_and_nothing_else_does" {
  command = plan

  assert {
    condition     = authentik_provider_oauth2.app["unfold-headscale"].authorization_flow == authentik_flow.passkey_authorization.uuid
    error_message = "the Unfold tailnet login must run the passkey authorization flow"
  }

  assert {
    condition = alltrue([
      for key, provider in authentik_provider_oauth2.app :
      provider.authorization_flow != authentik_flow.passkey_authorization.uuid if key != "unfold-headscale"
    ])
    error_message = "only applications that ask for passkey_required get the passkey flow"
  }

  assert {
    condition = alltrue([
      authentik_flow.passkey_authorization.designation == "authorization",
      authentik_flow.passkey_authorization.authentication == "require_authenticated",
      authentik_flow_stage_binding.passkey_authorization.target == authentik_flow.passkey_authorization.uuid,
      authentik_flow_stage_binding.passkey_authorization.stage == authentik_stage_authenticator_validate.passkey_required.id,
    ])
    error_message = "the passkey authorization flow runs the passkey validation stage for a signed-in person"
  }

  assert {
    condition = alltrue([
      authentik_stage_authenticator_validate.passkey_required.device_classes == tolist(["webauthn"]),
      authentik_stage_authenticator_validate.passkey_required.not_configured_action == "deny",
      authentik_stage_authenticator_validate.passkey_required.webauthn_user_verification == "required",
      authentik_stage_authenticator_validate.passkey_required.last_auth_threshold == "seconds=0",
    ])
    error_message = "only a passkey or security key with user verification passes, every time, and a person without one is refused rather than asked to enroll on the spot"
  }

  assert {
    condition = alltrue([
      authentik_stage_authenticator_webauthn.passkey.user_verification == "required",
      authentik_stage_authenticator_webauthn.passkey.configure_flow == authentik_flow.passkey_setup.uuid,
      authentik_flow.passkey_setup.designation == "stage_configuration",
      authentik_flow.passkey_setup.authentication == "require_authenticated",
    ])
    error_message = "a signed-in person enrolls a passkey from the user settings, with user verification"
  }
}

run "the_tailnet_login_is_a_confidential_client_for_headscale_that_only_unfold_admins_open" {
  command = plan

  assert {
    condition = alltrue([
      authentik_provider_oauth2.app["unfold-headscale"].client_id == "unfold-headscale",
      authentik_provider_oauth2.app["unfold-headscale"].client_type == "confidential",
      authentik_application.app["unfold-headscale"].slug == "unfold-headscale",
      [for redirect in authentik_provider_oauth2.app["unfold-headscale"].allowed_redirect_uris : redirect.url] == ["https://headscale.example.invalid/oidc/callback"],
      [for redirect in authentik_provider_oauth2.app["unfold-headscale"].allowed_redirect_uris : redirect.matching_mode] == ["strict"],
      contains(authentik_provider_oauth2.app["unfold-headscale"].property_mappings, authentik_property_mapping_provider_scope.app["groups"].id),
    ])
    error_message = "Headscale is a confidential client with one exact callback, and gets the groups claim it checks"
  }

  assert {
    condition     = [for binding in local.gate_bindings : binding.group if binding.app == "unfold-headscale"] == ["unfold-admins"]
    error_message = "unfold-admins, and no other group, opens the Unfold tailnet login"
  }
}

run "unfold_grafana_is_a_confidential_client_with_its_tailnet_callback_that_unfold_viewers_and_admins_open" {
  command = plan

  assert {
    condition = alltrue([
      authentik_provider_oauth2.app["unfold-grafana"].client_id == "unfold-grafana",
      authentik_provider_oauth2.app["unfold-grafana"].client_type == "confidential",
      authentik_application.app["unfold-grafana"].slug == "unfold-grafana",
      [for redirect in authentik_provider_oauth2.app["unfold-grafana"].allowed_redirect_uris : redirect.url] == ["http://unfold-observability.tailnet.unfold.internal/login/generic_oauth"],
      [for redirect in authentik_provider_oauth2.app["unfold-grafana"].allowed_redirect_uris : redirect.matching_mode] == ["strict"],
      contains(authentik_provider_oauth2.app["unfold-grafana"].property_mappings, authentik_property_mapping_provider_scope.app["groups"].id),
    ])
    error_message = "Unfold Grafana is a confidential client with one exact callback on the Unfold tailnet, and gets the groups claim it maps to roles"
  }

  assert {
    condition     = sort([for binding in local.gate_bindings : binding.group if binding.app == "unfold-grafana"]) == tolist(["unfold-admins", "unfold-viewers"])
    error_message = "unfold-viewers and unfold-admins, and no other group, open Unfold Grafana"
  }
}
