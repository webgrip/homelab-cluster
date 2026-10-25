#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel)}"
APP="${ROOT_DIR}/kubernetes/apps/backup/etcd/app"
IMAGE="$(sed -n 's/^ *image: \(harbor.webgrip.dev\/webgrip\/infra-runner:[^ ]*\)$/\1/p' "${APP}/cronjob-drill.yaml" | head -n 1)"
workspace="$(mktemp -d)"
chmod 777 "$workspace"
trap 'docker run --rm -v "${workspace}:/w" --entrypoint sh -u 0 "$IMAGE" -c "rm -rf /w/*" >/dev/null 2>&1; rm -rf "$workspace"' EXIT

docker run --rm -v "${workspace}:/w" --entrypoint bash "$IMAGE" -c '
set -euo pipefail
cd /tmp
age-keygen -o /w/identity 2>/dev/null
age-keygen -o /w/other-identity 2>/dev/null
recipient="$(age-keygen -y /w/identity)"
now="$(date -u +%s)"
build() {
  local name="$1" canary="$2" keys="$3"
  rm -rf /tmp/e; etcd --data-dir /tmp/e --listen-client-urls http://127.0.0.1:2379 --advertise-client-urls http://127.0.0.1:2379 >/tmp/etcd.log 2>&1 &
  local pid=$!
  for _ in $(seq 1 30); do etcdctl endpoint health >/dev/null 2>&1 && break; sleep 1; done
  for k in $keys; do etcdctl put "$k" x >/dev/null; done
  [ -n "$canary" ] && etcdctl put /registry/configmaps/backup/etcd-backup-canary "k8s\x00$canary\x00" >/dev/null
  etcdctl snapshot save /tmp/s.db >/dev/null 2>&1
  kill $pid; wait $pid 2>/dev/null || true
  age -r "$recipient" -o "/w/$name" /tmp/s.db
}
all="/registry/namespaces/kube-system /registry/namespaces/flux-system /registry/namespaces/backup"
stamp() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
build "homelab-$(stamp $((now - 3600))).snap.age" "canary-$((now - 86400))-ab12-end" "$all"
mv /w/homelab-*.snap.age /w/good.snap.age
build "stale-snap" "canary-$((now - 86400))-ab12-end" "$all"; mv /w/stale-snap "/w/homelab-$(stamp $((now - 2 * 86400))).snap.age"
build "canary-old" "canary-$((now - 3 * 86400))-ab12-end" "$all"
build "no-canary" "" "$all"
build "missing-namespace" "canary-$((now - 86400))-ab12-end" "/registry/namespaces/kube-system /registry/namespaces/backup"
chmod 666 /w/*
'
good="homelab-$(date -u -d '-1 hour' +%Y-%m-%dT%H:%M:%SZ).snap.age"

failures=0
expect() {
  local label="$1" want="$2" file="$3" identity="$4" corrupt="${5:-false}" got=pass
  mkdir -p "${workspace}/out-${label}"; chmod 777 "${workspace}/out-${label}"
  local target="/w/${file}"
  if [[ "$file" == good.snap.age ]]; then
    cp "${workspace}/good.snap.age" "${workspace}/${label}-${good}"; target="/w/${label}-${good}"
  elif [[ "$file" != homelab-* ]]; then
    cp "${workspace}/${file}" "${workspace}/${label}-${good}"; target="/w/${label}-${good}"
  fi
  docker run --rm -v "${workspace}:/w" -v "${APP}/verify-etcd-snapshot.sh:/scripts/verify.sh:ro" \
    -e S3_BUCKET=homelab-etcd -e SNAPSHOT_FILE="$target" -e AGE_IDENTITY_FILE="/w/${identity}" \
    -e OUT="/w/out-${label}" -e CORRUPT_ON_PURPOSE="$corrupt" \
    --entrypoint bash "$IMAGE" /scripts/verify.sh >"${workspace}/${label}.log" 2>&1 || got=fail
  local reason
  reason="$(grep -m1 -E '^(FAIL|restore verified|no canary)' "${workspace}/${label}.log" || tail -n1 "${workspace}/${label}.log")"
  if [[ "$got" == "$want" ]]; then
    echo "ok    ${label}: ${got} (${reason})"
  else
    echo "WRONG ${label}: ${got}, wanted ${want}"; cat "${workspace}/${label}.log"; failures=$((failures + 1))
  fi
}

expect good pass good.snap.age identity
expect stale-snapshot fail "$(cd "$workspace" && ls homelab-*.snap.age | head -n 1)" identity
expect corrupt-snapshot fail good.snap.age identity true
expect wrong-identity fail good.snap.age other-identity
expect stale-canary fail canary-old identity
expect missing-namespace fail missing-namespace identity
expect no-canary pass no-canary identity
[[ -f "${workspace}/out-no-canary/no-canary" ]] && echo "ok    no-canary: marker left for the recorder" \
  || { echo "WRONG no-canary: no marker"; failures=$((failures + 1)); }
[[ ! -f "${workspace}/out-good/no-canary" ]] && echo "ok    good: no no-canary marker" \
  || { echo "WRONG good: no-canary marker"; failures=$((failures + 1)); }

mkdir -p "${workspace}/rec/bin"
cat >"${workspace}/rec/bin/kubectl" <<'STUB'
#!/usr/bin/env bash
args=("$@"); [[ "${args[0]}" == "-n" ]] && args=("${args[@]:2}")
case "${args[0]} ${args[1]}" in
  "get configmap") [[ -f "$REC_STATE/${args[2]}" ]] ;;
  "delete configmap") rm -f "$REC_STATE/${args[2]}" ;;
  "create configmap") echo "${args[3]}" >"$REC_STATE/${args[2]}" ;;
  "create -f") cat >"$REC_STATE/verified" ;;
esac
STUB
chmod +x "${workspace}/rec/bin/kubectl"
expect_record() {
  local label="$1" want="$2" out="$3" seeded="$4" got=pass
  local state="${workspace}/rec/state-${label}"; mkdir -p "$state"
  [[ "$seeded" == seeded ]] && echo old >"$state/etcd-backup-canary"
  PATH="${workspace}/rec/bin:${PATH}" REC_STATE="$state" NAMESPACE=backup OUT="${workspace}/${out}" \
    sh "${APP}/record-etcd-drill.sh" >"${workspace}/rec-${label}.log" 2>&1 || got=fail
  local recorded=no; [[ -f "$state/verified" ]] && recorded=yes
  echo "$( [[ "$got" == "${want%%/*}" && "$recorded" == "${want##*/}" ]] && echo ok || { echo WRONG; failures=$((failures + 1)); } )    record-${label}: ${got}, verified recorded: ${recorded} ($(tail -n1 "${workspace}/rec-${label}.log"))"
}
expect_record verified pass/yes out-good seeded
expect_record first-run pass/no out-no-canary fresh
expect_record canary-lost fail/no out-no-canary seeded
expect_record restore-failed fail/no out-wrong-identity seeded

exit "$failures"
