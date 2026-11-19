path "secret/data/ploegd-connections/*" {
  capabilities = ["create", "read", "update", "delete"]
}
path "secret/metadata/ploegd-connections/*" {
  capabilities = ["read", "list", "delete"]
}
path "secret/metadata/ploegd-connections" {
  capabilities = ["list"]
}
