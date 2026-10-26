#!/bin/sh
set -u

root="${PROBE_ROOT:-}"
connect_timeout="${PROBE_CONNECT_TIMEOUT:-5}"
metadata_urls="${PROBE_METADATA_URLS:-http://169.254.169.254/latest/meta-data/ http://metadata.google.internal/computeMetadata/v1/ http://100.100.100.200/latest/meta-data/}"
kubernetes_api_urls="${PROBE_KUBERNETES_API_URLS:-https://kubernetes.default.svc/version}"
blocked_urls="${PROBE_BLOCKED_URLS:-https://example.com/ https://1.1.1.1/}"
reachable_urls="${PROBE_REACHABLE_URLS:-}"
host_paths="/host /hostfs /rootfs /var/lib/kubelet /var/lib/containerd /etc/kubernetes /var/log/pods /certs /var/run/docker.sock /run/docker.sock /run/containerd/containerd.sock /var/run/crio/crio.sock /run/crio/crio.sock"
token_paths="/var/run/secrets/kubernetes.io/serviceaccount/token /run/secrets/kubernetes.io/serviceaccount/token"
failures=0

pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

status_field() { awk -v key="$1:" '$1 == key { print $2; exit }' "$root/proc/self/status"; }

connected() {
  seconds=$(curl -sk --noproxy '*' -o /dev/null --connect-timeout "$connect_timeout" --max-time $((connect_timeout * 2)) -w '%{time_connect}' "$1" 2>/dev/null)
  case "${seconds:-0}" in
    0 | 0.0 | 0.000 | 0.000000) return 1 ;;
    *) return 0 ;;
  esac
}

expect_unreachable() {
  for url in $2; do
    if connected "$url"; then fail "$1 reachable $url"; else pass "$1 unreachable $url"; fi
  done
}

check_privilege() {
  uid=$(status_field Uid)
  case "$uid" in
    "" ) fail "privilege no Uid in $root/proc/self/status" ;;
    0 ) fail "privilege runs as uid 0" ;;
    * ) pass "privilege uid $uid" ;;
  esac
  for set in CapEff CapPrm CapBnd CapAmb; do
    value=$(status_field "$set")
    case "$value" in
      *[!0]* | "") fail "privilege $set=${value:-missing}" ;;
      *) pass "privilege $set empty" ;;
    esac
  done
  [ "$(status_field NoNewPrivs)" = 1 ] && pass "privilege no_new_privs set" || fail "privilege no_new_privs not set"
  [ "$(status_field Seccomp)" = 2 ] && pass "privilege seccomp filter on" || fail "privilege seccomp mode $(status_field Seccomp)"
}

check_service_account_token() {
  for path in $token_paths; do
    if [ -e "$root$path" ]; then fail "kubernetes-token present at $path"; else pass "kubernetes-token absent at $path"; fi
  done
}

check_host_paths() {
  mounted=$(awk '{ print $5 }' "$root/proc/self/mountinfo" 2>/dev/null)
  for path in $host_paths; do
    if [ -e "$root$path" ]; then
      fail "host-mount $path exists"
    elif printf '%s\n' "$mounted" | grep -qx "$path"; then
      fail "host-mount $path is a mount point"
    else
      pass "host-mount $path absent"
    fi
  done
  if [ -n "${DOCKER_HOST:-}" ]; then fail "host-mount DOCKER_HOST is set"; else pass "host-mount DOCKER_HOST unset"; fi
  printf '%s\n' "$mounted" | sed '/^$/d; s/^/INFO mount /'
}

check_kubernetes_api() {
  urls="$kubernetes_api_urls"
  if [ -n "${KUBERNETES_SERVICE_HOST:-}" ]; then
    urls="$urls https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT:-443}/version"
  fi
  expect_unreachable kubernetes-api "$urls"
}

check_reachable() {
  for url in $reachable_urls; do
    if connected "$url"; then pass "allowed reachable $url"; else fail "allowed unreachable $url"; fi
  done
}

echo "worker-boundary-probe kernel=$(uname -r) uid=$(id -u)"
check_privilege
check_service_account_token
check_host_paths
expect_unreachable metadata "$metadata_urls"
check_kubernetes_api
expect_unreachable egress "$blocked_urls"
check_reachable

if [ "$failures" -ne 0 ]; then
  echo "worker-boundary-probe FAILED ($failures)"
  exit 1
fi
echo "worker-boundary-probe passed"
