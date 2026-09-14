provider "vault" {
  address = var.vault_address
  token   = var.vault_token != "" ? var.vault_token : null

  dynamic "auth_login" {
    for_each = var.vault_token == "" ? [1] : []
    content {
      path = "auth/kubernetes/login"
      parameters = {
        role = "access-plane"
        jwt  = file("/var/run/secrets/kubernetes.io/serviceaccount/token")
      }
    }
  }
}

provider "authentik" {
  url   = var.authentik_url
  token = ephemeral.vault_kv_secret_v2.authentik.data["AUTHENTIK_BOOTSTRAP_TOKEN"]
}
