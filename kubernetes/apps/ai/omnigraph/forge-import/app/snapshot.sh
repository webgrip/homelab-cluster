#!/bin/sh
set -eu
OMNIGRAPH_BEARER_TOKEN=$(cat /run/secrets/omnigraph/token)
export OMNIGRAPH_BEARER_TOKEN
mkdir -p /work/snapshot
for query in forge_projects forge_orgs forge_people forge_artifacts forge_notes forge_passages forge_project_orgs forge_artifact_projects forge_artifact_people forge_note_projects forge_note_artifacts; do
  if ! omnigraph query --server "$OMNIGRAPH_URL" --graph brain --branch main --query /etc/forge-import/snapshot.gq "$query" --json > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-forge-import refused while reading $query on brain/main" >&2
    exit 1
  fi
done
echo "brain snapshot read"
