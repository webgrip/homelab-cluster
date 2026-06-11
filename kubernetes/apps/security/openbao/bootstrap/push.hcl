# Write access on the KV, used ONLY by ESO PushSecret to seed existing Secrets into
# OpenBao during the SOPS->ESO migration. Remove the openbao-push store + this role
# once migration is complete to return ESO to read-only.
path "secret/data/*" {
  capabilities = ["create", "update", "read"]
}
path "secret/metadata/*" {
  capabilities = ["read", "list"]
}
