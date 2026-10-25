#!/bin/sh
set -eu
: "${BUCKET:?}" "${LIFECYCLE_FILE:?}"
: "${WRITER_ACCESS_KEY_ID:?}" "${WRITER_SECRET_ACCESS_KEY:?}" "${WRITER_ENDPOINT:?}"
: "${READER_ACCESS_KEY_ID:?}" "${READER_SECRET_ACCESS_KEY:?}" "${READER_ENDPOINT:?}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-garage}"

AWS_ACCESS_KEY_ID="$WRITER_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$WRITER_SECRET_ACCESS_KEY" \
  aws --endpoint-url "$WRITER_ENDPOINT" s3api put-bucket-lifecycle-configuration \
  --bucket "$BUCKET" --lifecycle-configuration "file://$LIFECYCLE_FILE"

live="$(AWS_ACCESS_KEY_ID="$READER_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$READER_SECRET_ACCESS_KEY" \
  aws --endpoint-url "$READER_ENDPOINT" s3api get-bucket-lifecycle-configuration --bucket "$BUCKET" --output json)"
want="$(jq -S '.Rules | sort_by(.ID)' "$LIFECYCLE_FILE")"
got="$(printf '%s' "$live" | jq -S '.Rules | sort_by(.ID)')"
if [ "$want" != "$got" ]; then
  echo "FAIL: lifecycle on $BUCKET reads back different from git"
  printf 'want: %s\ngot:  %s\n' "$(printf '%s' "$want" | jq -c .)" "$(printf '%s' "$got" | jq -c .)"
  exit 1
fi
echo "lifecycle on $BUCKET matches git: $(printf '%s' "$got" | jq -c '[.[] | {ID, Days: .Expiration.Days}]')"
