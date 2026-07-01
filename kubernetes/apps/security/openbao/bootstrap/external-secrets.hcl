# Read-only on the KV v2 engine for External Secrets Operator (bound to the ESO
# ServiceAccount via the kubernetes auth role "external-secrets").
path "secret/data/*" {
  capabilities = ["read"]
}
path "secret/metadata/*" {
  capabilities = ["read", "list"]
}
# Dynamic Postgres credentials (ADR-0010): ESO mints a fresh lease on each refresh by
# reading the database engine's creds path. Read-only; the config-admin policy manages the
# connections/roles, ESO only issues from them.
path "database/creds/*" {
  capabilities = ["read"]
}
