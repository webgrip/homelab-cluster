resource "authentik_user" "human" {
  for_each = module.model.humans

  username  = each.value.username
  name      = each.value.name
  email     = each.key
  type      = "internal"
  is_active = true

  lifecycle {
    ignore_changes = [attributes, path]
  }
}

resource "authentik_group" "group" {
  for_each = toset(module.model.authentik_groups)

  name         = each.key
  is_superuser = false
  users        = [for email in module.model.group_members[each.key] : tonumber(authentik_user.human[email].id)]
}
