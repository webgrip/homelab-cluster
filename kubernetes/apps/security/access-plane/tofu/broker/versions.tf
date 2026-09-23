terraform {
  required_version = "~> 1.12"

  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "2026.5.1"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "5.12.0"
    }
    harbor = {
      source  = "goharbor/harbor"
      version = "3.12.5"
    }
  }
}
