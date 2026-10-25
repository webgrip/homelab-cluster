#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
configmap="${HARBOR_CONFIGMAP:-$repo_root/kubernetes/apps/harbor/harbor/app/harbor-proxy-config.configmap.yaml}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/state"

python3 - "$configmap" "$work/lib.sh" <<'PY'
import re
import sys
import yaml

script = yaml.safe_load(open(sys.argv[1]))['data']['configure.sh'].replace('$$', '$')
wanted = ['log', 'hc', 'set_immutable_rules_disabled', 'retire_repository']
parts = []
for name in wanted:
    match = re.search(rf'^{name}\(\) {{[^\n]*}}$', script, re.M) or re.search(rf'^{name}\(\) {{.*?^}}$', script, re.S | re.M)
    if not match:
        sys.exit(f'function {name} not found in configure.sh')
    parts.append(match.group(0))
open(sys.argv[2], 'w').write('\n'.join(parts) + '\n')
PY

cat > "$work/bin/curl" <<'FAKE'
#!/bin/sh
method=GET
body=""
url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -X) method="$2"; shift 2 ;;
    -u|-H) shift 2 ;;
    -d) body="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
path="${url#http://harbor.test/api/v2.0}"
state="$FAKE_STATE"
echo "$method $path" >> "$state/calls"
case "$method $path" in
  "GET /projects/webgrip/repositories/semantic-release-rust")
    [ -f "$state/repo" ] && { echo '{}'; exit 0; } || exit 22 ;;
  "GET /projects/webgrip")
    echo '{"project_id":7}' ;;
  "GET /projects/7/immutabletagrules")
    cat "$state/rules.json" ;;
  "PUT /projects/7/immutabletagrules/"*)
    id="${path##*/}"
    jq --argjson rule "$body" --argjson id "$id" 'map(if .id == $id then $rule else . end)' "$state/rules.json" > "$state/rules.new"
    mv "$state/rules.new" "$state/rules.json" ;;
  "DELETE /projects/webgrip/repositories/semantic-release-rust")
    [ -f "$state/refuse-delete" ] && exit 22
    jq -e 'any(.[]; .disabled == false)' "$state/rules.json" >/dev/null && exit 22
    rm -f "$state/repo" ;;
  *)
    exit 22 ;;
esac
FAKE
chmod +x "$work/bin/curl"

run_case() {
  rm -rf "$work/state" && mkdir -p "$work/state"
  echo '[{"id":3,"disabled":false,"tag_selectors":[{"pattern":"**.**.**"}]}]' > "$work/state/rules.json"
  [ "$1" = present ] && touch "$work/state/repo"
  [ "$2" = refuse ] && touch "$work/state/refuse-delete"
  PATH="$work/bin:$PATH" FAKE_STATE="$work/state" HARBOR=http://harbor.test/api/v2.0 AUTH=x sh -c "
    HEALTH_FAILED=0
    . '$work/lib.sh'
    retire_repository webgrip semantic-release-rust 2>/dev/null
    echo \$HEALTH_FAILED > '$work/state/health'
  "
}

fail() { echo "FAIL: $*" >&2; exit 1; }
rule_enabled() { jq -e '.[0].disabled == false' "$work/state/rules.json" >/dev/null; }

run_case present allow
[ ! -f "$work/state/repo" ] || fail "a present retired repository behind an immutable rule was not deleted"
rule_enabled || fail "the immutable rule stayed disabled after the delete"
[ "$(cat "$work/state/health")" = 0 ] || fail "a successful retirement marked the run failed"

run_case absent allow
grep -q '^DELETE' "$work/state/calls" && fail "an absent repository was deleted again"
[ "$(cat "$work/state/health")" = 0 ] || fail "an absent repository marked the run failed"

run_case present refuse
[ -f "$work/state/repo" ] || fail "the fake refused the delete but the repository is gone"
rule_enabled || fail "the immutable rule stayed disabled after a failed delete"
[ "$(cat "$work/state/health")" = 1 ] || fail "a failed retirement did not mark the run failed"

python3 - "$configmap" "$work/loop.sh" "$work/listing" <<'PY'
import re
import sys
import yaml

data = yaml.safe_load(open(sys.argv[1]))['data']
script = data['configure.sh'].replace('$$', '$')
loop = re.search(r'^while read .*?^done < /scripts/retired-repositories$', script, re.S | re.M)
if not loop:
    sys.exit('the retired-repositories loop is missing from configure.sh')
open(sys.argv[2], 'w').write(loop.group(0).replace('/scripts/retired-repositories', sys.argv[3]) + '\n')
open(sys.argv[3], 'w').write(data['retired-repositories'].rstrip('\n') + '\nwebgrip last-entry-without-newline')
PY
sh -c "
  retire_repository() { echo \"\$1/\$2\" >> '$work/retired'; }
  . '$work/loop.sh'
"
grep -qx 'webgrip/semantic-release-rust' "$work/retired" || fail "the listed repository was not handed to retire_repository"
grep -qx 'webgrip/last-entry-without-newline' "$work/retired" || fail "the last entry of a list without a trailing newline is never read"

echo "ok: retired repositories are deleted behind immutable rules, the rules come back, absent ones are left alone, failures fail the run, every listed entry is read"
