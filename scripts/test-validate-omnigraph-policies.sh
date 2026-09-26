#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
bundle=$root/kubernetes/apps/ai/omnigraph/app/bundle
validator=(python3 "$root/scripts/validate_omnigraph_policies.py")
cross_client=(--cross-client-actor act-admin --cross-client-actor act-ryan --cross-client-actor act-ingest)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0

fresh() {
  rm -rf "${work:?}/$1"
  cp -r "$bundle" "$work/$1"
  echo "$work/$1"
}

with_two_clients() {
  local dir=$1 keep_explorer=${2:-}
  python3 - "$dir" "$keep_explorer" <<'PY'
import sys
from pathlib import Path
import yaml
bundle = Path(sys.argv[1])
keep_explorer = sys.argv[2]
cluster = yaml.safe_load((bundle / "cluster.yaml").read_text())
template = (bundle / "webgrip.policy.yaml").read_text()
for client in ("client-a", "client-b"):
    cluster["graphs"][client] = {"schema": "meetings.pg", "queries": ["meetings.gq"]}
    cluster["policies"][f"{client}-access"] = {"file": f"{client}.policy.yaml", "applies_to": [client]}
    policy = yaml.safe_load(template)
    policy["groups"].pop("explorers", None)
    policy["rules"] = [rule for rule in policy["rules"] if rule["allow"]["actors"]["group"] != "explorers"]
    if keep_explorer == "keep-explorer":
        policy["groups"]["explorers"] = ["act-explorer"]
        policy["rules"].append({"id": "explorers-read-and-export", "allow": {"actors": {"group": "explorers"}, "actions": ["read", "export"], "branch_scope": "any"}})
    policy["groups"]["client"] = [f"act-{client}"]
    policy["rules"].append({"id": "client-reads-main", "allow": {"actors": {"group": "client"}, "actions": ["read"], "branch_scope": "protected"}})
    (bundle / f"{client}.policy.yaml").write_text(yaml.safe_dump(policy, sort_keys=False))
(bundle / "cluster.yaml").write_text(yaml.safe_dump(cluster, sort_keys=False))
PY
}

expect() {
  local want=$1 label=$2 dir=$3 rc out verdict
  shift 3
  out=$("${validator[@]}" "$dir/cluster.yaml" "$@" 2>&1)
  rc=$?
  case "$want:$rc" in
    pass:0 | fail:1 | error:2) verdict=ok ;;
    *) verdict=WRONG; wrong=$((wrong + 1)) ;;
  esac
  printf '%-5s expect=%-5s rc=%s  %s\n' "$verdict" "$want" "$rc" "$label"
  printf '%s\n' "$out" | sed 's/^/        /'
}

d=$(fresh deployed)
expect pass "deployed bundle" "$d" "${cross_client[@]}"

d=$(fresh unbound)
sed -i 's/^policies:/  scratch:\n    schema: memory.pg\npolicies:/' "$d/cluster.yaml"
expect fail "graph declared without a policy" "$d" "${cross_client[@]}"

d=$(fresh clients)
with_two_clients "$d"
expect pass "two isolated client graphs" "$d" "${cross_client[@]}"

d=$(fresh spanning)
with_two_clients "$d"
sed -i 's/^  - act-client-b$/  - act-client-b\n  - act-client-a/' "$d/client-b.policy.yaml"
expect fail "client actor granted on both client graphs" "$d" "${cross_client[@]}"

d=$(fresh explorer-spanning)
with_two_clients "$d" keep-explorer
expect fail "explorer copied onto both client graphs" "$d" "${cross_client[@]}"

d=$(fresh unprotected)
with_two_clients "$d"
sed -i '/^protected_branches:/,/^- main$/d' "$d/client-a.policy.yaml"
expect fail "client graph without protected main" "$d" "${cross_client[@]}"

d=$(fresh no-allow-list)
with_two_clients "$d"
expect fail "shared operators not allow-listed" "$d"

d=$(fresh missing-file)
rm "$d/brain.policy.yaml"
expect fail "policy bundle names a missing file" "$d" "${cross_client[@]}"

d=$(fresh broken)
printf 'graphs: [\n' > "$d/cluster.yaml"
expect error "unparseable cluster.yaml" "$d" "${cross_client[@]}"

echo "wrong verdicts: $wrong"
[ "$wrong" -eq 0 ]
