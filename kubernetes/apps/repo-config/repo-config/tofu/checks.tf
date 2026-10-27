locals {
  repos_readable_anonymously = {
    for name, settings in local.repos : name => settings if !try(settings.private, false)
  }
}

data "http" "live_repo" {
  for_each = local.repos_readable_anonymously
  url      = "${var.forgejo_url}/api/v1/repos/${local.owner}/${each.key}"
}

locals {
  live = {
    for name, response in data.http.live_repo : name => try(jsondecode(response.response_body), {})
  }

  write_only_fields = [
    "default_delete_branch_after_merge",
    "allow_fast_forward_only_merge",
  ]

  write_only_drift = flatten([
    for name, settings in local.repos_readable_anonymously : [
      for field in local.write_only_fields :
      format("%s.%s model=%s live=%s", name, field, settings[field], try(local.live[name][field], "unreadable"))
      if try(local.live[name][field], null) != settings[field]
    ]
  ])

  resent_provider_defaults = {
    allow_rebase_update           = true
    default_allow_maintainer_edit = false
    default_update_style          = "merge"
    globally_editable_wiki        = false
  }

  resent_default_drift = flatten([
    for name in keys(local.repos_readable_anonymously) : [
      for field, value in local.resent_provider_defaults :
      format("%s.%s sent=%s live=%s", name, field, value, try(local.live[name][field], "unreadable"))
      if try(local.live[name][field], null) != value
    ]
  ])
}

check "write_only_fields_match_live" {
  assert {
    condition     = length(local.write_only_drift) == 0
    error_message = "Write-only fields in the model differ from live Forgejo: ${join(", ", local.write_only_drift)}"
  }
}

check "resent_provider_defaults_match_live" {
  assert {
    condition     = length(local.resent_default_drift) == 0
    error_message = "A repository update re-sends these provider defaults over a different live value: ${join(", ", local.resent_default_drift)}"
  }
}

data "http" "org_repos" {
  for_each = toset(["1", "2", "3", "4"])
  url      = "${var.forgejo_url}/api/v1/orgs/${local.owner}/repos?limit=50&page=${each.key}"
}

locals {
  live_active_sources = sort(flatten([
    for page in data.http.org_repos : [
      for repo in try(jsondecode(page.response_body), []) : repo.name
      if !repo.archived && !repo.mirror
    ]
  ]))

  unmodelled_repos = [for name in local.live_active_sources : name if !contains(keys(local.repos), name)]
}

check "every_active_repo_is_modelled" {
  assert {
    condition     = length(local.unmodelled_repos) == 0
    error_message = "Active Forgejo repositories outside the repo-config model get no branch protection: ${join(", ", local.unmodelled_repos)}"
  }
}
