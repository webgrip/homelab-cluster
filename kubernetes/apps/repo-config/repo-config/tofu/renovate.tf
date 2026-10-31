locals {
  renovate_config_repo = "local>webgrip/renovate-config"

  renovate_policy = {
    for name, repo in local.forgejo_repos : name => {
      config_file = try(repo.renovate.config_file, "renovate.json")
      absent      = try(repo.renovate.absent, false)
      presets = tolist(try(
        ["${local.renovate_config_repo}:${repo.renovate.gate}"],
        repo.renovate.presets,
        [],
      ))
    } if try(repo.renovate, null) != null && contains(keys(local.repos_readable_anonymously), name)
  }

  json5_extends_array = "(?m)^\\s*\"?extends\"?\\s*:\\s*\\[([^\\]]*)\\]"
  json5_line_comment  = "/(?m)//.*$/"
  quoted_string       = "[\"']([^\"'\\s]+)[\"']"
}

data "http" "renovate_config" {
  for_each = local.renovate_policy
  url      = "${var.forgejo_url}/api/v1/repos/${local.owner}/${each.key}/raw/${each.value.config_file}"
}

locals {
  renovate_live_extends = {
    for name, response in data.http.renovate_config : name => (
      response.status_code != 200 ? null :
      endswith(local.renovate_policy[name].config_file, ".json5") ? tolist(try(flatten(regexall(
        local.quoted_string,
        replace(regex(local.json5_extends_array, response.response_body)[0], local.json5_line_comment, ""),
      )), [])) :
      tolist(try(jsondecode(response.response_body).extends, []))
    )
  }

  renovate_live_presets = {
    for name, extends in local.renovate_live_extends : name => (
      extends == null ? null : [for entry in extends : split("#", entry)[0]]
    )
  }

  renovate_policy_drift = flatten([
    for name, policy in local.renovate_policy : (
      data.http.renovate_config[name].status_code == 404 ? (
        policy.absent ? [] : ["${name}: ${policy.config_file} is missing on the default branch"]
      ) :
      data.http.renovate_config[name].status_code != 200 ? [
        "${name}: ${policy.config_file} unreadable (HTTP ${data.http.renovate_config[name].status_code})"
      ] :
      policy.absent ? ["${name}: the model says no Renovate config, live has ${policy.config_file}"] :
      jsonencode(local.renovate_live_presets[name]) == jsonencode(policy.presets) ? [] : [
        "${name}: extends model=[${join(", ", policy.presets)}] live=[${join(", ", local.renovate_live_presets[name])}]"
      ]
    )
  ])

  renovate_unpinned_extends = flatten([
    for name, extends in local.renovate_live_extends : [
      for entry in(extends == null ? [] : extends) : "${name}: ${entry}"
      if can(regex("^[a-z]+>", entry)) && !strcontains(entry, "#")
    ]
  ])
}

check "renovate_policy_matches_live" {
  assert {
    condition     = length(local.renovate_policy_drift) == 0
    error_message = "Renovate config on the default branch differs from the model, ignoring #vX.Y.Z pins: ${join("; ", local.renovate_policy_drift)}"
  }
}

check "renovate_extends_pinned" {
  assert {
    condition     = length(local.renovate_unpinned_extends) == 0
    error_message = "Renovate extends without a #vX.Y.Z pin follow the preset repository's default branch: ${join("; ", local.renovate_unpinned_extends)}"
  }
}

output "renovate_policy_drift" {
  value = {
    drift    = local.renovate_policy_drift
    unpinned = local.renovate_unpinned_extends
  }
}
