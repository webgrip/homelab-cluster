import {
  for_each = local.active_repos
  to       = github_repository.repo[each.key]
  id       = each.value.name
}

import {
  for_each = local.archived_repos
  to       = github_repository.archived[each.key]
  id       = each.value.name
}

import {
  for_each = local.active_repos
  to       = github_branch_default.default[each.key]
  id       = each.value.name
}

import {
  for_each = local.active_repos
  to       = github_actions_repository_permissions.actions[each.key]
  id       = each.value.name
}

import {
  for_each = local.active_repos
  to       = github_workflow_repository_permissions.workflow[each.key]
  id       = each.value.name
}

import {
  for_each = local.rulesets
  to       = github_repository_ruleset.ruleset[each.key]
  id       = "${local.repos[each.value.repo].name}:${each.value.id}"
}

import {
  for_each = local.release_consumers
  to       = github_actions_variable.release_consumers[each.key]
  id       = "${local.repos[each.key].name}:RELEASE_CONSUMERS"
}
