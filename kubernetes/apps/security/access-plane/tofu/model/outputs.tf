output "humans" {
  value = {
    for email, p in local.humans : email => {
      name     = p.name
      username = p.username
    }
  }
}

output "authentik_groups" {
  value = local.authentik_groups
}

output "group_members" {
  value = local.group_members
}

output "cluster_bindings" {
  value = local.cluster_bindings
}

output "namespace_bindings" {
  value = local.namespace_bindings
}
