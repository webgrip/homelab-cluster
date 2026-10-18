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
  archive_on_destroy                = true

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [clone_addr]
  }
}
