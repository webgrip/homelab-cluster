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
[ -n "${CURL_LOG:-}" ] && echo "$url" >>"$CURL_LOG"
[ -n "${CURL_ARGS_LOG:-}" ] && echo "$*" >>"$CURL_ARGS_LOG"
case "$*" in
  *"-X POST "*"/push_mirrors "*) printf '{}'; exit 0 ;;
  *"/push_mirrors") printf '[]'; exit 0 ;;
  *"https://api.github.com/user") printf '{"login":"mirror-bot"}'; exit 0 ;;
esac
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
for retired in protect settings protect,prs; do
  : >"$work/curl.log"
  if FORGEJO_TOKEN=test-token CURL_LOG="$work/curl.log" PATH="$work/bin:$PATH" bash "$sync_script" --all --only "$retired" --apply >/dev/null 2>&1; then
    echo "FAIL: --only $retired must refuse, it exited 0"
    failures=$((failures + 1))
  fi
  if [ -s "$work/curl.log" ]; then
    echo "FAIL: --only $retired called the Forgejo API before refusing"
    failures=$((failures + 1))
  fi
done
mirror_posts() {
  : >"$work/args.log"
  FORGEJO_TOKEN=test-token GH_MIRROR_TOKEN=test-mirror-token CURL_ARGS_LOG="$work/args.log" PATH="$work/bin:$PATH" \
    bash "$sync_script" --repo "$1" --only mirror --apply >/dev/null 2>&1
  grep -c -- "-X POST .*/repos/webgrip/$1/push_mirrors " "$work/args.log" || true
}
if [ "$(mirror_posts public-app)" != "1" ]; then
  echo "FAIL: --only mirror --apply must add a push mirror for public-app"
  failures=$((failures + 1))
fi
if [ "$(mirror_posts unfold)" != "0" ]; then
  echo "FAIL: --only mirror --apply added a push mirror for unfold, whose source of truth moves to GitHub"
  failures=$((failures + 1))
fi
if [ "$failures" -gt 0 ]; then
  exit 1
fi
echo "PASS: forgejo-sync --all manages public-app only; private, mirrored and forked repos are left alone; protect and settings refuse; unfold gets no push mirror"
