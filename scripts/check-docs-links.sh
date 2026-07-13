#!/usr/bin/env bash
# Docs consistency gate for docs/techdocs: every mkdocs nav entry and redirect target must
# exist, every page must be reachable (nav or whitelisted), and every relative .md link must
# resolve. Redirect-map SOURCES are intentionally nonexistent old paths — only targets checked.
set -uo pipefail

repo_root="${1:-$(pwd)}"
techdocs="${repo_root}/docs/techdocs"
cd "${techdocs}" || { echo "missing ${techdocs}" >&2; exit 1; }

# Pages allowed to exist outside the nav (linked directly, not in the sidebar).
nav_whitelist='adr/adr-0000-template.md'

# One nav slice, reused everywhere. Load-bearing: `sed ... | grep -q` under pipefail is a
# SIGPIPE race — grep -q exits on first match, sed gets SIGPIPE (141), and the pipeline
# "fails" despite the match. Bit CI 2026-07-13 (14 false NOT-IN-NAV under concurrent-run
# load). Herestrings avoid the pipeline entirely.
nav_slice="$(sed -n '/^nav:/,$p' mkdocs.yml)"

fail=0
say() { echo "  $1"; fail=1; }

echo "check-docs-links: redirect targets"
grep -E "^\s+'[^']+': '[^']+'" mkdocs.yml | sed -E "s/^[^:]+: '([^']+)'.*/\1/" | sort -u |
while read -r f; do [ -f "docs/$f" ] || say "MISSING redirect target: $f"; done

echo "check-docs-links: nav entries"
grep -oE '[A-Za-z0-9./_-]+\.md' <<<"${nav_slice}" | sort -u |
while read -r f; do [ -f "docs/$f" ] || say "MISSING nav entry: $f"; done

echo "check-docs-links: orphan pages (on disk, not in nav)"
find docs -name '*.md' | sed 's|^docs/||' | sort | while read -r f; do
  case " ${nav_whitelist} " in (*" $f "*) continue ;; esac
  grep -q "$f" <<<"${nav_slice}" || say "NOT IN NAV: $f"
done

echo "check-docs-links: relative links"
find docs -name '*.md' | while read -r f; do
  case " ${nav_whitelist} " in (*" ${f#docs/} "*) continue ;; esac
  dir=$(dirname "$f")
  grep -oE '\]\([^)#[:space:]]+\.md' "$f" | sed 's/](//' | while read -r target; do
    case "$target" in (http*|/*) continue ;; esac
    [ -f "$dir/$target" ] || say "DEAD link: $f -> $target"
  done
done

# Sub-shell pipelines can't propagate fail=1; re-run cheaply and count.
errors=$(
  {
    grep -E "^\s+'[^']+': '[^']+'" mkdocs.yml | sed -E "s/^[^:]+: '([^']+)'.*/\1/" | sort -u |
      while read -r f; do [ -f "docs/$f" ] || echo x; done
    grep -oE '[A-Za-z0-9./_-]+\.md' <<<"${nav_slice}" | sort -u |
      while read -r f; do [ -f "docs/$f" ] || echo x; done
    find docs -name '*.md' | sed 's|^docs/||' | while read -r f; do
      case " ${nav_whitelist} " in (*" $f "*) continue ;; esac
      grep -q "$f" <<<"${nav_slice}" || echo x
    done
    find docs -name '*.md' | while read -r f; do
      case " ${nav_whitelist} " in (*" ${f#docs/} "*) continue ;; esac
      dir=$(dirname "$f")
      grep -oE '\]\([^)#[:space:]]+\.md' "$f" | sed 's/](//' | while read -r t; do
        case "$t" in (http*|/*) continue ;; esac
        [ -f "$dir/$t" ] || echo x
      done
    done
  } | wc -l
)

if [ "${errors}" -gt 0 ]; then
  echo "check-docs-links: FAILED (${errors} problem(s))" >&2
  exit 1
fi
echo "check-docs-links: OK"
