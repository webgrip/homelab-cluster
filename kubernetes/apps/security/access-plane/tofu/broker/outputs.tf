data "authentik_users" "all" {
  ordering = "pk"
}

output "authentik_users_present" {
  value = [for u in data.authentik_users.all.users : "${u.pk}:${u.username}:${u.type}"]
}

output "authentik_groups_managed" {
  value = keys(authentik_group.group)
}
