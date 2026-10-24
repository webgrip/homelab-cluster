#!/usr/bin/env bash
set -euo pipefail

root="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
model="${REPO_CONFIG_MODEL_DIR:-${root}/kubernetes/apps/repo-config/repo-config/model}"

for file in profiles repos; do
  check-jsonschema --schemafile "${model}/schema/${file}.schema.json" "${model}/${file}.yaml"
done

python3 - "${model}" <<'PY'
import json
import pathlib
import sys

import yaml

model = pathlib.Path(sys.argv[1])
profiles = yaml.safe_load((model / "profiles.yaml").read_text())["profiles"]
repo_set = yaml.safe_load((model / "repos.yaml").read_text())
repos = repo_set["repos"]
github_owners = repo_set["github"]["owners"]
errors = []

github_settings_required_when_active = [
    "visibility",
    "default_branch",
    "has_issues",
    "has_projects",
    "has_wiki",
    "has_discussions",
    "allow_merge_commit",
    "allow_squash_merge",
    "allow_rebase_merge",
    "allow_auto_merge",
    "allow_update_branch",
    "delete_branch_on_merge",
    "web_commit_signoff_required",
    "squash_merge_commit_title",
    "squash_merge_commit_message",
    "merge_commit_title",
    "merge_commit_message",
    "actions_enabled",
    "allowed_actions",
    "default_workflow_permissions",
    "can_approve_pull_request_reviews",
]
fields_an_archived_github_repo_cannot_apply = ["rulesets", "release_consumers"]


def forgejo_archived(repo):
    forge_profile = profiles.get(repo["profile"], {}).get("forgejo", {})
    return {**forge_profile.get("settings", {}), **repo.get("settings", {})}.get("archived", False)


for name, repo in sorted(repos.items()):
    forge = repo["forge"]
    if repo["profile"] not in profiles:
        errors.append(f"{name}: names profile {repo['profile']}, which profiles.yaml does not define")
        continue
    profile = profiles[repo["profile"]]
    if forge not in profile:
        errors.append(f"{name}: profile {repo['profile']} carries no {forge} block, so the {forge} module has nothing to apply")
        continue
    if forge != "github":
        continue
    owner = name.split("/")[0]
    if owner not in github_owners:
        errors.append(f"{name}: GitHub owner {owner} is not listed under github.owners, so no Terraform object holds its credentials")
    settings = {**profile["github"]["settings"], **repo.get("settings", {})}
    if settings.get("archived", False):
        carried = [field for field in fields_an_archived_github_repo_cannot_apply if field in repo]
        if carried:
            errors.append(f"{name}: archived on GitHub but carries {', '.join(carried)}; an archived repository is read-only, so they would never apply")
    else:
        missing = [field for field in github_settings_required_when_active if field not in settings]
        if missing:
            errors.append(f"{name}: an active GitHub repository needs every setting the module writes; missing {', '.join(missing)}")
    if "release_consumers" in repo:
        try:
            json.loads(repo["release_consumers"])
        except json.JSONDecodeError as error:
            errors.append(f"{name}: release_consumers is not valid JSON ({error})")
    if "mirror_of" in repo:
        source = repos.get(repo["mirror_of"])
        if source is None or source["forge"] != "forgejo":
            errors.append(f"{name}: mirror_of {repo['mirror_of']} names no Forgejo repository in the model")
        elif forgejo_archived(source) and not settings.get("archived", False):
            errors.append(f"{name}: push mirror of archived Forgejo repository {repo['mirror_of']} must be archived on GitHub too (ADR-0078 R4)")

platform_automerge_gate = "e2e / Lint & static validation (pull_request)"
homelab_main_checks = profiles[repos["homelab-cluster"]["profile"]]["forgejo"]["branches"]["main"]["status_checks"]
if platform_automerge_gate not in homelab_main_checks:
    errors.append(
        f"homelab-cluster main must require '{platform_automerge_gate}'. The Ploeg and Unfold release group"
        " in .renovaterc.json5 uses platformAutomerge, and Forgejo's merge-when-checks-succeed merges at once"
        " when no required check matches, so this check is what holds an untested release pair out of main."
    )

if errors:
    print("validate-repo-config-model:", *errors, sep="\n  ")
    sys.exit(1)
by_forge = {forge: sum(1 for repo in repos.values() if repo["forge"] == forge) for forge in ("forgejo", "github")}
print(
    f"validate-repo-config-model: {len(profiles)} profiles,"
    f" {by_forge['forgejo']} Forgejo repos, {by_forge['github']} GitHub repos, 0 errors"
)
PY
