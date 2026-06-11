# Read-only on the raft snapshot endpoint, for the openbao-snapshot CronJob.
path "sys/storage/raft/snapshot" {
  capabilities = ["read"]
}
