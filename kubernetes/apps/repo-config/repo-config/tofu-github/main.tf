locals {
  model_dir    = var.model_dir != "" ? var.model_dir : "${path.module}/../model"
  profiles     = yamldecode(file("${local.model_dir}/profiles.yaml")).profiles
  model        = yamldecode(file("${local.model_dir}/repos.yaml"))
  github_owner = local.model.github.owners[var.github_owner]

  repos = {
    for key, repo in local.model.repos : key => {
      name              = split("/", key)[1]
      settings          = merge(local.profiles[repo.profile].github.settings, try(repo.settings, {}))
      rulesets          = try(repo.rulesets, {})
      release_consumers = try(repo.release_consumers, null)
      mirror_of         = try(repo.mirror_of, null)
    } if repo.forge == "github" && split("/", key)[0] == var.github_owner
  }

  active_repos   = { for key, repo in local.repos : key => repo if !try(repo.settings.archived, false) && repo.mirror_of == null }
  archived_repos = { for key, repo in local.repos : key => repo if try(repo.settings.archived, false) }

  rulesets = merge([
    for key, repo in local.active_repos : {
      for ruleset, rule in repo.rulesets : "${key}/${ruleset}" => merge(rule, { repo = key })
    }
  ]...)

  release_consumers = {
    for key, repo in local.active_repos : key => repo.release_consumers if repo.release_consumers != null
  }
}

resource "github_repository" "repo" {
  for_each = local.active_repos

  name       = each.value.name
  visibility = each.value.settings.visibility

  has_issues      = each.value.settings.has_issues
  has_projects    = each.value.settings.has_projects
  has_wiki        = each.value.settings.has_wiki
  has_discussions = each.value.settings.has_discussions

  allow_merge_commit          = each.value.settings.allow_merge_commit
  allow_squash_merge          = each.value.settings.allow_squash_merge
  allow_rebase_merge          = each.value.settings.allow_rebase_merge
  allow_auto_merge            = each.value.settings.allow_auto_merge
  allow_update_branch         = each.value.settings.allow_update_branch
  delete_branch_on_merge      = each.value.settings.delete_branch_on_merge
  web_commit_signoff_required = each.value.settings.web_commit_signoff_required
  squash_merge_commit_title   = each.value.settings.squash_merge_commit_title
  squash_merge_commit_message = each.value.settings.squash_merge_commit_message
  merge_commit_title          = each.value.settings.merge_commit_title
  merge_commit_message        = each.value.settings.merge_commit_message

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [ignore_vulnerability_alerts_during_read]
  }
}

resource "github_repository" "archived" {
  for_each = local.archived_repos

  name     = each.value.name
  archived = true

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      allow_auto_merge,
      allow_forking,
      allow_merge_commit,
      allow_rebase_merge,
      allow_squash_merge,
      allow_update_branch,
      archive_on_destroy,
      auto_init,
      default_branch,
      delete_branch_on_merge,
      description,
      gitignore_template,
      has_discussions,
      has_downloads,
      has_issues,
      has_projects,
      has_wiki,
      homepage_url,
      ignore_vulnerability_alerts_during_read,
      is_template,
      license_template,
      merge_commit_message,
      merge_commit_title,
      pages,
      private,
      security_and_analysis,
      squash_merge_commit_message,
      squash_merge_commit_title,
      template,
      topics,
      visibility,
      vulnerability_alerts,
      web_commit_signoff_required,
    ]
  }
}

resource "github_branch_default" "default" {
  for_each = local.active_repos

  repository = github_repository.repo[each.key].name
  branch     = each.value.settings.default_branch

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_actions_repository_permissions" "actions" {
  for_each = local.active_repos

  repository      = github_repository.repo[each.key].name
  enabled         = each.value.settings.actions_enabled
  allowed_actions = each.value.settings.allowed_actions
}

resource "github_workflow_repository_permissions" "workflow" {
  for_each = local.active_repos

  repository                       = github_repository.repo[each.key].name
  default_workflow_permissions     = each.value.settings.default_workflow_permissions
  can_approve_pull_request_reviews = each.value.settings.can_approve_pull_request_reviews
}

resource "github_repository_ruleset" "ruleset" {
  for_each = local.rulesets

  repository  = github_repository.repo[each.value.repo].name
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

  repository    = github_repository.repo[each.key].name
  variable_name = "RELEASE_CONSUMERS"
  value         = each.value

  lifecycle {
    precondition {
      condition     = can(jsondecode(each.value))
      error_message = "release_consumers of ${each.key} in the model is not valid JSON."
    }
  }
}
