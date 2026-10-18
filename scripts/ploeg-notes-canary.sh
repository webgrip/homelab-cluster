#!/usr/bin/env bash
set -euo pipefail

ns=ploeg
port=${PLOEG_CANARY_PORT:-18734}
run_wait_seconds=${PLOEG_CANARY_RUN_WAIT:-900}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
failures=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
note() { printf '      %s\n' "$1"; }

token=$(kubectl -n "$ns" get secret unfold-operator -o jsonpath='{.data.PLOEG_OPERATOR_UNFOLD_TOKEN}' | base64 -d)
db=$(kubectl -n "$ns" get pods -l cnpg.io/cluster=ploeg-db,cnpg.io/instanceRole=primary -o name | head -1)

kubectl -n "$ns" port-forward deploy/ploeg "$port:8080" >/dev/null 2>&1 &
forward=$!
trap 'kill "$forward" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  curl -fsS -m 2 "http://127.0.0.1:$port/healthz" >/dev/null 2>&1 && break
  sleep 1
done

api() {
  curl -sS -m 30 -H "Authorization: Bearer $token" -H "X-Ploeg-Actor: ploeg-notes-canary" \
    -H "X-Ploeg-Acting-User: ${USER:-operator}" -H "Content-Type: application/json" \
    -w '\n%{http_code}' "$@" "http://127.0.0.1:$port${path}"
}
sql() { kubectl -n "$ns" exec "$db" -c postgres -- psql -U postgres -d app -AtX -v ON_ERROR_STOP=1 -c "$1"; }

wait_for_finished_runs() {
  local want=$1 deadline=$((SECONDS + run_wait_seconds))
  while [ "$SECONDS" -lt "$deadline" ]; do
    [ "$(sql "select count(*) from agent_runs where work_item_id = $item and finished_at is not null")" -ge "$want" ] && return 0
    sleep 10
  done
  return 1
}

wait_for_written_notes() {
  local run=$1 deadline=$((SECONDS + 120))
  while [ "$SECONDS" -lt "$deadline" ]; do
    [ "$(sql "select count(*) from work_item_note_outbox where run_id = $run and written_at is null")" -eq 0 ] && return 0
    sleep 5
  done
  return 1
}

check_run() {
  local label=$1 run=$2 want_briefed=$3
  printf '\n%s: Run %s\n' "$label" "$run"
  sql "select outcome, coalesce(stuck_reason, ''), ploegd_version from agent_runs where id = $run" | while IFS= read -r line; do note "$line"; done
  if wait_for_written_notes "$run"; then pass "every note of Run $run reached the notes graph"; else fail "Run $run still has notes waiting in the outbox"; fi
  sql "select note_key, written_by, coalesce(left(graph_commit, 12), ''), coalesce(nullif(last_error, ''), 'ok') from work_item_note_outbox where run_id = $run order by id" | while IFS= read -r line; do note "$line"; done
  local live stop briefed
  live=$(sql "select count(*) from work_item_note_outbox where run_id = $run and note_key like '%/live/%' and graph_commit <> ''")
  stop=$(sql "select count(*) from work_item_note_outbox where run_id = $run and note_key like '%/worker/stop' and graph_commit <> ''")
  briefed=$(sql "select coalesce(max(substring(learning->>'body' from 'briefed=([0-9]+)')::int), -1) from work_item_note_outbox where run_id = $run and note_key like '%/live/%'")
  if [ "$live" -ge 1 ]; then pass "the agent's live note was sent while it worked"; else fail "no live note from Run $run"; fi
  if [ "$stop" -ge 1 ]; then pass "the worker left a stop note"; else fail "no stop note from Run $run"; fi
  if [ "$briefed" -ge "$want_briefed" ]; then pass "the Run was briefed with $briefed earlier canary note(s)"; else fail "the Run was briefed with $briefed earlier canary note(s), want at least $want_briefed"; fi
}

printf 'Ploeg notes canary %s: team copper, exec harness, no model call\n' "$stamp"

path=/api/v1/operator/work-items
response=$(api -X POST -d "{\"requestId\":\"notes-canary-$stamp\",\"team\":\"copper\",\"target\":\"erfbeeld\",\"title\":\"[canary] notes loop $stamp\",\"description\":\"A canary Work Item. The copper exec harness writes one live note, sleeps and stops on purpose, so the worker writes a stop note. It opens no pull request and calls no model.\",\"budgetUsd\":0.01}")
status=${response##*$'\n'}
body=${response%$'\n'*}
if [ "$status" != 201 ] && [ "$status" != 200 ]; then
  fail "admission answered HTTP $status: $body"
  exit 1
fi
item=$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin)["workItem"]["id"])')
pass "admitted Work Item $item"

if ! wait_for_finished_runs 1; then fail "no Run of Work Item $item finished within ${run_wait_seconds}s"; exit 1; fi
first=$(sql "select id from agent_runs where work_item_id = $item and finished_at is not null order by id limit 1")
check_run "First Run" "$first" 0

path=/api/v1/operator/work-items/$item/requeue
response=$(api -X POST -d "{\"commandId\":\"notes-canary-$stamp-requeue\",\"poolUsd\":0.01,\"note\":\"Second canary Run: it must be briefed with the first Run's note.\"}")
status=${response##*$'\n'}
if [ "$status" = 200 ] || [ "$status" = 201 ] || [ "$status" = 202 ]; then
  pass "requeued Work Item $item"
  if wait_for_finished_runs 2; then
    second=$(sql "select id from agent_runs where work_item_id = $item and finished_at is not null order by id desc limit 1")
    check_run "Second Run" "$second" 1
  else
    fail "the second Run did not finish within ${run_wait_seconds}s"
  fi
else
  fail "requeue answered HTTP $status: ${response%$'\n'*}"
fi

path=/api/v1/operator/work-items/$item/cancel
response=$(api -X POST -d "{\"commandId\":\"notes-canary-$stamp-cancel\"}")
note "cleanup: cancel answered HTTP ${response##*$'\n'}; Work Item $item is $(sql "select state from work_items where id = $item")"

printf '\n'
if [ "$failures" -eq 0 ]; then
  printf 'Notes canary passed for Work Item %s\n' "$item"
else
  printf 'Notes canary FAILED %s check(s) for Work Item %s\n' "$failures" "$item"
  exit 1
fi
