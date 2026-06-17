# Read-only access to the cosign Transit PUBLIC key, for the in-cluster publisher that
# mirrors it into the cosign-webgrip-pub ConfigMap (consumed by the Kyverno verify policy).
# Public key only — no sign, no other paths — so it's safe for an unattended reconciler.
path "transit/keys/cosign-webgrip" {
  capabilities = ["read"]
}
