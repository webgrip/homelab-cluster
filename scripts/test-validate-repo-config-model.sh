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
run_case fail wrong-setting-type "sed -i 's/^        default_merge_style: merge$/        default_merge_style: yes-please/' profiles.yaml"
run_case fail unknown-profile "sed -i '0,/profile: baseline/s//profile: product/' repos.yaml"
run_case fail homelab-cluster-missing "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  homelab-cluster:\n    forge: forgejo\n    profile: protected-core\n\", \"\"))'"
run_case fail homelab-cluster-off-core-profile "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  homelab-cluster:\n    forge: forgejo\n    profile: protected-core\n\", \"  homelab-cluster:\n    forge: forgejo\n    profile: protected\n\"))'"
run_case fail core-merge-without-owner "python3 -c 'import pathlib; p=pathlib.Path(\"profiles.yaml\"); s=p.read_text(); i=s.index(\"  protected-core:\"); p.write_text(s[:i] + s[i:].replace(\"          merge:\n            - ryangr0\n\", \"          merge:\n\", 1))'"
run_case fail homelab-cluster-branch-override "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  homelab-cluster:\"); p.write_text(s[:i] + s[i:].replace(\"      main:\n        status_checks:\n\", \"      main:\n        merge: []\n        status_checks:\n\", 1))'"
run_case fail branch-rule-unknown-key "sed -i '0,/^        status_checks: \\[\\]$/s//        status_checks: []\\n        required_reviews: 1/' repos.yaml"
run_case fail status-check-unescaped-glob-bracket "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"\\\\\\\\[Workflow\\\\\\\\]\", \"[Workflow]\", 1))'"
run_case fail homelab-main-drops-the-pair-gate "sed -i '/^          - \"e2e \/ Lint & static validation (pull_request)\"$/d' repos.yaml"
run_case fail homelab-main-requires-nothing "python3 -c 'import re,pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  homelab-cluster:\"); p.write_text(s[:i] + re.sub(r\"        status_checks:\\n(          - .*\\n)+\", \"        status_checks: []\\n\", s[i:], count=1))'"
run_case fail baseline-missing-field "sed -i '/^        allow_fast_forward_only_merge: true$/d' profiles.yaml"
run_case fail repo-without-forge "sed -i '0,/^    forge: forgejo$/{/^    forge: forgejo$/d}' repos.yaml"
run_case fail forgejo-name-claims-github "sed -i '0,/^    forge: forgejo$/s//    forge: github/' repos.yaml"
run_case fail github-key-claims-forgejo "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  ploeg-hq/ploeg:\n    forge: github\n\", \"  ploeg-hq/ploeg:\n    forge: forgejo\n\"))'"
run_case fail github-owner-without-credentials "sed -i 's|^  webgrip/twitch_exporter:$|  someone-else/twitch_exporter:|' repos.yaml"
run_case fail github-unknown-setting-key "sed -i 's/^      default_branch: development$/      default_branch: development\n      has_downloads: true/' repos.yaml"
run_case fail github-setting-outside-enum "sed -i 's/^        squash_merge_commit_title: COMMIT_OR_PR_TITLE$/        squash_merge_commit_title: TITLE/' profiles.yaml"
run_case fail github-active-repo-without-default-branch "sed -i 's/^      default_branch: development$/      has_wiki: true/' repos.yaml"
run_case fail github-profile-sets-default-branch "sed -i 's/^        visibility: public$/        visibility: public\n        default_branch: main/' profiles.yaml"
run_case fail baseline-without-github-block "python3 -c 'import re,pathlib; p=pathlib.Path(\"profiles.yaml\"); p.write_text(re.sub(r\"    github:\\n(      .*\\n|        .*\\n)+\", \"\", p.read_text()))'"
run_case fail github-repo-on-profile-without-github "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  webgrip/twitch_exporter:\n    forge: github\n    profile: baseline\n\", \"  webgrip/twitch_exporter:\n    forge: github\n    profile: protected\n\"))'"
run_case fail github-archived-repo-keeps-rulesets "sed -i 's/^      default_branch: development$/      default_branch: development\n      archived: true/' repos.yaml"
run_case fail github-release-consumers-not-json "sed -i 's/^      \\[{\"forge\"/      [{forge/' repos.yaml"
run_case fail github-ruleset-missing-field "sed -i '/^        update: true$/d' repos.yaml"
run_case fail github-status-check-without-integration "sed -i '0,/^            integration_id: 15368$/{/^            integration_id: 15368$/d}' repos.yaml"
run_case fail github-ruleset-id-not-a-number "sed -i 's/^        id: 24445407$/        id: release-tags/' repos.yaml"
run_case fail github-mirror-of-unknown-repo "sed -i 's/^    mirror_of: ledgerflow$/    mirror_of: ledger-flow/' repos.yaml"
run_case fail github-mirror-of-github-repo "sed -i 's|^    mirror_of: ledgerflow$|    mirror_of: ploeg-hq/ploeg|' repos.yaml"
run_case fail github-mirror-of-archived-repo-left-active "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"    mirror_of: ledgerflow\n    settings:\n      archived: true\n\", \"    mirror_of: ledgerflow\n    settings:\n      archived: false\n      default_branch: main\n\"))'"
run_case pass github-mirror-of-active-repo-stays-active "printf '  webgrip/renovate-config:\n    forge: github\n    profile: baseline\n    mirror_of: renovate-config\n    settings:\n      default_branch: main\n' >> repos.yaml"
run_case pass github-new-archived-mirror "printf '  webgrip/seekframe:\n    forge: github\n    profile: baseline\n    mirror_of: seekframe\n    settings:\n      archived: true\n' >> repos.yaml"
run_case fail unfold-cluster-merge-by-a-developer "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  unfold-cluster:\"); p.write_text(s[:i] + s[i:].replace(\"        merge:\n          - ryangr0\n\", \"        merge:\n          - ryangr0\n          - yon\n\", 1))'"
run_case fail unfold-cluster-push-by-a-developer "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  unfold-cluster:\"); p.write_text(s[:i] + s[i:].replace(\"        push: []\n\", \"        push:\n          - yon\n\", 1))'"
run_case fail unfold-cluster-merge-whitelist-dropped "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  unfold-cluster:\"); p.write_text(s[:i] + s[i:].replace(\"        merge:\n          - ryangr0\n\", \"\", 1))'"
run_case fail unfold-cluster-requires-no-checks "python3 -c 'import re,pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  unfold-cluster:\"); p.write_text(s[:i] + re.sub(r\"        status_checks:\\n(          - .*\\n)+\", \"        status_checks: []\\n\", s[i:], count=1))'"
run_case pass unfold-cluster-fewer-checks-still-gated "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  unfold-cluster:\"); p.write_text(s[:i] + s[i:].replace(\"          - \\\"infra-check / token-mask-proof (pull_request)\\\"\n\", \"\", 1))'"
run_case fail protected-profile-allows-a-push "python3 -c 'import pathlib; p=pathlib.Path(\"profiles.yaml\"); p.write_text(p.read_text().replace(\"          push: []\n\", \"          push:\n            - ryangr0\n\", 1))'"
run_case fail repo-rule-reopens-push "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  unfold:\"); p.write_text(s[:i] + s[i:].replace(\"        push: []\n\", \"        push:\n          - webgrip-ci\n\", 1))'"
run_case fail active-repo-left-on-baseline "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  seekframe:\n    forge: forgejo\n    profile: protected\n\", \"  seekframe:\n    forge: forgejo\n    profile: baseline\n\"))'"
run_case fail core-repo-on-plain-protected "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  workflows:\n    forge: forgejo\n    profile: protected-core\n\", \"  workflows:\n    forge: forgejo\n    profile: protected\n\"))'"
run_case fail core-profile-without-approval "python3 -c 'import pathlib; p=pathlib.Path(\"profiles.yaml\"); p.write_text(p.read_text().replace(\"          required_approvals: 1\n\", \"          required_approvals: 0\n\"))'"
run_case fail tag-whitelist-not-a-username "python3 -c 'import pathlib; p=pathlib.Path(\"profiles.yaml\"); p.write_text(p.read_text().replace(\"          - webgrip-ci\n\", \"          - webgrip ci\n\", 1))'"
run_case fail renovate-preset-pins-a-version "sed -i '0,/^        - \"local>webgrip\/renovate-config:apm\"$/s//        - \"local>webgrip\/renovate-config:apm#v1.15.0\"/' repos.yaml"
run_case fail renovate-unknown-profile "sed -i '0,/^      profile: profile-library$/s//      profile: profile-libary/' repos.yaml"
run_case fail renovate-profile-and-presets "sed -i '0,/^      profile: profile-library$/s//      profile: profile-library\n      presets:\n        - \"local>webgrip\/renovate-config:apm\"/' repos.yaml"
run_case fail renovate-unknown-key "sed -i '0,/^      profile: profile-library$/s//      profile: profile-library\n      pin: v1.15.0/' repos.yaml"
run_case fail renovate-empty-presets "python3 -c 'import re,pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(re.sub(r\"      presets:\\n(        - .*\\n)+\", \"      presets: []\\n\", p.read_text(), count=1))'"
run_case fail renovate-absent-false "sed -i '0,/^      profile: profile-site$/s//      absent: false/' repos.yaml"
run_case fail active-repo-without-renovate-policy "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"    renovate:\n      profile: profile-site\n\", \"\", 1))'"
run_case fail github-mirror-carries-renovate-policy "printf '  webgrip/renovate-config:\n    forge: github\n    profile: baseline\n    mirror_of: renovate-config\n    settings:\n      default_branch: main\n    renovate:\n      profile: profile-library\n' >> repos.yaml"
run_case pass renovate-explicit-absent "sed -i '0,/^      profile: profile-site$/s//      absent: true/' repos.yaml"
run_case pass renovate-presets-swapped-for-profile "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"      presets:\n        - \\\"local>webgrip/renovate-config:profile-app\\\"\n        - \\\"local>webgrip/renovate-config:apm\\\"\n\", \"      profile: profile-app\n\", 1))'"

run_case fail active-repo-without-a-kind "sed -i '0,/^    kind: service$/{/^    kind: service$/d}' repos.yaml"
run_case fail unknown-kind "sed -i '0,/^    kind: package$/s//    kind: library/' repos.yaml"
run_case fail mirror-with-a-kind "sed -i '0,/^    mirror_of: \\(.*\\)$/s//    mirror_of: \\1\\n    kind: service/' repos.yaml"

run_case pass platform-automerge-behind-the-gate "true"
run_case fail platform-automerge-without-a-gate "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); p.write_text(p.read_text().replace(\"  seekframe:\\n    forge: forgejo\\n    profile: protected\\n    kind: package\\n    renovate:\\n      presets:\\n\", \"  seekframe:\\n    forge: forgejo\\n    profile: protected\\n    kind: package\\n    renovate:\\n      presets:\\n        - \\\"local>webgrip/renovate-config:platform-automerge\\\"\\n\", 1))'"
run_case fail platform-automerge-with-one-branch-ungated "python3 -c 'import pathlib; p=pathlib.Path(\"repos.yaml\"); s=p.read_text(); i=s.index(\"  unfold:\"); p.write_text(s[:i] + s[i:].replace(\"          - \\\"* / gate (pull_request)\\\"\\n\", \"          - \\\"\\\\\\\\[Workflow\\\\\\\\] On Pull Request / checks (pull_request)\\\"\\n\", 1))'"

if [ "$failures" -ne 0 ]; then
  echo "test-validate-repo-config-model: ${failures} case(s) wrong"
  exit 1
fi
echo "test-validate-repo-config-model: all cases behave"
