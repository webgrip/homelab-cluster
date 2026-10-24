terraform {
  required_version = "~> 1.12"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "6.13.0"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "5.12.0"
    }
  }
}
