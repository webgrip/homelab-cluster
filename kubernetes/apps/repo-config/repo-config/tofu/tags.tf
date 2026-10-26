resource "restapi_object" "tag_protection" {
  for_each = local.tag_protections

  path         = "/repos/${local.owner}/${each.value.repo}/tag_protections"
  id_attribute = "id"
  data = jsonencode({
    name_pattern        = each.value.pattern
    whitelist_usernames = each.value.users
    whitelist_teams     = []
  })

  depends_on = [forgejo_repository.repo]
}
