terraform {
  required_version = "~> 1.12"

  required_providers {
    forgejo = {
      source  = "svalabs/forgejo"
      version = "1.7.0"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "5.12.0"
    }
    restapi = {
      source  = "Mastercard/restapi"
      version = "2.0.1"
    }
    http = {
      source  = "hashicorp/http"
      version = "3.5.0"
    }
  }
}
