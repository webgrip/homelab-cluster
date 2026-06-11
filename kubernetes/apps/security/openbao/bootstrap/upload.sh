#!/bin/sh
# Upload the raft snapshot to Garage (S3) and prune to the last 14.
[ -s /shared/openbao.snap ] || { echo "no snapshot to upload"; exit 1; }
EP="${S3_ENDPOINT}"
case "${EP}" in http*) ;; *) EP="http://${EP}" ;; esac
KEY="openbao-snapshots/openbao-$(date +%Y%m%d-%H%M%S).snap"
aws --endpoint-url "${EP}" s3 cp /shared/openbao.snap "s3://${S3_BUCKET}/${KEY}"
echo "uploaded s3://${S3_BUCKET}/${KEY}"

# retention: keep the newest 14 snapshots
aws --endpoint-url "${EP}" s3 ls "s3://${S3_BUCKET}/openbao-snapshots/" 2>/dev/null \
  | awk '{ print $4 }' | grep -v '^$' | sort | head -n -14 | while read -r old; do
  echo "pruning ${old}"
  aws --endpoint-url "${EP}" s3 rm "s3://${S3_BUCKET}/openbao-snapshots/${old}"
done
