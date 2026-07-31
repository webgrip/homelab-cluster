#!/bin/sh
# Upload the raft snapshot to Garage (S3) and prune to the last 14.
[ -s /shared/openbao.snap ] || { echo "no snapshot to upload"; exit 1; }
EP="${S3_ENDPOINT}"
# Default to HTTPS when S3_ENDPOINT carries no scheme. This used to default to
# http://, which was harmless while the endpoint was a LAN Garage but would ship
# raft snapshots — the cluster's secret material — in plaintext the moment the
# endpoint moves off-LAN. Explicit http:// in S3_ENDPOINT still wins, so the
# current LAN endpoint is unaffected.
case "${EP}" in http://*|https://*) ;; *) EP="https://${EP}" ;; esac
KEY="openbao-snapshots/openbao-$(date +%Y%m%d-%H%M%S).snap"
aws --endpoint-url "${EP}" s3 cp /shared/openbao.snap "s3://${S3_BUCKET}/${KEY}"
echo "uploaded s3://${S3_BUCKET}/${KEY}"

# retention: keep the newest 14 snapshots
aws --endpoint-url "${EP}" s3 ls "s3://${S3_BUCKET}/openbao-snapshots/" 2>/dev/null \
  | awk '{ print $4 }' | grep -v '^$' | sort | head -n -14 | while read -r old; do
  echo "pruning ${old}"
  aws --endpoint-url "${EP}" s3 rm "s3://${S3_BUCKET}/openbao-snapshots/${old}"
done
