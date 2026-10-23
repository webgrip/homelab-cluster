locals {
  model_dir = var.model_dir != "" ? var.model_dir : "${path.module}/../model"
  profiles  = yamldecode(file("${local.model_dir}/profiles.yaml")).profiles
  model     = yamldecode(file("${local.model_dir}/repos.yaml"))
  owner     = local.model.owner

  repos = {
    for name, repo in local.model.repos : name => merge(
      local.profiles[repo.profile].settings,
      try(repo.settings, {}),
    )
  }

  branch_protections = merge([
    for name, repo in local.model.repos : {
      for branch, rule in merge(
        try(local.profiles[repo.profile].branches, {}),
        try(repo.branches, {}),
      ) : "${name}/${branch}" => merge(rule, { repo = name, branch = branch })
    }
  ]...)

  owner_push_guard = {
    rule = "homelab-cluster/main"
    user = "ryangr0"
  }
  owner_keeps_trunk_push = contains(
    try(local.branch_protections[local.owner_push_guard.rule].push, []),
    local.owner_push_guard.user,
  )
}

resource "forgejo_repository" "repo" {
  for_each = local.repos

  owner = local.owner
  name  = each.key

  has_actions                       = each.value.has_actions
  has_pull_requests                 = each.value.has_pull_requests
  has_releases                      = each.value.has_releases
  default_merge_style               = each.value.default_merge_style
  default_delete_branch_after_merge = each.value.default_delete_branch_after_merge
  allow_fast_forward_only_merge     = each.value.allow_fast_forward_only_merge
  allow_squash_merge                = each.value.allow_squash_merge
  archived                          = try(each.value.archived, false)
  archive_on_destroy                = true

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [clone_addr]
  }
}

resource "forgejo_branch_protection" "rule" {
  for_each = local.branch_protections

  repository_id = forgejo_repository.repo[each.value.repo].id
  branch_name   = each.value.branch

  enable_push               = true
  enable_push_whitelist     = try(each.value.push, null) != null
  push_whitelist_usernames  = try(each.value.push, null)
  enable_merge_whitelist    = try(each.value.merge, null) != null
  merge_whitelist_usernames = try(each.value.merge, null)
  enable_status_check       = length(each.value.status_checks) > 0
  status_check_contexts     = length(each.value.status_checks) > 0 ? each.value.status_checks : null

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = local.owner_keeps_trunk_push
      error_message = "The model must keep ${local.owner_push_guard.user} in the push list of ${local.owner_push_guard.rule}: without it the owner is locked out of trunk pushes (2026-08-05). Nothing is applied while this fails."
    }
  }
}
