#!/bin/sh
set -eu
OMNIGRAPH_TOKEN_FILE=/run/secrets/omnigraph/token
export OMNIGRAPH_TOKEN_FILE
og() { python3 -I /etc/omnigraph-embed-step/omnigraph_http.py "$@"; }
mkdir -p /work/snapshot
ready_started=$(date +%s)
og ready
echo "omnigraph ready after $(( $(date +%s) - ready_started ))s"
queries=$(sed -n 's/^query \([a-zA-Z0-9_]*\)().*/\1/p' /etc/distill/snapshot.gq)
for query in $queries; do
  if ! og query --graph brain --query /etc/distill/snapshot.gq "$query" > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-distill refused while reading $query on brain/main: $(cat /work/snapshot.err)" >&2
    exit 1
  fi
done
echo "brain snapshot read: queries=$(echo "$queries" | wc -w)"
