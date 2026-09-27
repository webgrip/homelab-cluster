#!/bin/sh
set -eu
OMNIGRAPH_BEARER_TOKEN=$(cat /run/secrets/omnigraph/token)
export OMNIGRAPH_BEARER_TOKEN
for query in vault_notes vault_links; do
  if ! omnigraph query --server "$OMNIGRAPH_URL" --graph brain --branch main --query /etc/vault-import/snapshot.gq "$query" --json > "/work/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-vault-import refused while reading $query on brain/main" >&2
    exit 1
  fi
done
echo "brain snapshot read"
