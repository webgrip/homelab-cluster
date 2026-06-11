#!/bin/sh
# Take a raft snapshot, authenticating via Kubernetes auth (SA openbao-snapshot ->
# snapshot policy). Writes to the shared volume for the upload container.
export BAO_ADDR="http://openbao.security.svc.cluster.local:8200"
JWT="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
BAO_TOKEN="$(bao write -field=token auth/kubernetes/login role=openbao-snapshot jwt="${JWT}")"
export BAO_TOKEN
bao operator raft snapshot save /shared/openbao.snap
echo "snapshot written: $(ls -l /shared/openbao.snap)"
