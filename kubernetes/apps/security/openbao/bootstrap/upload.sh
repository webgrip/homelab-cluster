#!/bin/sh
# Upload the raft snapshot to the off-site Garage (S3), prove it landed intact,
# and prune to the last 14. Every failure exits non-zero so the Job fails and
# OpenBaoSnapshotStale fires. Until 2026-09-30 this script had no `set -e`: a
# failed copy (the endpoint still pointed at the retired LAN Garage) printed
# "uploaded" and exited 0, so no snapshot reached off-site from 08-01 on.
set -eu
[ -s /shared/openbao.snap ] || { echo "no snapshot to upload"; exit 1; }
EP="${S3_ENDPOINT}"
# Default to HTTPS when S3_ENDPOINT carries no scheme, so raft snapshots (the
# cluster's secret material) never travel in plaintext off-LAN. An explicit
# http:// in S3_ENDPOINT still wins.
case "${EP}" in http://*|https://*) ;; *) EP="https://${EP}" ;; esac
KEY="openbao-snapshots/openbao-$(date +%Y%m%d-%H%M%S).snap"
LOCAL_SHA="$(sha256sum /shared/openbao.snap | cut -d' ' -f1)"
aws --endpoint-url "${EP}" s3 cp /shared/openbao.snap "s3://${S3_BUCKET}/${KEY}"

# Read the object back and compare. A full Garage disk acknowledges a PUT but
# stores an empty block, so a size check alone would pass a corrupt snapshot.
aws --endpoint-url "${EP}" s3 cp "s3://${S3_BUCKET}/${KEY}" /tmp/verify.snap
REMOTE_SHA="$(sha256sum /tmp/verify.snap | cut -d' ' -f1)"
rm -f /tmp/verify.snap
if [ "${REMOTE_SHA}" != "${LOCAL_SHA}" ]; then
  echo "s3://${S3_BUCKET}/${KEY} reads back as ${REMOTE_SHA}, expected ${LOCAL_SHA}"
  exit 1
fi
echo "uploaded and verified s3://${S3_BUCKET}/${KEY} (sha256 ${LOCAL_SHA})"

# retention: keep the newest 14 snapshots. The listing runs on its own so a
# failure stops the script instead of silently pruning nothing.
LISTING="$(aws --endpoint-url "${EP}" s3 ls "s3://${S3_BUCKET}/openbao-snapshots/")"
echo "${LISTING}" | awk '{ print $4 }' | grep -v '^$' | sort | head -n -14 | while read -r old; do
  echo "pruning ${old}"
  aws --endpoint-url "${EP}" s3 rm "s3://${S3_BUCKET}/openbao-snapshots/${old}"
done
