#!/bin/sh
set -eu
MAX_SNAPSHOT_AGE_SECONDS="${MAX_SNAPSHOT_AGE_SECONDS:-108000}"
EP="${S3_ENDPOINT}"
case "${EP}" in http://*|https://*) ;; *) EP="https://${EP}" ;; esac

newest="$(aws --endpoint-url "${EP}" s3 ls "s3://${S3_BUCKET}/openbao-snapshots/" | awk '{ print $4 }' | grep '^openbao-[0-9]\{8\}-[0-9]\{6\}\.snap$' | sort | tail -n 1)"
[ -n "${newest}" ] || { echo "FAIL: stale: no snapshot under s3://${S3_BUCKET}/openbao-snapshots/"; exit 1; }
stamp="$(echo "${newest}" | sed -E 's/^openbao-([0-9]{4})([0-9]{2})([0-9]{2})-([0-9]{2})([0-9]{2})([0-9]{2})\.snap$/\1-\2-\3 \4:\5:\6/')"
age=$(( $(date -u +%s) - $(date -u -d "${stamp}" +%s) ))
echo "newest snapshot ${newest}, taken ${age}s ago"
[ "${age}" -le "${MAX_SNAPSHOT_AGE_SECONDS}" ] || { echo "FAIL: stale: newest snapshot is ${age}s old, limit ${MAX_SNAPSHOT_AGE_SECONDS}s"; exit 1; }
aws --endpoint-url "${EP}" s3 cp "s3://${S3_BUCKET}/openbao-snapshots/${newest}" /shared/openbao.snap >/dev/null
echo "${newest}" > /shared/snapshot-name
