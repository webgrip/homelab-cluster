moved {
  from = github_repository.repo
  to   = github_repository.repo["ploeg-hq/ploeg"]
}

moved {
  from = github_branch_default.default
  to   = github_branch_default.default["ploeg-hq/ploeg"]
}

moved {
  from = github_actions_repository_permissions.actions
  to   = github_actions_repository_permissions.actions["ploeg-hq/ploeg"]
}

moved {
  from = github_workflow_repository_permissions.workflow
  to   = github_workflow_repository_permissions.workflow["ploeg-hq/ploeg"]
}

moved {
  from = github_repository_ruleset.ruleset["protect-development"]
  to   = github_repository_ruleset.ruleset["ploeg-hq/ploeg/protect-development"]
}

moved {
  from = github_repository_ruleset.ruleset["protect-main"]
  to   = github_repository_ruleset.ruleset["ploeg-hq/ploeg/protect-main"]
}

moved {
  from = github_repository_ruleset.ruleset["release-tags-immutable"]
  to   = github_repository_ruleset.ruleset["ploeg-hq/ploeg/release-tags-immutable"]
}

moved {
  from = github_actions_variable.release_consumers["RELEASE_CONSUMERS"]
  to   = github_actions_variable.release_consumers["ploeg-hq/ploeg"]
}
