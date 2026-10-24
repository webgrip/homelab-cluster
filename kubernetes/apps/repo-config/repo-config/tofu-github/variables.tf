variable "github_owner" {
  type = string

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+$", var.github_owner))
    error_message = "github_owner must be a GitHub organisation or user name listed under github.owners in the repo-config model."
  }
}

variable "vault_address" {
  type    = string
  default = "http://openbao.security.svc.cluster.local:8200"
}

variable "vault_role" {
  type    = string
  default = ""
}

variable "vault_token" {
  type      = string
  default   = ""
  sensitive = true
}

variable "model_dir" {
  type    = string
  default = ""
}

variable "github_base_url" {
  type    = string
  default = "https://api.github.com/"
}

variable "local_verification_github_token" {
  type      = string
  default   = ""
  sensitive = true
}
