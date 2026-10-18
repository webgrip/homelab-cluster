import {
  for_each = local.repos
  to       = forgejo_repository.repo[each.key]
  id       = "${local.owner}/${each.key}"
}
