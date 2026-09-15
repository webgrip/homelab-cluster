data "harbor_project" "registry" {
  for_each = toset(module.model.harbor_projects)

  name = each.key
}

resource "authentik_group" "harbor" {
  for_each = module.model.harbor_memberships

  name         = each.value.group
  is_superuser = false
  users        = [for email in each.value.members : tonumber(authentik_user.human[email].id)]
}

resource "harbor_group" "membership" {
  for_each = module.model.harbor_memberships

  group_name = each.value.group
  group_type = 3
}

resource "harbor_project_member_group" "membership" {
  for_each = module.model.harbor_memberships

  project_id = data.harbor_project.registry[each.value.project].id
  group_name = harbor_group.membership[each.key].group_name
  type       = "oidc"
  role       = each.value.role
}

locals {
  group_ids = merge(
    { for name, group in authentik_group.group : name => group.id },
    { for key, group in authentik_group.harbor : group.name => group.id },
  )
}
