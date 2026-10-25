#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0
rules=kubernetes/apps/observability/victoria-metrics/app/rules
dashboards=kubernetes/apps/observability/grafana/app/dashboards
forgejo_ci_rule=$rules/prometheusrule-platform-forgejo-ci.yaml

fresh() {
  rm -rf "${work:?}/$1"
  mkdir -p "$work/$1"
  cp -r "$root/kubernetes" "$work/$1/kubernetes"
  echo "$work/$1"
}

expect() {
  local want=$1 label=$2 dir=$3 rc out verdict
  out=$(python3 "$root/scripts/validate_alert_annotations.py" "$dir" 2>&1)
  rc=$?
  case "$want:$rc" in
    pass:0 | fail:1) verdict=ok ;;
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

d=$(fresh retired-uid)
rewrite 's|/d/forgejo-ci/forgejo-ci"|/d/infra-forgejo-ci"|' "$d/$forgejo_ci_rule"
expect fail "alert links a retired dashboard uid" "$d"
rewrite 's|/d/infra-forgejo-ci"|/d/forgejo-ci/forgejo-ci"|' "$d/$forgejo_ci_rule"
expect pass "same tree after the link is re-pointed" "$d"

d=$(fresh slug-as-uid)
rewrite 's|/d/talos-node-health"|/d/talos-nodes/talos-nodes"|' "$d/$rules/prometheusrule-platform-nodes.yaml"
expect fail "alert links the file name instead of the uid" "$d"

d=$(fresh deleted-dashboard)
rm "$d/$dashboards/infra-harbor.yaml"
expect fail "dashboard deleted while an alert still links it" "$d"

d=$(fresh generated-target)
rewrite 's|/d/forgejo-ci/forgejo-ci"|/d/glide-runs"|' "$d/$forgejo_ci_rule"
expect pass "alert links a uid defined only in a generated file" "$d"

d=$(fresh other-namespace-target)
rewrite 's|/d/forgejo-ci/forgejo-ci"|/d/litellm-reliability"|' "$d/$forgejo_ci_rule"
expect pass "alert links a dashboard that lives outside observability" "$d"

d=$(fresh templated-uid)
rewrite 's|/d/forgejo-ci/forgejo-ci"|/d/{{ $labels.dashboard_uid }}"|' "$d/$forgejo_ci_rule"
expect pass "templated uid is skipped" "$d"

d=$(fresh broken-dashboard-json)
rewrite 's|"uid": "infra-harbor",|"uid": "infra-harbor",,|' "$d/$dashboards/infra-harbor.yaml"
expect fail "dashboard json no longer parses" "$d"

echo "wrong verdicts: $wrong"
[ "$wrong" -eq 0 ]
