locals {
  groups_claim_expression = <<-EOT
    return {
        "groups": [group.name for group in request.user.ak_groups.all()],
    }
  EOT

  scope_mappings = {
    grafana-groups = {
      scope_name  = "groups"
      description = "Group names for Grafana role mapping."
      expression  = local.groups_claim_expression
    }
    forgejo-groups = {
      scope_name  = "groups"
      description = "Group names for Forgejo team + admin mapping."
      expression  = local.groups_claim_expression
    }
    openbao-groups = {
      scope_name  = "groups"
      description = "Group names for OpenBao policy mapping."
      expression  = local.groups_claim_expression
    }
    harbor-groups = {
      scope_name  = "groups"
      description = ""
      expression  = local.groups_claim_expression
    }
    vloer-groups = {
      scope_name  = "groups"
      description = ""
      expression  = <<-EOT
        return {
            "groups": [group.name for group in request.user.groups.filter(name="homelab-admins")],
        }
      EOT
    }
    litellm-role = {
      scope_name  = "litellm_role"
      description = "Emits litellm_role (proxy_admin for homelab-admins, else internal_user)."
      expression  = <<-EOT
        if request.user.ak_groups.filter(name="homelab-admins").exists():
            return {"litellm_role": "proxy_admin"}
        return {"litellm_role": "internal_user"}
      EOT
    }
  }

  oauth_applications = {
    grafana = {
      provider_name = "grafana-oidc"
      display_name  = "Grafana OIDC"
      app_name      = "Grafana"
      description   = "Grafana login via Authentik OIDC."
      launch_url    = "https://grafana.${var.SECRET_DOMAIN}"
      client_id     = data.vault_kv_secret_v2.oidc_client["grafana"].data["GF_AUTH_GENERIC_OAUTH_CLIENT_ID"]
      client_secret = data.vault_kv_secret_v2.oidc_client["grafana"].data["GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET"]
      client_type   = "confidential"
      signing_key   = false
      grant_types   = ["authorization_code", "refresh_token"]
      redirects     = [{ matching_mode = "strict", url = "https://grafana.${var.SECRET_DOMAIN}/login/generic_oauth" }]
      extra_scopes  = ["grafana-groups"]
      gate          = "homelab-users-only"
    }
    backstage = {
      provider_name = "backstage-oidc"
      display_name  = "Backstage OIDC"
      app_name      = "Backstage"
      description   = "Backstage developer portal login via Authentik OIDC."
      launch_url    = "https://backstage.${var.SECRET_DOMAIN}"
      client_id     = data.vault_kv_secret_v2.oidc_client["backstage"].data["AUTH_OIDC_CLIENT_ID"]
      client_secret = data.vault_kv_secret_v2.oidc_client["backstage"].data["AUTH_OIDC_CLIENT_SECRET"]
      client_type   = "confidential"
      signing_key   = false
      grant_types   = ["authorization_code", "refresh_token"]
      redirects     = [{ matching_mode = "strict", url = "https://backstage.${var.SECRET_DOMAIN}/api/auth/oidc/handler/frame" }]
      extra_scopes  = []
      gate          = "homelab-users-only"
    }
    forgejo = {
      provider_name = "forgejo-oidc"
      display_name  = "Forgejo OIDC"
      app_name      = "Forgejo"
      description   = "Forgejo git hosting login via Authentik OIDC."
      launch_url    = "https://forgejo.${var.SECRET_DOMAIN}"
      client_id     = data.vault_kv_secret_v2.oidc_client["forgejo"].data["key"]
      client_secret = data.vault_kv_secret_v2.oidc_client["forgejo"].data["secret"]
      client_type   = "confidential"
      signing_key   = false
      grant_types   = ["authorization_code", "refresh_token"]
      redirects     = [{ matching_mode = "strict", url = "https://forgejo.${var.SECRET_DOMAIN}/user/oauth2/authentik/callback" }]
      extra_scopes  = ["forgejo-groups"]
      gate          = "homelab-users-only"
    }
    openbao = {
      provider_name = "openbao-oidc"
      display_name  = "OpenBao OIDC"
      app_name      = "OpenBao"
      description   = "OpenBao secrets manager login via Authentik OIDC."
      launch_url    = "https://openbao.${var.SECRET_DOMAIN}"
      client_id     = "openbao"
      client_secret = null
      client_type   = "confidential"
      signing_key   = true
      grant_types   = ["authorization_code", "refresh_token"]
      redirects = [
        { matching_mode = "strict", url = "https://openbao.${var.SECRET_DOMAIN}/ui/vault/auth/oidc/oidc/callback" },
        { matching_mode = "strict", url = "http://localhost:8250/oidc/callback" },
      ]
      extra_scopes = ["openbao-groups"]
      gate         = "homelab-users-only"
    }
    harbor = {
      provider_name = "harbor-oidc"
      display_name  = "Harbor OIDC"
      app_name      = "Harbor"
      description   = "Harbor container registry login via Authentik OIDC."
      launch_url    = "https://harbor.${var.SECRET_DOMAIN}"
      client_id     = "harbor"
      client_secret = data.vault_kv_secret_v2.oidc_client["harbor"].data["client_secret"]
      client_type   = "confidential"
      signing_key   = true
      grant_types   = ["authorization_code", "refresh_token"]
      redirects     = [{ matching_mode = "strict", url = "https://harbor.${var.SECRET_DOMAIN}/c/oidc/callback" }]
      extra_scopes  = ["harbor-groups"]
      gate          = "homelab-users-only"
    }
    vikunja = {
      provider_name = "vikunja-oidc"
      display_name  = "Vikunja OIDC"
      app_name      = "Vikunja"
      description   = "Vikunja task management login via Authentik OIDC."
      launch_url    = "https://vikunja.${var.SECRET_DOMAIN}"
      client_id     = "vikunja"
      client_secret = data.vault_kv_secret_v2.oidc_client["vikunja"].data["client_secret"]
      client_type   = "confidential"
      signing_key   = true
      grant_types   = ["authorization_code", "refresh_token"]
      redirects     = [{ matching_mode = "strict", url = "https://vikunja.${var.SECRET_DOMAIN}/auth/openid/authentik" }]
      extra_scopes  = []
      gate          = "homelab-users-only"
    }
    litellm = {
      provider_name = "litellm-oidc"
      display_name  = "LiteLLM OIDC"
      app_name      = "LiteLLM"
      description   = "LiteLLM proxy Admin UI login via Authentik OIDC."
      launch_url    = "https://litellm.${var.SECRET_DOMAIN}/ui"
      client_id     = "litellm"
      client_secret = data.vault_kv_secret_v2.oidc_client["litellm"].data["client_secret"]
      client_type   = "confidential"
      signing_key   = true
      grant_types   = ["authorization_code", "refresh_token"]
      redirects     = [{ matching_mode = "strict", url = "https://litellm.${var.SECRET_DOMAIN}/sso/callback" }]
      extra_scopes  = ["litellm-role"]
      gate          = "homelab-users-only"
    }
    cloudflare-access = {
      provider_name = "cloudflare-access-oidc"
      display_name  = "Cloudflare Access OIDC"
      app_name      = "Cloudflare Access"
      description   = "Cloudflare Access login for the staging sites via Authentik OIDC."
      launch_url    = "https://staging.twente.dev"
      client_id     = "cloudflare-access"
      client_secret = data.vault_kv_secret_v2.oidc_client["cloudflare-access"].data["client_secret"]
      client_type   = "confidential"
      signing_key   = true
      grant_types   = ["authorization_code", "refresh_token"]
      redirects     = [{ matching_mode = "strict", url = "https://webgrip.cloudflareaccess.com/cdn-cgi/access/callback" }]
      extra_scopes  = []
      gate          = "homelab-users-only"
    }
    vloer = {
      provider_name = "vloer-oidc"
      display_name  = "vloer-oidc"
      app_name      = "Vloer"
      description   = "Human workbench for Ploeg and remote agent workspaces."
      launch_url    = "https://vloer.${var.SECRET_DOMAIN}"
      client_id     = "vloer"
      client_secret = null
      client_type   = "public"
      signing_key   = true
      grant_types   = ["authorization_code"]
      redirects     = [{ matching_mode = "strict", url = "https://vloer.${var.SECRET_DOMAIN}/api/auth/oidc/callback" }]
      extra_scopes  = ["vloer-groups"]
      gate          = "homelab-admins-only"
    }
  }

  expression_policies = {
    homelab-users-only   = "return request.user.is_authenticated and request.user.ak_groups.filter(name=\"homelab-users\").exists()\n"
    homelab-admins-only  = "return request.user.is_authenticated and request.user.ak_groups.filter(name=\"homelab-admins\").exists()\n"
    homelab-mfa-required = "return request.user.is_authenticated and request.user.ak_groups.filter(name=\"homelab-mfa\").exists()"
  }
}

resource "authentik_policy_expression" "gate" {
  for_each   = local.expression_policies
  name       = each.key
  expression = each.value
}

resource "authentik_property_mapping_provider_scope" "app" {
  for_each    = local.scope_mappings
  name        = each.key
  scope_name  = each.value.scope_name
  description = each.value.description
  expression  = each.value.expression
}

resource "authentik_provider_oauth2" "app" {
  for_each = local.oauth_applications

  name                = each.value.display_name
  client_id           = each.value.client_id
  client_secret       = each.value.client_secret
  client_type         = each.value.client_type
  grant_types         = each.value.grant_types
  authentication_flow = data.authentik_flow.authentication.id
  authorization_flow  = data.authentik_flow.authorization_explicit_consent.id
  invalidation_flow   = data.authentik_flow.invalidation.id
  signing_key         = each.value.signing_key ? data.authentik_certificate_key_pair.self_signed.id : null

  allowed_redirect_uris = each.value.redirects

  property_mappings = concat(
    data.authentik_property_mapping_provider_scope.standard.ids,
    [for scope in each.value.extra_scopes : authentik_property_mapping_provider_scope.app[scope].id],
  )
}

resource "authentik_application" "app" {
  for_each = local.oauth_applications

  name               = each.value.app_name
  slug               = each.key
  protocol_provider  = authentik_provider_oauth2.app[each.key].id
  meta_description   = each.value.description
  meta_launch_url    = each.value.launch_url
  open_in_new_tab    = true
  policy_engine_mode = "all"
}

resource "authentik_policy_binding" "gate" {
  for_each = local.oauth_applications

  target  = authentik_application.app[each.key].uuid
  policy  = authentik_policy_expression.gate[each.value.gate].id
  order   = 0
  enabled = true
}

resource "authentik_policy_binding" "mfa" {
  for_each = local.oauth_applications

  target  = authentik_application.app[each.key].uuid
  policy  = authentik_policy_expression.gate["homelab-mfa-required"].id
  order   = 10
  enabled = true
}
