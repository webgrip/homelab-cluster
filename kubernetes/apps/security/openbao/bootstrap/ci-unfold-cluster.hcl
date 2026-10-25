path "secret/data/hetzner/unfold-tofu" {
  capabilities = ["read"]
}

path "secret/data/hetzner/unfold-cluster" {
  capabilities = ["read"]
}

path "secret/data/hetzner/unfold-vip" {
  capabilities = ["read"]
}

path "secret/data/unfold-cluster/tofu-state" {
  capabilities = ["read"]
}

path "secret/data/unfold-cluster/etcd-backup" {
  capabilities = ["read"]
}
