#!/bin/sh
set -eu
OMNIGRAPH_BEARER_TOKEN=$(cat /run/secrets/omnigraph/token)
export OMNIGRAPH_BEARER_TOKEN
mkdir -p /work/snapshot
ready_timeout=${OMNIGRAPH_READY_TIMEOUT_SECONDS:-300}
ready_by=$(( $(date +%s) + ready_timeout ))
until curl -fsS -o /dev/null --max-time 5 "$OMNIGRAPH_URL/readyz" 2> /work/readyz.err; do
  if [ "$(date +%s)" -ge "$ready_by" ]; then
    echo "omnigraph not ready: $OMNIGRAPH_URL/readyz did not answer 200 within ${ready_timeout}s: $(cat /work/readyz.err)" >&2
    exit 1
  fi
  sleep "${OMNIGRAPH_READY_POLL_SECONDS:-5}"
done
echo "omnigraph ready after $(( $(date +%s) - ready_by + ready_timeout ))s"
awk 'BEGIN { printf "{\"v\":[1.0"; for (i = 1; i < 384; i++) printf ",0.0"; print "]}" }' > /tmp/vector-probe.json
for query in forge_projects forge_orgs forge_people forge_artifacts forge_notes forge_passages forge_project_orgs forge_artifact_projects forge_artifact_people forge_note_projects forge_note_artifacts; do
  if ! omnigraph query --server "$OMNIGRAPH_URL" --graph brain --branch main --query /etc/forge-import/snapshot.gq "$query" --json > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-forge-import refused while reading $query on brain/main: $(cat /work/snapshot.err)" >&2
    exit 1
  fi
done
for query in forge_passages_with_vectors forge_notes_with_vectors; do
  if ! omnigraph query --server "$OMNIGRAPH_URL" --graph brain --branch main --query /etc/forge-import/snapshot.gq "$query" --params-file /tmp/vector-probe.json --json > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-forge-import refused while reading $query on brain/main: $(cat /work/snapshot.err)" >&2
    exit 1
  fi
done
echo "brain snapshot read"
