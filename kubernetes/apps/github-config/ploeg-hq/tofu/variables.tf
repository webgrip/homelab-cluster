variable "vault_address" {
  type    = string
  default = "http://openbao.security.svc.cluster.local:8200"
}

variable "vault_role" {
  type    = string
  default = "github-config-ploeg-hq"
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
