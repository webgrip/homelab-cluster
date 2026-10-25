#!/bin/sh
set -eu
ROOT="${ROOT:-/data}"
REQUIRED_PATHS="${REQUIRED_PATHS:-}"
FRESH_PATH="${FRESH_PATH:-}"
FRESH_WITHIN_SECONDS="${FRESH_WITHIN_SECONDS:-172800}"
BACKUP_CREATED_AT="${BACKUP_CREATED_AT:-0}"
MIN_FILES="${MIN_FILES:-1}"

fail() {
  echo "FAIL: $*"
  exit 1
}

files="$(find "${ROOT}" -type f 2>/dev/null | wc -l | tr -d ' ')"
[ "${files}" -ge "${MIN_FILES}" ] || fail "corrupt: the restored volume holds ${files} files, expected at least ${MIN_FILES}"
for path in ${REQUIRED_PATHS}; do
  [ -e "${ROOT}/${path}" ] || fail "corrupt: ${path} is missing from the restored volume"
done
if [ -n "${FRESH_PATH}" ]; then
  newest="$(find "${ROOT}/${FRESH_PATH}" -type f -exec stat -c %Y {} + 2>/dev/null | sort -n | tail -n 1)"
  [ -n "${newest}" ] || fail "corrupt: no files under ${FRESH_PATH}"
  lag=$(( BACKUP_CREATED_AT - newest ))
  echo "newest file under ${FRESH_PATH} was written ${lag}s before the backup"
  [ "${lag}" -le "${FRESH_WITHIN_SECONDS}" ] || fail "stale: newest file under ${FRESH_PATH} is ${lag}s older than the backup, limit ${FRESH_WITHIN_SECONDS}s"
fi
echo "verified ${files} files"
