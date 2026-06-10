# Read-only on the KV v2 engine for External Secrets Operator (bound to the ESO
# ServiceAccount via the kubernetes auth role "external-secrets").
path "secret/data/*" {
  capabilities = ["read"]
}
path "secret/metadata/*" {
  capabilities = ["read", "list"]
}
