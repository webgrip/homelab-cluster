#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
python=${PYTHON:-python3}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0
grants=kubernetes/apps/security/openbao/bootstrap/eso-grants.txt
stores=kubernetes/apps/security/external-secrets/tenants/stores.generated.yaml
freshrss_secret=kubernetes/apps/freshrss/freshrss/app/freshrss-secrets.externalsecret.yaml
harbor_push=kubernetes/apps/harbor/harbor/app/harbor-admin.pushsecret.yaml

fresh() {
  rm -rf "${work:?}/$1"
  mkdir -p "$work/$1"
  cp -r "$root/kubernetes" "$root/scripts" "$work/$1/"
  echo "$work/$1"
}

mutate() {
  local file=$1 script=$2 before
  before=$(cat "$file")
  sed -i "$script" "$file"
  if [ "$(cat "$file")" = "$before" ]; then
    echo "WRONG mutation '$script' changed nothing in ${file#"$work"/}"
    wrong=$((wrong + 1))
  fi
}

expect() {
  local want=$1 label=$2 dir=$3 rc out verdict
  out=$("$python" "$dir/scripts/eso_grants.py" "$dir" 2>&1)
  rc=$?
  case "$want:$rc" in
    pass:0 | fail:1 | error:2) verdict=ok ;;
    *) verdict=WRONG; wrong=$((wrong + 1)) ;;
  esac
  printf '%-5s expect=%-5s rc=%s  %s\n' "$verdict" "$want" "$rc" "$label"
  printf '%s\n' "$out" | tail -n 3 | sed 's/^/        /'
}

d=$(fresh committed)
expect pass "committed tree" "$d"

d=$(fresh foreign-path)
mutate "$d/$freshrss_secret" '0,/key: freshrss\/app/s//key: litellm/'
expect fail "freshrss ExternalSecret reads the LiteLLM master key path" "$d"

d=$(fresh regenerated)
mutate "$d/$freshrss_secret" '0,/key: freshrss\/app/s//key: litellm/'
"$python" "$d/scripts/eso_grants.py" "$d" --write >/dev/null
expect pass "same change after --write records the grant" "$d"
if ! grep -qx 'freshrss read litellm' "$d/$grants"; then
  echo "WRONG --write did not add 'freshrss read litellm' to the grants file"
  wrong=$((wrong + 1))
fi

d=$(fresh unused-grant)
echo 'searxng read litellm' >>"$d/$grants"
sort -o "$d/$grants" "$d/$grants"
"$python" - "$d" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
import eso_grants
(root / eso_grants.STORES_FILE).write_text(eso_grants.render_stores(eso_grants.committed_grants(root)))
PY
expect fail "grant nothing in the namespace uses" "$d"

d=$(fresh moved-grant)
mutate "$d/$grants" 's/^freshrss read freshrss\/app$/ai read freshrss\/app/'
expect fail "grant moved to another namespace" "$d"

d=$(fresh stale-stores)
mutate "$d/$stores" '0,/role: eso-read-freshrss/s//role: eso-read-ai/'
expect fail "generated SecretStore authenticates as another namespace's role" "$d"

d=$(fresh push-outside)
mutate "$d/$harbor_push" '0,/remoteKey: harbor\/admin/s//remoteKey: forgejo\/admin/'
expect fail "harbor PushSecret writes another namespace's path" "$d"

d=$(fresh cluster-store)
mutate "$d/$freshrss_secret" '0,/kind: SecretStore, name: openbao}/s//kind: ClusterSecretStore, name: openbao}/'
expect fail "ExternalSecret names the retired ClusterSecretStore" "$d"

d=$(fresh find)
cat >>"$d/$freshrss_secret" <<'YAML'
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: everything
spec:
  secretStoreRef: {kind: SecretStore, name: openbao}
  target: {name: everything}
  dataFrom:
    - find: {path: ".*"}
YAML
expect error "dataFrom.find cannot be granted path by path" "$d"

d=$(fresh substituted)
mutate "$d/$freshrss_secret" '0,/key: freshrss\/app/s//key: "freshrss\/${APP_NAME}"/'
expect error "path built from a Flux substitution" "$d"

d=$(fresh malformed)
echo 'freshrss write freshrss/app' >>"$d/$grants"
expect error "grants file line with an unknown access" "$d"

echo "wrong verdicts: $wrong"
[ "$wrong" -eq 0 ]
