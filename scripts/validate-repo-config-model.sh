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
fields_a_tracked_mirror_leaves_to_github = ["settings", "rulesets", "release_consumers", "managed"]


def forgejo_archived(repo):
    forge_profile = profiles.get(repo["profile"], {}).get("forgejo", {})
    return {**forge_profile.get("settings", {}), **repo.get("settings", {})}.get("archived", False)


def archived(repo, profile):
    forge_settings = profile.get(repo["forge"], {}).get("settings", {})
    return {**forge_settings, **repo.get("settings", {})}.get("archived", False)


for name, repo in sorted(repos.items()):
    forge = repo["forge"]
    if repo["profile"] not in profiles:
        errors.append(f"{name}: names profile {repo['profile']}, which profiles.yaml does not define")
        continue
    profile = profiles[repo["profile"]]
    if forge not in profile:
        errors.append(f"{name}: profile {repo['profile']} carries no {forge} block, so the {forge} module has nothing to apply")
        continue
    active_source = not archived(repo, profile) and "mirror_of" not in repo
    if active_source and "renovate" not in repo:
        errors.append(
            f"{name}: an active repository must state its Renovate policy (renovate.profile, renovate.presets,"
            " or renovate.absent), or the renovate_policy_matches_live check has nothing to compare"
        )
    if active_source and "kind" not in repo:
        errors.append(
            f"{name}: an active repository must state its kind (service, image-set, package, site, config or none;"
            " ADR-0078)"
        )
    if "mirror_of" in repo and "kind" in repo:
        errors.append(f"{name}: a push mirror takes its kind from {repo['mirror_of']}; drop kind here")
    if "mirror_of" in repo and "renovate" in repo:
        errors.append(f"{name}: a push mirror takes its Renovate policy from {repo['mirror_of']}; drop renovate here")
    if forge != "github":
        continue
    owner = name.split("/")[0]
    if owner not in github_owners:
        errors.append(f"{name}: GitHub owner {owner} is not listed under github.owners, so no Terraform object holds its credentials")
    settings = {**profile["github"]["settings"], **repo.get("settings", {})}
    if "mirror_of" in repo and not settings.get("archived", False):
        managed = [field for field in fields_a_tracked_mirror_leaves_to_github if field in repo]
        if managed:
            errors.append(
                f"{name}: an active push mirror is tracked, not managed (ADR-0085), so tofu-github never applies"
                f" its {', '.join(managed)}; drop them"
            )
    elif "managed" in repo and not settings.get("archived", False):
        errors.append(
            f"{name}: managed: false only keeps an archived repository out of tofu-github (one the App installation"
            " does not cover yet); an active repository is either managed or a tracked mirror"
        )
    elif settings.get("archived", False):
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

def branch_rule(name, branch):
    repo = repos[name]
    profile_rule = profiles.get(repo["profile"], {}).get("forgejo", {}).get("branches", {}).get(branch, {})
    return {**profile_rule, **repo.get("branches", {}).get(branch, {})}


core_repositories = {"agent-standards", "workflows", "renovate-config", "homelab-cluster", "unfold-cluster"}
for name, repo in sorted(repos.items()):
    if repo["forge"] != "forgejo" or forgejo_archived(repo):
        continue
    expected = "protected-core" if name in core_repositories else "protected"
    if repo["profile"] != expected:
        errors.append(
            f"{name}: an active Forgejo repository is on profile {expected} (ADR-0083), not {repo['profile']};"
            " a repository off it can be pushed to directly or tagged by anyone with write access"
        )
    for branch in set(profiles.get(repo["profile"], {}).get("forgejo", {}).get("branches", {})) | set(repo.get("branches", {})):
        pushers = branch_rule(name, branch).get("push")
        if pushers is None or pushers:
            errors.append(
                f"{name} {branch}: nobody pushes to a protected branch (ADR-0083), so its rule must say push: []"
                f" (it says {pushers!r}); changes land through pull requests"
            )
missing_core = sorted(core_repositories - set(repos))
if missing_core:
    errors.append(f"the core repositories {', '.join(missing_core)} must be in the model, on profile protected-core")

platform_automerge_gate = "e2e / Lint & static validation (pull_request)"
homelab_main_checks = branch_rule("homelab-cluster", "main")["status_checks"]
if platform_automerge_gate not in homelab_main_checks:
    errors.append(
        f"homelab-cluster main must require '{platform_automerge_gate}'. The Ploeg and Unfold release group"
        " in .renovaterc.json5 uses platformAutomerge, and Forgejo's merge-when-checks-succeed merges at once"
        " when no required check matches, so this check is what holds an untested release pair out of main."
    )

gate_check = "* / gate (pull_request)"
platform_automerge_presets = {"local>webgrip/renovate-config:platform-automerge"}
for name, repo in sorted(repos.items()):
    if repo["forge"] != "forgejo" or forgejo_archived(repo):
        continue
    if not platform_automerge_presets & set(repo.get("renovate", {}).get("presets", [])):
        continue
    branches = set(profiles.get(repo["profile"], {}).get("forgejo", {}).get("branches", {})) | set(repo.get("branches", {}))
    ungated = sorted(branch for branch in branches if gate_check not in branch_rule(name, branch).get("status_checks", []))
    if not branches or ungated:
        errors.append(
            f"{name}: its Renovate presets let Forgejo merge on green, so every protected branch must require"
            f" '{gate_check}' (ADR-0084); {', '.join(ungated) or 'no branch rule'} does not. Forgejo's"
            " merge-when-checks-succeed merges at once when no required check matches."
        )

unfold_production_deployers = {"ryangr0"}
unfold_main = repos.get("unfold-cluster", {}).get("branches", {}).get("main")
if unfold_main is None:
    errors.append("unfold-cluster must declare its main rule: a merge to that main deploys to production through Flux")
else:
    for field in ("push", "merge"):
        listed = unfold_main.get(field)
        if listed is None:
            errors.append(f"unfold-cluster main must list its {field} whitelist; without one every writer may {field}")
            continue
        outsiders = sorted(set(listed) - unfold_production_deployers)
        if outsiders:
            errors.append(
                f"unfold-cluster main {field} lists {', '.join(outsiders)}; only {', '.join(sorted(unfold_production_deployers))}"
                " may deploy to Unfold production (identity-and-access G-01)"
            )
    if not unfold_main.get("status_checks"):
        errors.append("unfold-cluster main must require its pull request checks; a merge there deploys to production")

if errors:
    print("validate-repo-config-model:", *errors, sep="\n  ")
    sys.exit(1)
by_forge = {forge: sum(1 for repo in repos.values() if repo["forge"] == forge) for forge in ("forgejo", "github")}
print(
    f"validate-repo-config-model: {len(profiles)} profiles,"
    f" {by_forge['forgejo']} Forgejo repos, {by_forge['github']} GitHub repos, 0 errors"
)
PY
