data "authentik_users" "adopt" {
  for_each = var.adopt_existing ? module.model.humans : {}
  email    = each.key
}

data "authentik_groups" "adopt" {
  for_each = var.adopt_existing ? toset(module.model.authentik_groups) : toset([])
  name     = each.key
}

data "authentik_provider_oauth2_config" "adopt" {
  for_each = var.adopt_existing ? local.oauth_applications : {}
  name     = each.value.provider_name
}

data "authentik_property_mapping_provider_scope" "adopt" {
  for_each = var.adopt_existing ? local.scope_mappings : {}
  name     = each.key
}

data "authentik_policy_expression" "adopt" {
  for_each = var.adopt_existing ? local.expression_policies : {}
  name     = each.key
}

data "vault_identity_group" "adopt" {
  count      = var.adopt_existing ? 1 : 0
  group_name = "openbao-admins"
}

import {
  for_each = { for email, found in data.authentik_users.adopt : email => found.users[0].pk if length(found.users) > 0 }
  to       = authentik_user.human[each.key]
  id       = tostring(each.value)
}

import {
  for_each = { for group, found in data.authentik_groups.adopt : group => found.groups[0].pk if length(found.groups) > 0 }
  to       = authentik_group.group[each.key]
  id       = each.value
}

import {
  for_each = data.authentik_provider_oauth2_config.adopt
  to       = authentik_provider_oauth2.app[each.key]
  id       = each.value.id
}

import {
  for_each = var.adopt_existing ? local.oauth_applications : {}
  to       = authentik_application.app[each.key]
  id       = each.key
}

import {
  for_each = data.authentik_property_mapping_provider_scope.adopt
  to       = authentik_property_mapping_provider_scope.app[each.key]
  id       = each.value.id
}

import {
  for_each = data.authentik_policy_expression.adopt
  to       = authentik_policy_expression.gate[each.key]
  id       = each.value.id
}

import {
  for_each = toset(var.adopt_existing ? ["oidc"] : [])
  to       = vault_jwt_auth_backend.oidc
  id       = each.key
}

import {
  for_each = toset(var.adopt_existing ? ["auth/oidc/role/default"] : [])
  to       = vault_jwt_auth_backend_role.default
  id       = each.key
}

import {
  for_each = toset(var.adopt_existing ? [data.vault_identity_group.adopt[0].group_id] : [])
  to       = vault_identity_group.openbao_admins
  id       = each.key
}

import {
  for_each = toset(var.adopt_existing ? [data.vault_identity_group.adopt[0].alias_id] : [])
  to       = vault_identity_group_alias.homelab_admins
  id       = each.key
}
