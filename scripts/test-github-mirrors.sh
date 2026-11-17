#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
reconciler="$repo_root/kubernetes/apps/github-config/github-mirrors/app/github_mirrors.py"
suite="$repo_root/scripts/test_github_mirrors.py"
python="${PYTHON:-python3}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> unmutated reconciler must pass"
RECONCILER_SCRIPT="$reconciler" "$python" "$suite"

mutate() {
  name="$1"
  test_name="$2"
  shift 2
  copy="$work/$name.py"
  "$python" - "$reconciler" "$copy" "$@" <<'PY'
import sys
source, target, *pairs = sys.argv[1:]
text = open(source).read()
for find, replace in zip(pairs[0::2], pairs[1::2]):
    if find not in text:
        sys.exit(f"mutation anchor not found: {find!r}")
    text = text.replace(find, replace, 1)
open(target, "w").write(text)
PY
  if RECONCILER_SCRIPT="$copy" "$python" "$suite" "ReconcilerTest.$test_name" >"$work/$name.log" 2>&1; then
    echo "MUTATION SURVIVED: $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: $name by $test_name"
}

mutate missing-release-read-as-present test_missing_release_is_copied_with_assets_and_flags \
  'if release["tag_name"] not in target_release_tags),' \
  'if release["tag_name"] in target_release_tags),'
mutate existing-releases-copied-again test_extra_github_releases_are_counted_and_never_changed \
  'if release["tag_name"] not in target_release_tags),' \
  'if True),'
mutate guard-gone-and-cleanup-hits-an-old-release test_failed_asset_upload_discards_only_the_new_draft \
  'if release_id not in self.created_release_ids:' \
  'if False:' \
  'github.discard(created["id"])' \
  'github.discard(5001)'
mutate failed-copy-left-behind test_failed_asset_upload_discards_only_the_new_draft \
  '    except Exception:
        github.discard(created["id"])
        raise' \
  '    except Exception:
        raise'
mutate release-created-without-its-tag test_release_waits_until_its_tag_reached_github \
  '            if release["tag_name"] not in target_tags:
                continue' \
  ''
mutate every-copy-marked-latest test_older_copy_is_not_marked_latest \
  'release["tag_name"] == latest_tag, config["scratch"]' \
  'True, config["scratch"]'
mutate assets-skipped test_missing_release_is_copied_with_assets_and_flags \
  'for asset in release.get("assets") or []:' \
  'for asset in []:'
mutate drafts-published test_draft_release_stays_a_draft \
  'if not release.get("draft"):
            github.publish' \
  'if True:
            github.publish'
mutate releases-missing-metric-dropped test_release_waits_until_its_tag_reached_github \
  'metrics.set("releases_missing", labels, len(missing) - copied)' \
  'pass'
mutate extra-releases-metric-dropped test_extra_github_releases_are_counted_and_never_changed \
  'metrics.set("releases_extra", labels, len(target_release_tags - source_release_tags))' \
  'pass'
mutate head-always-matches test_head_mismatch_is_reported \
  'metrics.set("head_match", labels, 1 if target_head == source_head and' \
  'metrics.set("head_match", labels, 1 if True or'
mutate mirror-error-ignored test_push_mirror_status_is_exported \
  'metrics.set("error", labels, 1 if (mirror.get("last_error") or "").strip() else 0)' \
  'metrics.set("error", labels, 0)'
mutate budget-ignored test_copy_budget_copies_the_oldest_first \
  'if copied >= copy_budget or not writable:' \
  'if not writable:'
mutate token-not-scoped test_installation_tokens_are_scoped_to_one_repository_and_one_permission \
  'body={"repositories": [name], "permissions": dict(permissions)})' \
  'body={"repositories": [name]})'
mutate administration-token-asks-for-everything test_installation_tokens_are_scoped_to_one_repository_and_one_permission \
  'ADMINISTRATION_WRITE = {"administration": "write"}' \
  'ADMINISTRATION_WRITE = {"administration": "write", "contents": "write"}'
mutate token-mirror-removed-before-the-ssh-mirror-pushed test_a_token_mirror_is_replaced_by_a_keyed_ssh_mirror_once_that_pushes \
  'if has_pushed_cleanly(keep) and retire_other_mirrors(' \
  'if retire_other_mirrors('
mutate token-mirror-removed-while-the-ssh-mirror-fails test_a_failing_ssh_mirror_keeps_the_token_mirror \
  'return timestamp_seconds(mirror.get("last_update")) > 0 and not (mirror.get("last_error") or "").strip()' \
  'return timestamp_seconds(mirror.get("last_update")) > 0'
mutate token-mirror-never-retired test_a_token_mirror_is_replaced_by_a_keyed_ssh_mirror_once_that_pushes \
  'if has_pushed_cleanly(keep) and retire_other_mirrors(' \
  'if False and retire_other_mirrors('
mutate deploy-key-read-only test_a_token_mirror_is_replaced_by_a_keyed_ssh_mirror_once_that_pushes \
  '"key": wanted, "read_only": False}' \
  '"key": wanted, "read_only": True}'
mutate mirror-not-pushed-on-commit test_a_token_mirror_is_replaced_by_a_keyed_ssh_mirror_once_that_pushes \
  '"sync_on_commit": True,' \
  '"sync_on_commit": False,'
mutate first-push-not-triggered test_a_token_mirror_is_replaced_by_a_keyed_ssh_mirror_once_that_pushes \
  '    forgejo.sync_push_mirrors(forgejo_repository)
    log(' \
  '    log('
mutate deleted-deploy-key-left-missing test_a_deleted_deploy_key_is_registered_again \
  'if admin.ensure_deploy_key(keep["public_key"]):' \
  'if False:'
mutate refused-key-leaves-an-orphan-mirror test_a_refused_deploy_key_removes_the_new_mirror_and_fails_the_check \
  '    except ReconcilerFailure:
        forgejo.delete_push_mirror(forgejo_repository, created["remote_name"])
        raise' \
  '    except ReconcilerFailure:
        raise'
mutate mirror-changed-without-deploy-key-access test_without_deploy_key_access_the_push_mirror_is_left_alone \
  '        metrics.set("deploy_key_access", labels, 0)
        return push_mirrors' \
  '        metrics.set("deploy_key_access", labels, 0)
        create_keyed_mirror(config, forgejo, app.repository(github_repository), github_repository, forgejo_repository)
        return push_mirrors'
mutate mirror-follows-a-transferred-repository test_a_repository_that_moved_on_github_gets_no_push_mirror \
  'if (target.get("full_name") or "").lower() != expected_name.lower():' \
  'if False:'
mutate token-mirror-count-dropped test_a_token_mirror_is_replaced_by_a_keyed_ssh_mirror_once_that_pushes \
  'metrics.set("token_push_mirrors", labels, sum(1 for each in mirrors if not is_keyed(each)))' \
  'pass'
mutate absent-credentials-exit-nonzero test_absent_app_credentials_exit_zero_and_touch_nothing_on_github \
  '            metrics.set("reconciler_last_success_timestamp_seconds", {}, int(time.time()))
            return 0' \
  '            return 1'
mutate archived-mirror-tracked test_model_parser_matches_yaml_on_the_real_model \
  'entries[key]["archived"] = setting.group("value") == "true"' \
  'entries[key]["archived"] = False'
mutate github-drift-blind test_model_drift_on_both_forges \
  'drifted = repository["name"] not in modelled_github' \
  'drifted = False'
mutate broken-read-reads-as-success test_a_broken_read_fails_the_run_but_still_reports \
  '        if failures:
            log(f"{failures} check(s) failed")
            return 1' \
  ''

echo "all mutations killed"
