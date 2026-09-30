OMNIGRAPH_WRITE_ATTEMPTS=${OMNIGRAPH_WRITE_ATTEMPTS:-8}
OMNIGRAPH_WRITE_FIRST_DELAY=${OMNIGRAPH_WRITE_FIRST_DELAY:-0.2}
omnigraph_write_retries=0
omnigraph_write_failure=""

omnigraph_write_backoff() {
  awk -v attempt="$1" -v first="$OMNIGRAPH_WRITE_FIRST_DELAY" -v seed="$$$1" 'BEGIN { srand(seed); delay = first * 2 ^ (attempt - 1); printf "%.3f", delay + rand() * delay / 2 }'
}

omnigraph_write_class() {
  if grep -q read_set_conflict "$1"; then
    echo read_set_conflict
  elif grep -q key_conflict "$1"; then
    echo key_conflict
  elif grep -qE '(^|[^0-9])503([^0-9]|$)|recovery' "$1"; then
    echo recovery_required
  elif grep -qE '(^|[^0-9])413([^0-9]|$)|length limit|resource_limit' "$1"; then
    echo too_large
  elif grep -qE '(^|[^0-9])40[13]([^0-9]|$)|forbidden|unauthori' "$1"; then
    echo refused
  else
    echo other
  fi
}

omnigraph_write() {
  attempt=1
  while :; do
    if "$@" > "${TMPDIR:-/tmp}/omnigraph-write.out" 2> "${TMPDIR:-/tmp}/omnigraph-write.err"; then
      return 0
    fi
    omnigraph_write_failure=$(omnigraph_write_class "${TMPDIR:-/tmp}/omnigraph-write.err")
    if [ "$omnigraph_write_failure" != read_set_conflict ] || [ "$attempt" -ge "$OMNIGRAPH_WRITE_ATTEMPTS" ]; then
      return 1
    fi
    sleep "$(omnigraph_write_backoff "$attempt")"
    attempt=$((attempt + 1))
    omnigraph_write_retries=$((omnigraph_write_retries + 1))
  done
}
