# Sign-only Transit access for the in-cluster Forgejo runner (bound via the cosign-signer
# JWT-auth role on auth/forgejo, which only the release workflow's OIDC token can assume).
# Lets CI sign + attest Harbor images with the
# cosign-webgrip key WITHOUT the key material ever leaving OpenBao. Deliberately minimal:
# sign + read-public-key on the ONE key, and nothing else (no secret reads, no other paths).
path "transit/sign/cosign-webgrip" {
  capabilities = ["update"]
}
path "transit/sign/cosign-webgrip/*" {
  capabilities = ["update"]
}
path "transit/keys/cosign-webgrip" {
  capabilities = ["read"]
}
