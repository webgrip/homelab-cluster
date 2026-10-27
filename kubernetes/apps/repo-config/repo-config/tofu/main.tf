locals {
  model_dir = var.model_dir != "" ? var.model_dir : "${path.module}/../model"
  profiles  = yamldecode(file("${local.model_dir}/profiles.yaml")).profiles
  kinds     = yamldecode(file("${local.model_dir}/profiles.yaml")).kinds
  model     = yamldecode(file("${local.model_dir}/repos.yaml"))
  owner     = local.model.forgejo.owner

  repos_created_by_tofu = toset([
    "talos-kata-extension",
  ])

  forgejo_repos = {
    for name, repo in local.model.repos : name => merge(repo, {
      profile  = try(repo.profile, local.kinds[repo.kind].profile)
      renovate = try(repo.renovate, local.kinds[repo.kind].renovate, null)
    }) if repo.forge == "forgejo"
  }

  repos = {
    for name, repo in local.forgejo_repos : name => merge(
      local.profiles[repo.profile].forgejo.settings,
      try(local.kinds[repo.kind].settings, {}),
      try(repo.settings, {}),
    )
  }

  branch_protections = merge([
    for name, repo in local.forgejo_repos : {
      for branch in setunion(
        keys(try(local.profiles[repo.profile].forgejo.branches, {})),
        keys(try(local.kinds[repo.kind].branches, {})),
        keys(try(repo.branches, {})),
        ) : "${name}/${branch}" => merge(
        try(local.profiles[repo.profile].forgejo.branches[branch], {}),
        try(local.kinds[repo.kind].branches[branch], {}),
        try(repo.branches[branch], {}),
        { repo = name, branch = branch },
      )
    }
  ]...)

  tag_protections = merge([
    for name, repo in local.forgejo_repos : {
      for pattern, users in merge(
        try(local.profiles[repo.profile].forgejo.tags, {}),
        try(repo.tags, {}),
      ) : "${name}/${pattern}" => { repo = name, pattern = pattern, users = users }
    } if !try(local.repos[name].archived, false)
  ]...)

  owner_merge_guard = {
    rule = "homelab-cluster/main"
    user = "ryangr0"
  }
  owner_can_merge = contains(
    try(local.branch_protections[local.owner_merge_guard.rule].merge, []),
    local.owner_merge_guard.user,
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
  allow_rebase                      = try(each.value.allow_rebase, null)
  archived                          = try(each.value.archived, false)
  private                           = try(each.value.private, false)
  auto_init                         = contains(local.repos_created_by_tofu, each.key) ? false : null
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

  enable_push               = try(length(each.value.push) > 0, true)
  enable_push_whitelist     = try(length(each.value.push) > 0, false) ? true : null
  push_whitelist_usernames  = try(length(each.value.push) > 0 ? each.value.push : null, null)
  enable_merge_whitelist    = try(each.value.merge, null) != null
  merge_whitelist_usernames = try(each.value.merge, null)
  enable_status_check       = length(each.value.status_checks) > 0
  status_check_contexts     = length(each.value.status_checks) > 0 ? each.value.status_checks : null
  required_approvals        = try(each.value.required_approvals, 0)
  dismiss_stale_approvals   = try(each.value.dismiss_stale_approvals, false)
  block_on_rejected_reviews = try(each.value.block_on_rejected_reviews, false)
  block_on_outdated_branch  = try(each.value.block_on_outdated_branch, false)

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = local.owner_can_merge
      error_message = "The model must keep ${local.owner_merge_guard.user} in the merge list of ${local.owner_merge_guard.rule}: nobody pushes to main (ADR-0083), so without it the owner cannot land a change in the GitOps repository at all. Nothing is applied while this fails."
    }
  }
}
