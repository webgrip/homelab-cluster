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

output "application_gates" {
  value = {
    for app in distinct(flatten([for c in values(local.capabilities) : try(c.projects.authentik.applications, [])])) :
    app => sort(distinct(flatten([
      for c in values(local.capabilities) : try(c.projects.authentik.groups, [])
      if contains(try(c.projects.authentik.applications, []), app)
    ])))
  }
}

output "cluster_bindings" {
  value = local.cluster_bindings
}

output "namespace_bindings" {
  value = local.namespace_bindings
}
