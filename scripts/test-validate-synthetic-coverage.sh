#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0
blackbox=kubernetes/apps/observability/blackbox-exporter/app

fresh() {
  rm -rf "${work:?}/$1"
  mkdir -p "$work/$1"
  cp -r "$root/kubernetes" "$work/$1/kubernetes"
  echo "$work/$1"
}

expect() {
  local want=$1 label=$2 dir=$3 rc out verdict
  out=$(python3 "$root/scripts/validate_synthetic_coverage.py" "$dir" 2>&1)
  rc=$?
  case "$want:$rc" in
    pass:0 | fail:1 | error:2) verdict=ok ;;
    *) verdict=WRONG; wrong=$((wrong + 1)) ;;
  esac
  printf '%-5s expect=%-5s rc=%s  %s\n' "$verdict" "$want" "$rc" "$label"
  printf '%s\n' "$out" | tail -3 | sed 's/^/        /'
}

rewrite() {
  sed -i.orig "$1" "$2" && rm -f "$2.orig"
}

d=$(fresh current)
expect pass "current tree" "$d"

d=$(fresh k6-claim)
rewrite 's/synthetic-check: blackbox-omnigraph$/synthetic-check: k6-ingress-canary/' "$d/kubernetes/apps/ai/omnigraph/app/httproute.yaml"
expect fail "route claims the suspended k6 canary" "$d"

d=$(fresh label-true)
rewrite 's/synthetic-check: blackbox-omnigraph$/synthetic-check: "true"/' "$d/kubernetes/apps/ai/omnigraph/app/httproute.yaml"
expect fail "route claims a bare \"true\"" "$d"

d=$(fresh unlisted-probe)
rewrite '/probe-omnigraph.yaml/d' "$d/$blackbox/kustomization.yaml"
expect fail "probe file dropped from the kustomization" "$d"

d=$(fresh missing-module)
rewrite 's/module: http_omnigraph_gateway/module: http_omnigraph_gateway_renamed/' "$d/$blackbox/probe-omnigraph.yaml"
expect fail "probe names an undefined module" "$d"

d=$(fresh deleted-probe)
rm "$d/$blackbox/probe-omnigraph.yaml"
expect fail "probe deleted while the route still claims it" "$d"

d=$(fresh broken-yaml)
printf 'resources: [\n' > "$d/$blackbox/kustomization.yaml"
expect error "unparseable blackbox kustomization" "$d"

echo "wrong verdicts: $wrong"
[ "$wrong" -eq 0 ]
