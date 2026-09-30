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
queries=$(sed -n 's/^query \([a-zA-Z0-9_]*\)().*/\1/p' /etc/distill/snapshot.gq)
for query in $queries; do
  if ! omnigraph query --server "$OMNIGRAPH_URL" --graph brain --branch main --query /etc/distill/snapshot.gq "$query" --json > "/work/snapshot/$query.json" 2> /work/snapshot.err; then
    echo "omnigraph not reachable or act-distill refused while reading $query on brain/main: $(cat /work/snapshot.err)" >&2
    exit 1
  fi
done
echo "brain snapshot read: queries=$(echo "$queries" | wc -w)"
