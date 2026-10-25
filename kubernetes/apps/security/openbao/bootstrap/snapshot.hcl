path "sys/storage/raft/snapshot" {
  capabilities = ["read"]
}

path "secret/data/backup-canary/openbao" {
  capabilities = ["create", "update"]
}
