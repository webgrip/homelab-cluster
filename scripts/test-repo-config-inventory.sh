#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
inventory="$repo_root/kubernetes/apps/repo-config/repo-config/inventory/repo_config_inventory.py"
suite="$repo_root/scripts/test_repo_config_inventory.py"
python="${PYTHON:-python3}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> unmutated inventory must pass"
INVENTORY_SCRIPT="$inventory" "$python" "$suite"

mutate() {
  name="$1"
  test_name="$2"
  shift 2
  copy="$work/$name.py"
  "$python" - "$inventory" "$copy" "$@" <<'PY'
import sys
source, target, *pairs = sys.argv[1:]
text = open(source).read()
for find, replace in zip(pairs[0::2], pairs[1::2]):
    if find not in text:
        sys.exit(f"mutation anchor not found: {find!r}")
    text = text.replace(find, replace, 1)
open(target, "w").write(text)
PY
  if INVENTORY_SCRIPT="$copy" "$python" "$suite" "InventoryTest.$test_name" >"$work/$name.log" 2>&1; then
    echo "MUTATION SURVIVED: $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: $name by $test_name"
}

mutate unmodelled-never-flagged test_unmodelled_private_repository_is_reported \
  '1 if name in missing else 0' \
  '0'
mutate everything-flagged test_fully_modelled_org_passes_and_reports_zero \
  '1 if name in missing else 0' \
  '1'
mutate archived-counted test_archived_and_mirrored_repositories_are_not_counted \
  'if not repository.get("archived") and not repository.get("mirror"))' \
  'if not repository.get("mirror"))'
mutate mirrors-counted test_archived_and_mirrored_repositories_are_not_counted \
  'if not repository.get("archived") and not repository.get("mirror"))' \
  'if not repository.get("archived"))'
mutate first-page-only test_pages_are_read_until_an_empty_page \
  '        repositories.extend(batch)
    raise' \
  '        repositories.extend(batch)
        return repositories
    raise'
mutate anonymous-read test_unmodelled_private_repository_is_reported \
  ', "Authorization": f"token {token}"}' \
  '}'
mutate absent-token-tolerated test_absent_token_fails_without_reading_anonymously \
  '    if not token:
        raise' \
  '    if False:
        raise'
mutate private-blindness-tolerated test_token_blind_to_private_repositories_fails \
  'if expected_private and not visible_private:' \
  'if False:'
mutate forgejo-error-swallowed test_forgejo_error_fails_without_a_success_timestamp \
  'raise InventoryFailure(f"Forgejo GET {path} page {page} returned {error.code}") from None' \
  'return repositories'
mutate empty-model-tolerated test_empty_model_fails \
  '    if not entries:
        raise' \
  '    if False:
        raise'
mutate push-rejection-ignored test_rejected_metrics_push_fails_the_run \
  'if status >= 300:' \
  'if False:'
mutate archived-model-entry-dropped test_model_parser_matches_yaml_on_the_real_model \
  'return {key: entry for key, entry in entries.items() if entry["forge"] == "forgejo"}' \
  'return {key: entry for key, entry in entries.items() if entry["forge"] == "forgejo" and not entry["archived"]}'
mutate private-setting-unparsed test_model_parser_matches_yaml_on_the_real_model \
  'in ("archived", "private"):' \
  'in ("archived",):'
mutate prerelease-counted-as-latest test_repository_info_states_how_a_repository_ships \
  '(?P<patch>\d+)$")' \
  '(?P<patch>\d+)")'
mutate unreadable-repository-aborts test_unreadable_repository_is_reported_and_the_inventory_still_succeeds \
  'log(f"could not read the delivery files of {name}: {failure}")' \
  'raise failure'
mutate reusable-definition-ships test_own_release_and_steps_are_read_but_reusable_definitions_are_not \
  'if REUSABLE_DEFINITION.search(text):' \
  'if False:'
mutate archived-mirror-counted test_model_facts_match_yaml_on_the_real_model \
  'fact.get("mirror_of") and not fact["archived"]' \
  'fact.get("mirror_of")'
mutate lag-counts-the-newest-pin test_repository_info_states_how_a_repository_ships \
  'if version_key(tag) > version_key(oldest)' \
  'if version_key(tag) >= version_key(oldest)'

mutate composite-actions-ignored test_composite_actions_are_calls_and_pins_in_both_forms \
  'composite-actions/(?P<action>' \
  'composite-actionz/(?P<action>'
mutate composite-ships-nothing test_composite_actions_are_calls_and_pins_in_both_forms \
  '    "docker-build-push-registry-fast": "image",
' \
  ''
mutate tag-ref-unversioned test_a_pin_is_versioned_only_as_a_tag_or_a_sha_with_its_tag \
  '    if SEMVER_REF.match(ref):
        return ref' \
  '    if False:
        return ref'
mutate bare-sha-versioned test_a_pin_is_versioned_only_as_a_tag_or_a_sha_with_its_tag \
  '    return UNVERSIONED


def release_image_pins' \
  '    return ref


def release_image_pins'
mutate tooling-repository-pins-itself test_a_tooling_repository_does_not_pin_itself \
  'set() if package == name else found' \
  'found'
mutate release-image-ignored test_the_release_image_is_a_semantic_release_config_pin \
  'release_config_pins |= workflows["image_pins"]' \
  'release_config_pins |= set()'
mutate toolchain-image-input-ignored test_the_release_image_is_a_semantic_release_config_pin \
  '(?:image|toolchain-image|container)' \
  '(?:image|container)'
mutate retired-release-image-counted test_the_release_image_is_a_semantic_release_config_pin \
  '            if version_key(match.group("version")) >= FIRST_CONFIG_RELEASE}' \
  '}'
mutate old-path-reads-as-shared test_each_release_style_is_told_apart \
  '    if called & OLD_RELEASE_CALLS:' \
  '    if False:'
mutate reusable-definition-releases test_each_release_style_is_told_apart \
  '        run_calls |= {name for _, name in called}' \
  ''
mutate reusable-calls-uncounted test_composite_actions_are_calls_and_pins_in_both_forms \
  '        calls |= called' \
  ''
mutate webgrip-release-unread test_each_release_style_is_told_apart \
  '    if runs_webgrip_release:' \
  '    if False:'
mutate local-actions-unread test_each_release_style_is_told_apart \
  '    workflow_texts += local_action_texts(forgejo, name, workflow_texts)' \
  ''
mutate comments-read-as-steps test_each_release_style_is_told_apart \
  'SHARED_CALL.sub("", COMMENT_LINE.sub("", text))' \
  'SHARED_CALL.sub("", text)'
mutate red-checks-read-as-pending test_each_behind_pin_states_whether_an_update_is_on_its_way \
  '"failure": "pr_red"' \
  '"failure": "pr_pending"'
mutate approval-read-as-queued test_each_behind_pin_states_whether_an_update_is_on_its_way \
  '"awaits_approval" if line.group("action") == "approve" else "queued"' \
  '"queued"'
mutate open-dashboard-lines-read-as-waits test_each_behind_pin_states_whether_an_update_is_on_its_way \
  '        if line.group("action") in DASHBOARD_HAS_A_PULL:' \
  '        if False:'
mutate oldest-proposal-wins test_each_behind_pin_states_whether_an_update_is_on_its_way \
  'newest_first(proposal) > newest_first(proposals[package])' \
  'newest_first(proposal) < newest_first(proposals[package])'
mutate any-branch-is-renovate test_each_behind_pin_states_whether_an_update_is_on_its_way \
  '        if not ((pull.get("head") or {}).get("ref") or "").startswith(RENOVATE_BRANCH):' \
  '        if False:'
mutate current-repositories-list-pulls test_a_repository_on_the_newest_releases_reads_no_pull_requests \
  '        if not behind:
            continue' \
  '        if False:
            continue'
mutate unreadable-pulls-abort test_unreadable_pull_requests_leave_the_pins_and_skip_the_update_state \
  'log(f"could not read the open updates of {name}: {failure}")' \
  'raise failure'

echo "all mutations killed"
