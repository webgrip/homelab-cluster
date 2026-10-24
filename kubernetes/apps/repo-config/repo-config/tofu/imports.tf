import {
  for_each = { for name, repo in local.repos : name => repo if !contains(local.repos_created_by_tofu, name) }
  to       = forgejo_repository.repo[each.key]
  id       = "${local.owner}/${each.key}"
}

locals {
  branch_protections_live_before_tofu = toset([
    "claude-config/main",
    "homelab-cluster/main",
    "unfold/development",
    "unfold/main",
    "workflows/main",
  ])
}

import {
  for_each = local.branch_protections_live_before_tofu
  to       = forgejo_branch_protection.rule[each.key]
  id       = "${local.owner}/${each.key}"
}
