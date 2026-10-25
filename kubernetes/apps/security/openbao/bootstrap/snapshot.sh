#!/bin/sh
set -eu
export BAO_ADDR="http://openbao.security.svc.cluster.local:8200"
JWT="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
BAO_TOKEN="$(bao write -field=token auth/kubernetes/login role=openbao-snapshot jwt="${JWT}")"
export BAO_TOKEN
bao kv put -mount=secret backup-canary/openbao written_at="$(date +%s)" >/dev/null
bao operator raft snapshot save /shared/openbao.snap
echo "snapshot written: $(ls -l /shared/openbao.snap)"
