#!/usr/bin/env bash
set -euo pipefail

root="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
validator="${root}/scripts/validate-repo-config-model.sh"
model="${root}/kubernetes/apps/repo-config/repo-config/model"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
failures=0

run_case() {
  local expect="$1" name="$2" mutation="$3"
  local dir="${work}/${name}"
  cp -r "$model" "$dir"
  (cd "$dir" && eval "$mutation")
  if REPO_CONFIG_MODEL_DIR="$dir" "$validator" "$root" >"${dir}.log" 2>&1; then got=pass; else got=fail; fi
  if [ "$got" = "$expect" ]; then
    echo "ok   ${name}: ${got}"
  else
    echo "FAIL ${name}: expected ${expect}, got ${got}"
    sed 's/^/     /' "${dir}.log"
    failures=$((failures + 1))
  fi
}

run_case pass unchanged-model 'true'
run_case fail unknown-setting-key "sed -i 's/^      has_releases: false$/      has_release: false/' repos.yaml"
run_case fail wrong-setting-type "sed -i 's/^      default_merge_style: merge$/      default_merge_style: yes-please/' profiles.yaml"
run_case fail unknown-profile "sed -i '0,/profile: baseline/s//profile: product/' repos.yaml"
run_case fail homelab-cluster-missing "python3 -c 'import re,pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(re.sub(r\"  homelab-cluster:\n    profile: homelab\n\", \"\", p.read_text()))'"
run_case fail homelab-cluster-off-homelab-profile "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  homelab-cluster:\n    profile: homelab\n\", \"  homelab-cluster:\n    profile: baseline\n\"))'"
run_case fail homelab-push-without-owner "python3 -c 'import pathlib; p=pathlib.Path(\"profiles.yaml\"); p.write_text(p.read_text().replace(\"        push:\n          - ryangr0\n\", \"        push:\n          - webgrip-ci\n\"))'"
run_case fail homelab-cluster-branch-override "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  homelab-cluster:\n    profile: homelab\n\", \"  homelab-cluster:\n    profile: homelab\n    branches:\n      main:\n        push: []\n        merge: []\n        status_checks: []\n\"))'"
run_case fail branch-rule-unknown-key "sed -i '0,/^        status_checks: \\[\\]$/s//        status_checks: []\\n        required_approvals: 1/' repos.yaml"
run_case fail status-check-unescaped-glob-bracket "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"\\\\\\\\[Workflow\\\\\\\\]\", \"[Workflow]\", 1))'"
run_case fail homelab-main-drops-the-pair-gate "sed -i '/^          - \"e2e \/ Lint & static validation (pull_request)\"$/d' profiles.yaml"
run_case fail homelab-main-requires-nothing "python3 -c 'import re,pathlib; p=pathlib.Path(\"profiles.yaml\"); p.write_text(re.sub(r\"(          - renovate\\n        status_checks:)\\n(          - .*\\n)+\", r\"\\1 []\\n\", p.read_text(), count=1))'"
run_case fail baseline-missing-field "sed -i '/^      allow_fast_forward_only_merge: true$/d' profiles.yaml"

if [ "$failures" -ne 0 ]; then
  echo "test-validate-repo-config-model: ${failures} case(s) wrong"
  exit 1
fi
echo "test-validate-repo-config-model: all cases behave"
