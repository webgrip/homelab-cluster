#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0
bridge=kubernetes/apps/vikunja/mcp-vikunja/app
namespace_policy=kubernetes/apps/vikunja/vikunja/app/networkpolicy.yaml
litellm=kubernetes/apps/ai/litellm/app/litellm-config.configmap.yaml

fresh() {
  rm -rf "${work:?}/$1"
  mkdir -p "$work/$1"
  cp -r "$root/kubernetes" "$work/$1/kubernetes"
  echo "$work/$1"
}

expect() {
  local want=$1 label=$2 dir=$3 rc out verdict
  out=$(python3 "$root/scripts/validate_mcp_gateway_only.py" "$dir" 2>&1)
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

d=$(fresh lan-route)
cat > "$d/$bridge/httproute.yaml" <<'EOF'
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-vikunja
spec:
  parentRefs:
    - name: envoy-internal
      namespace: network
  rules:
    - backendRefs:
        - name: mcp-vikunja
          port: 8000
EOF
expect fail "LAN HTTPRoute to the bridge comes back" "$d"

d=$(fresh namespace-wide-allow)
python3 - "$d/$namespace_policy" <<'EOF'
import sys
path = sys.argv[1]
text = open(path).read()
start = text.index("  podSelector:\n    matchExpressions:")
end = text.index("  policyTypes:", start)
open(path, "w").write(text[:start] + "  podSelector: {}\n" + text[end:])
EOF
expect fail "namespace-wide ingress allow selects the bridge again" "$d"

d=$(fresh extra-peer)
rewrite 's/kubernetes.io\/metadata.name: ai$/kubernetes.io\/metadata.name: observability/' "$d/$bridge/networkpolicy.yaml"
expect fail "bridge policy admits observability instead of LiteLLM" "$d"

d=$(fresh open-rule)
python3 - "$d/$bridge/networkpolicy.yaml" <<'EOF'
import sys
path = sys.argv[1]
text = open(path).read()
open(path, "w").write(text.replace("  ingress:\n    - from:", "  ingress:\n    - {}\n    - from:", 1))
EOF
expect fail "bridge policy gains an allow-all ingress rule" "$d"

d=$(fresh unlabelled-service)
rewrite '/mcp.webgrip.io\/access: litellm-gateway-only/d' "$d/$bridge/service.yaml"
expect fail "label dropped while LiteLLM serves vikunja to the board group" "$d"

d=$(fresh unlabelled-pods)
rewrite '/mcp.webgrip.io\/access: litellm-gateway-only/d' "$d/$bridge/deployment.yaml"
expect fail "pod template loses the label the namespace policy excludes" "$d"

d=$(fresh loadbalancer)
rewrite 's/^spec:$/spec:\n  type: LoadBalancer/' "$d/$bridge/service.yaml"
expect fail "bridge service becomes a LoadBalancer" "$d"

d=$(fresh read-only-group)
rewrite 's/access_groups: \["board"\]/access_groups: ["observability"]/' "$d/$litellm"
rewrite '/mcp.webgrip.io\/access: litellm-gateway-only/d' "$d/$bridge/service.yaml"
expect pass "unlabelled bridge served only to a read-only group" "$d"

d=$(fresh broken-config)
printf 'data: [\n' > "$d/$litellm"
expect error "unparseable LiteLLM config" "$d"

echo "wrong verdicts: $wrong"
[ "$wrong" -eq 0 ]
