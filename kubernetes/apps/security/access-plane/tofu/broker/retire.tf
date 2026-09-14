locals {
  retired_groups = ["homelab-mfa", "service-accounts"]
  retired_users  = ["svc-homelab"]
}

data "authentik_groups" "retired" {
  for_each = var.adopt_existing ? toset(local.retired_groups) : toset([])
  name     = each.key
}

data "authentik_users" "retired" {
  for_each = var.adopt_existing ? toset(local.retired_users) : toset([])
  username = each.key
}

resource "authentik_group" "retired" {
  for_each     = toset(local.retired_groups)
  name         = each.key
  is_superuser = false

  lifecycle {
    ignore_changes = [users, attributes, parents, roles]
  }
}

resource "authentik_user" "retired" {
  for_each = toset(local.retired_users)
  username = each.key
  name     = each.key

  lifecycle {
    ignore_changes = [name, email, type, is_active, attributes, path, groups]
  }
}

import {
  for_each = { for group, found in data.authentik_groups.retired : group => found.groups[0].pk if length(found.groups) > 0 }
  to       = authentik_group.retired[each.key]
  id       = each.value
}

import {
  for_each = { for user, found in data.authentik_users.retired : user => found.users[0].pk if length(found.users) > 0 }
  to       = authentik_user.retired[each.key]
  id       = tostring(each.value)
}
