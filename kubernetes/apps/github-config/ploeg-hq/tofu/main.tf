locals {
  model_dir  = var.model_dir != "" ? var.model_dir : "${path.module}/../model"
  model      = yamldecode(file("${local.model_dir}/ploeg-hq.yaml"))
  owner      = local.model.owner
  repository = local.model.repository
  settings   = local.model.settings
  rulesets   = local.model.rulesets

  release_consumers = local.model.release_consumers_enabled ? { RELEASE_CONSUMERS = local.model.release_consumers } : {}
}

resource "github_repository" "repo" {
  name       = local.repository
  visibility = local.settings.visibility

  has_issues      = local.settings.has_issues
  has_projects    = local.settings.has_projects
  has_wiki        = local.settings.has_wiki
  has_discussions = local.settings.has_discussions

  allow_merge_commit          = local.settings.allow_merge_commit
  allow_squash_merge          = local.settings.allow_squash_merge
  allow_rebase_merge          = local.settings.allow_rebase_merge
  allow_auto_merge            = local.settings.allow_auto_merge
  allow_update_branch         = local.settings.allow_update_branch
  delete_branch_on_merge      = local.settings.delete_branch_on_merge
  web_commit_signoff_required = local.settings.web_commit_signoff_required
  squash_merge_commit_title   = local.settings.squash_merge_commit_title
  squash_merge_commit_message = local.settings.squash_merge_commit_message
  merge_commit_title          = local.settings.merge_commit_title
  merge_commit_message        = local.settings.merge_commit_message

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [ignore_vulnerability_alerts_during_read]
  }
}

resource "github_branch_default" "default" {
  repository = github_repository.repo.name
  branch     = local.settings.default_branch

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_actions_repository_permissions" "actions" {
  repository      = github_repository.repo.name
  enabled         = local.settings.actions_enabled
  allowed_actions = local.settings.allowed_actions
}

resource "github_workflow_repository_permissions" "workflow" {
  repository                       = github_repository.repo.name
  default_workflow_permissions     = local.settings.default_workflow_permissions
  can_approve_pull_request_reviews = local.settings.can_approve_pull_request_reviews
}

resource "github_repository_ruleset" "ruleset" {
  for_each = local.rulesets

  repository  = github_repository.repo.name
  name        = each.value.name
  target      = each.value.target
  enforcement = "active"

  conditions {
    ref_name {
      include = each.value.include
      exclude = []
    }
  }

  dynamic "bypass_actors" {
    for_each = each.value.bypass_repository_role_ids
    content {
      actor_id    = bypass_actors.value
      actor_type  = "RepositoryRole"
      bypass_mode = "always"
    }
  }

  rules {
    deletion         = each.value.deletion
    non_fast_forward = each.value.non_fast_forward
    update           = each.value.update

    dynamic "required_status_checks" {
      for_each = length(each.value.required_status_checks) > 0 ? [each.value.required_status_checks] : []
      content {
        strict_required_status_checks_policy = false
        do_not_enforce_on_create             = false

        dynamic "required_check" {
          for_each = required_status_checks.value
          content {
            context        = required_check.value.context
            integration_id = required_check.value.integration_id
          }
        }
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_actions_variable" "release_consumers" {
  for_each = local.release_consumers

  repository    = github_repository.repo.name
  variable_name = each.key
  value         = each.value

  lifecycle {
    precondition {
      condition     = can(jsondecode(each.value))
      error_message = "release_consumers in the model is not valid JSON."
    }
  }
}
