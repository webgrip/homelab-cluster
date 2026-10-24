# RFC 8693 token exchange into Ploeg (VIK-2381, RFC-0011 stage 2).
#
# A consumer acting for a person trades that person's token for one Ploeg can
# verify, instead of naming the person in a header Ploeg must trust. Two providers
# per consumer:
#
#   <consumer>-exchange    confidential client the consumer's SERVER authenticates
#                          as; may exchange tokens its sign-in provider issued
#                          (jwt_federation_providers), and nothing else
#   ploeg-for-<consumer>   the target: aud = azp = its client_id, issued only by
#                          exchange (no redirect URIs, no grant of its own)
#
# One target per consumer, because authentik writes the TARGET's client_id into
# both aud and azp of an exchanged token (providers/oauth2/id_token.py at
# version/2026.8.5): the audience is the only claim that tells Ploeg which
# consumer asked, and a token minted for one consumer cannot be replayed by
# another. Targets use the global issuer so Ploeg trusts one issuer for all of
# them. Subject tokens are looked up as authentik-issued access tokens of the
# federated provider (base_fed.py validate_jwt_from_provider), not as foreign
# JWTs, so no federated-source claim policy is involved.
#
# The person's own sub carries over unchanged (hashed user id on every provider
# here), which is what Ploeg derives its person id from.
locals {
  exchange_consumers = {
    unfold = {
      sign_in       = "unfold"
      exchange_name = "Unfold (token exchange)"
      target_name   = "Ploeg, for Unfold"
      description   = "Unfold's server trades a signed-in person's token for one Ploeg verifies."
    }
    ploeg-mcp = {
      sign_in       = "ploeg-mcp"
      exchange_name = "Ploeg MCP (token exchange)"
      target_name   = "Ploeg, for Ploeg MCP"
      description   = "ploeg-mcp trades the caller's token for one Ploeg verifies before an action."
    }
  }

  # Every application the capability gates in applications.tf may bind to.
  application_uuids = merge(
    { for key, app in authentik_application.app : key => app.uuid },
    { for key, app in authentik_application.exchange_client : "${key}-exchange" => app.uuid },
    { for key, app in authentik_application.exchange_target : "ploeg-for-${key}" => app.uuid },
  )
}

resource "authentik_provider_oauth2" "exchange_client" {
  for_each = local.exchange_consumers

  name                     = "${each.key}-exchange"
  client_id                = "${each.key}-exchange"
  client_secret            = data.vault_kv_secret_v2.oidc_client["${each.key}-exchange"].data["client_secret"]
  client_type              = "confidential"
  grant_types              = ["urn:ietf:params:oauth:grant-type:token-exchange"]
  access_token_validity    = "minutes=5"
  refresh_token_validity   = "minutes=5"
  jwt_federation_providers = [authentik_provider_oauth2.app[each.value.sign_in].id]
  authentication_flow      = var.google_login ? authentik_flow.webgrip_authentication[0].uuid : data.authentik_flow.authentication.id
  authorization_flow       = data.authentik_flow.authorization_implicit_consent.id
  invalidation_flow        = data.authentik_flow.invalidation.id
  signing_key              = data.authentik_certificate_key_pair.self_signed.id
  allowed_redirect_uris    = []
  property_mappings        = data.authentik_property_mapping_provider_scope.standard.ids
}

resource "authentik_provider_oauth2" "exchange_target" {
  for_each = local.exchange_consumers

  name                     = "ploeg-for-${each.key}"
  client_id                = "ploeg-for-${each.key}"
  client_type              = "confidential"
  grant_types              = []
  issuer_mode              = "global"
  access_token_validity    = "minutes=5"
  refresh_token_validity   = "minutes=5"
  jwt_federation_providers = [authentik_provider_oauth2.exchange_client[each.key].id]
  authentication_flow      = var.google_login ? authentik_flow.webgrip_authentication[0].uuid : data.authentik_flow.authentication.id
  authorization_flow       = data.authentik_flow.authorization_implicit_consent.id
  invalidation_flow        = data.authentik_flow.invalidation.id
  signing_key              = data.authentik_certificate_key_pair.self_signed.id
  allowed_redirect_uris    = []
  property_mappings        = data.authentik_property_mapping_provider_scope.standard.ids
}

# authentik refuses an exchange whose requesting or target provider has no
# application, and checks the person against both applications' bindings.
# blank://blank keeps them out of everyone's application library.
resource "authentik_application" "exchange_client" {
  for_each = local.exchange_consumers

  name               = each.value.exchange_name
  slug               = "${each.key}-exchange"
  protocol_provider  = authentik_provider_oauth2.exchange_client[each.key].id
  meta_description   = each.value.description
  meta_launch_url    = "blank://blank"
  policy_engine_mode = "any"
}

resource "authentik_application" "exchange_target" {
  for_each = local.exchange_consumers

  name               = each.value.target_name
  slug               = "ploeg-for-${each.key}"
  protocol_provider  = authentik_provider_oauth2.exchange_target[each.key].id
  meta_description   = "The audience of person tokens ${each.value.sign_in} presents to Ploeg."
  meta_launch_url    = "blank://blank"
  policy_engine_mode = "any"
}
