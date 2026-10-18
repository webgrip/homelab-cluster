variable "vault_address" {
  type    = string
  default = "http://openbao.security.svc.cluster.local:8200"
}

variable "vault_role" {
  type    = string
  default = "forgejo-repo-config"
}

variable "forgejo_url" {
  type    = string
  default = "http://forgejo-http.forgejo.svc.cluster.local:3000"
}

variable "model_dir" {
  type    = string
  default = ""
}

variable "vault_token" {
  type      = string
  default   = ""
  sensitive = true
}
