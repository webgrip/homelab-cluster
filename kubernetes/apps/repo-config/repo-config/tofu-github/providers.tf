locals {
  read_app_credentials_from_vault = var.local_verification_github_token == ""
  vault_role                      = var.vault_role != "" ? var.vault_role : "github-config-${var.github_owner}"
}

provider "vault" {
  address          = var.vault_address
  skip_child_token = true
  token            = var.vault_token != "" ? var.vault_token : null

  dynamic "auth_login" {
    for_each = var.vault_token == "" && local.read_app_credentials_from_vault ? [1] : []
    content {
      path = "auth/kubernetes/login"
      parameters = {
        role = local.vault_role
        jwt  = file("/var/run/secrets/kubernetes.io/serviceaccount/token")
      }
    }
  }
}

ephemeral "vault_kv_secret_v2" "app" {
  count = local.read_app_credentials_from_vault ? 1 : 0
  mount = "secret"
  name  = local.github_owner.app_secret_path
}

provider "github" {
  owner    = var.github_owner
  base_url = var.github_base_url
  token    = local.read_app_credentials_from_vault ? null : var.local_verification_github_token

  dynamic "app_auth" {
    for_each = local.read_app_credentials_from_vault ? [1] : []
    content {
      id              = ephemeral.vault_kv_secret_v2.app[0].data["app_id"]
      installation_id = ephemeral.vault_kv_secret_v2.app[0].data["installation_id"]
      pem_file        = ephemeral.vault_kv_secret_v2.app[0].data["private_key"]
    }
  }
}
