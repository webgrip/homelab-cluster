provider "vault" {
  address          = var.vault_address
  skip_child_token = true
  token            = var.vault_token != "" ? var.vault_token : null

  dynamic "auth_login" {
    for_each = var.vault_token == "" ? [1] : []
    content {
      path = "auth/kubernetes/login"
      parameters = {
        role = var.vault_role
        jwt  = file("/var/run/secrets/kubernetes.io/serviceaccount/token")
      }
    }
  }
}

ephemeral "vault_kv_secret_v2" "forgejo_token" {
  mount = "secret"
  name  = "forgejo/repo-config"
}

provider "forgejo" {
  host      = var.forgejo_url
  api_token = ephemeral.vault_kv_secret_v2.forgejo_token.data["FORGEJO_TOKEN"]
}
