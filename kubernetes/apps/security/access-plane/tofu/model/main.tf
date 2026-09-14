locals {
  capabilities = yamldecode(file("${var.model_dir}/capabilities.yaml")).capabilities
  roles        = yamldecode(file("${var.model_dir}/roles.yaml")).roles
  projects     = yamldecode(file("${var.model_dir}/projects.yaml")).projects
  people       = yamldecode(file("${var.model_dir}/people.yaml")).people

  humans = {
    for p in local.people : p.email => p
    if p.kind != "machine" && p.status == "active"
  }

  live_grants = {
    for email, p in local.humans : email => [
      for g in p.grants : g
      if g.until == "none" || timecmp("${g.until}T23:59:59Z", plantimestamp()) >= 0
    ]
  }

  held_before_supersession = {
    for email, p in local.humans : email => concat(
      [for g in local.roles[p.role].grants : {
        capability = g.capability
        scope      = lookup(g, "scope", null)
        project    = null
      }],
      [for g in local.live_grants[email] : {
        capability = g.capability
        scope      = lookup(g, "scope", null)
        project    = lookup(g, "project", null)
      }],
    )
  }

  superseded = {
    for email, held in local.held_before_supersession : email => distinct(flatten([
      for h in held : lookup(local.capabilities[h.capability], "supersedes", [])
    ]))
  }

  held = {
    for email, held in local.held_before_supersession : email => [
      for h in held : h if !contains(local.superseded[email], h.capability)
    ]
  }

  authentik_groups = distinct(flatten([
    for c in values(local.capabilities) : try(c.projects.authentik.groups, [])
  ]))

  group_members = {
    for g in local.authentik_groups : g => sort(distinct([
      for email, held in local.held : email
      if anytrue([for h in held : contains(try(local.capabilities[h.capability].projects.authentik.groups, []), g)])
    ]))
  }

  cluster_roles = distinct([
    for c in values(local.capabilities) : c.projects.kubernetes.clusterRole
    if can(c.projects.kubernetes.clusterRole)
  ])

  cluster_members = {
    for role in local.cluster_roles : role => sort(distinct([
      for email, held in local.held : email
      if anytrue([
        for h in held : try(local.capabilities[h.capability].projects.kubernetes.clusterRole, "") == role && h.scope == "cluster"
      ])
    ]))
  }

  cluster_bindings = { for role, members in local.cluster_members : role => members if length(members) > 0 }

  person_namespaces = {
    for email, p in local.humans : email => distinct(flatten([
      for project in p.projects : local.projects[project].namespaces
    ]))
  }

  namespace_grants = flatten([
    for email, held in local.held : [
      for h in held : [
        for ns in(h.project != null ? local.projects[h.project].namespaces : local.person_namespaces[email]) : {
          key       = "${ns}/${local.capabilities[h.capability].projects.kubernetes.clusterRole}"
          namespace = ns
          role      = local.capabilities[h.capability].projects.kubernetes.clusterRole
          email     = email
        }
      ]
      if h.scope == "project" && can(local.capabilities[h.capability].projects.kubernetes.clusterRole)
    ]
  ])

  namespace_bindings = {
    for key in distinct([for g in local.namespace_grants : g.key]) : key => {
      namespace = [for g in local.namespace_grants : g.namespace if g.key == key][0]
      role      = [for g in local.namespace_grants : g.role if g.key == key][0]
      members   = sort(distinct([for g in local.namespace_grants : g.email if g.key == key]))
    }
  }
}
