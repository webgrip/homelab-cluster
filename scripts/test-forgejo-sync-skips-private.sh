#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
sync_script="${FORGEJO_SYNC_SCRIPT:-$repo_root/scripts/forgejo-sync.sh}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"
cat > "$work/bin/curl" <<'FAKE'
#!/usr/bin/env bash
url="${*: -1}"
case "$url" in
  *"/orgs/webgrip/repos?limit=50&page=1")
    printf '%s' '[{"name":"public-app","private":false,"mirror":false,"fork":false},{"name":"obsidian-vault","private":true,"mirror":false,"fork":false},{"name":"mirrored","private":false,"mirror":true,"fork":false},{"name":"forked","private":false,"mirror":false,"fork":true}]' ;;
  *"/orgs/webgrip/repos?"*) printf '[]' ;;
  *) printf '{"has_pull_requests":true}' ;;
esac
FAKE
chmod +x "$work/bin/curl"
output="$(FORGEJO_TOKEN=test-token PATH="$work/bin:$PATH" bash "$sync_script" --all --only prs 2>&1)"
header="$(printf '%s\n' "$output" | grep '^forgejo-sync:')"
failures=0
check() {
  if printf '%s\n' "$header" | grep -qw -- "$2"; then found=yes; else found=no; fi
  if [ "$found" != "$1" ]; then
    echo "FAIL: expected $2 managed=$1, header was: $header"
    failures=$((failures + 1))
  fi
}
check yes public-app
check no obsidian-vault
check no mirrored
check no forked
if [ "$failures" -gt 0 ]; then
  exit 1
fi
echo "PASS: forgejo-sync --all manages public-app only; private, mirrored and forked repos are left alone"
