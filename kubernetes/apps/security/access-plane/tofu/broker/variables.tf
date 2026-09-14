variable "adopt_existing" {
  type    = bool
  default = false
}

variable "vault_address" {
  type    = string
  default = "http://openbao.security.svc.cluster.local:8200"
}

variable "vault_token" {
  type      = string
  default   = ""
  sensitive = true
}

variable "authentik_url" {
  type    = string
  default = "http://authentik-server.authentik.svc.cluster.local"
}
