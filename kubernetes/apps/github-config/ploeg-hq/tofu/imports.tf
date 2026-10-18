import {
  to = github_repository.repo
  id = local.repository
}

import {
  to = github_branch_default.default
  id = local.repository
}

import {
  to = github_actions_repository_permissions.actions
  id = local.repository
}

import {
  to = github_workflow_repository_permissions.workflow
  id = local.repository
}

import {
  for_each = local.rulesets
  to       = github_repository_ruleset.ruleset[each.key]
  id       = "${local.repository}:${each.value.id}"
}
