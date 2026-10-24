#!/bin/sh
set -eu
OMNIGRAPH_TOKEN_FILE=/run/secrets/omnigraph/token
export OMNIGRAPH_TOKEN_FILE
og() { python3 -I /etc/omnigraph-embed-step/omnigraph_http.py "$@"; }
mkdir -p /work/snapshot
ready_started=$(date +%s)
og ready
echo "omnigraph ready after $(( $(date +%s) - ready_started ))s"
awk 'BEGIN { printf "{\"v\":[1.0"; for (i = 1; i < 384; i++) printf ",0.0"; print "]}" }' > /tmp/vector-probe.json
for query in vault_notes vault_links vault_shadow_artifacts vault_passages vault_note_artifacts vault_notes_with_vectors vault_passages_with_vectors; do
  case "$query" in
    *_with_vectors) params="--params-file /tmp/vector-probe.json" ;;
    *) params="" ;;
  esac
  if ! og query --graph brain --query /etc/vault-import/snapshot.gq "$query" $params > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-vault-import refused while reading $query on brain/main: $(cat /work/snapshot.err)" >&2
    exit 1
  fi
done
echo "brain snapshot read"
