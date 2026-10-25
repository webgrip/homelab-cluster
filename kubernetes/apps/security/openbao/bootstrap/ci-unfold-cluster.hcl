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

path "secret/data/unfold/tailnet-homelab-gateway" {
  capabilities = ["create", "read", "update"]
}

path "secret/data/unfold-cluster/talos-secrets" {
  capabilities = ["create", "read", "update"]
}

path "secret/data/unfold/headscale-address" {
  capabilities = ["create", "read", "update"]
}

path "secret/data/hetzner/unfold-drill" {
  capabilities = ["read"]
}

path "secret/data/hetzner/unfold-robot" {
  capabilities = ["read"]
}

path "secret/data/unfold-cluster/metal/*" {
  capabilities = ["create", "read", "update"]
}
