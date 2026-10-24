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
for query in forge_projects forge_orgs forge_people forge_artifacts forge_notes forge_passages forge_project_orgs forge_artifact_projects forge_artifact_people forge_note_projects forge_note_artifacts; do
  if ! og query --graph brain --query /etc/forge-import/snapshot.gq "$query" > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-forge-import refused while reading $query on brain/main: $(cat /work/snapshot.err)" >&2
    exit 1
  fi
done
for query in forge_passages_with_vectors forge_notes_with_vectors; do
  if ! og query --graph brain --query /etc/forge-import/snapshot.gq "$query" --params-file /tmp/vector-probe.json > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-forge-import refused while reading $query on brain/main: $(cat /work/snapshot.err)" >&2
    exit 1
  fi
done
echo "brain snapshot read"
