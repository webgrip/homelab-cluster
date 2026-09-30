#!/bin/sh
set -eu
OMNIGRAPH_BEARER_TOKEN=$(cat /run/secrets/omnigraph/token)
export OMNIGRAPH_BEARER_TOKEN
mkdir -p /work/snapshot
awk 'BEGIN { printf "{\"v\":[1.0"; for (i = 1; i < 384; i++) printf ",0.0"; print "]}" }' > /tmp/vector-probe.json
for query in vault_notes vault_links vault_shadow_artifacts vault_passages vault_note_artifacts vault_notes_with_vectors vault_passages_with_vectors; do
  case "$query" in
    *_with_vectors) params="--params-file /tmp/vector-probe.json" ;;
    *) params="" ;;
  esac
  if ! omnigraph query --server "$OMNIGRAPH_URL" --graph brain --branch main --query /etc/vault-import/snapshot.gq "$query" $params --json > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-vault-import refused while reading $query on brain/main" >&2
    exit 1
  fi
done
echo "brain snapshot read"
