data "authentik_users" "adopt" {
  for_each = var.adopt_existing ? module.model.humans : {}
  email    = each.key
}

data "authentik_groups" "adopt" {
  for_each = var.adopt_existing ? toset(module.model.authentik_groups) : toset([])
  name     = each.key
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
