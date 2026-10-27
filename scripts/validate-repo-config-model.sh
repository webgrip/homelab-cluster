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
profile_set = yaml.safe_load((model / "profiles.yaml").read_text())
profiles = profile_set["profiles"]
kinds = profile_set["kinds"]
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


def kind_of(repo):
    return kinds.get(repo.get("kind"), {})


def profile_name(repo):
    return repo.get("profile") or kind_of(repo).get("profile")


def forgejo_settings(repo):
    forge_profile = profiles.get(profile_name(repo), {}).get("forgejo", {})
    return {**forge_profile.get("settings", {}), **kind_of(repo).get("settings", {}), **repo.get("settings", {})}


def forgejo_archived(repo):
    return forgejo_settings(repo).get("archived", False)


def archived(repo, profile):
    if repo["forge"] == "forgejo":
        return forgejo_archived(repo)
    forge_settings = profile.get(repo["forge"], {}).get("settings", {})
    return {**forge_settings, **repo.get("settings", {})}.get("archived", False)


for name, kind in sorted(kinds.items()):
    if kind["profile"] not in profiles:
        errors.append(f"kind {name}: resolves to profile {kind['profile']}, which profiles.yaml does not define")

for name, repo in sorted(repos.items()):
    forge = repo["forge"]
    if forge == "forgejo":
        if repo["kind"] not in kinds:
            errors.append(f"{name}: names kind {repo['kind']}, which profiles.yaml does not define")
            continue
        if repo.get("profile") == kinds[repo["kind"]]["profile"]:
            errors.append(f"{name}: profile {repo['profile']} is what kind {repo['kind']} already resolves to; drop the override")
        if (repo["kind"] == "archived") != forgejo_archived(repo):
            errors.append(f"{name}: kind archived and settings.archived must agree; an archived repository is kind archived and nothing else is")
    if profile_name(repo) not in profiles:
        errors.append(f"{name}: names profile {profile_name(repo)}, which profiles.yaml does not define")
        continue
    profile = profiles[profile_name(repo)]
    if forge not in profile:
        errors.append(f"{name}: profile {profile_name(repo)} carries no {forge} block, so the {forge} module has nothing to apply")
        continue
    renovate_runs_on_this_repo = not archived(repo, profile) and "mirror_of" not in repo
    if renovate_runs_on_this_repo and "renovate" not in repo and "renovate" not in kind_of(repo):
        errors.append(
            f"{name}: an active repository must state its Renovate policy (renovate.profile, renovate.presets,"
            " or renovate.absent), or the renovate_policy_matches_live check has nothing to compare"
        )
    if "mirror_of" in repo and "renovate" in repo:
        errors.append(f"{name}: a push mirror takes its Renovate policy from {repo['mirror_of']}; drop renovate here")
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

def branches_of(repo):
    return (
        set(profiles.get(profile_name(repo), {}).get("forgejo", {}).get("branches", {}))
        | set(kind_of(repo).get("branches", {}))
        | set(repo.get("branches", {}))
    )


def branch_rule(name, branch):
    repo = repos[name]
    profile_rule = profiles.get(profile_name(repo), {}).get("forgejo", {}).get("branches", {}).get(branch, {})
    kind_rule = kind_of(repo).get("branches", {}).get(branch, {})
    return {**profile_rule, **kind_rule, **repo.get("branches", {}).get(branch, {})}


core_kinds = {"gitops", "supply-chain"}
writer_kinds = {"workspace"}
core_repositories = {
    "homelab-cluster": "gitops",
    "unfold-cluster": "gitops",
    "agent-standards": "supply-chain",
    "workflows": "supply-chain",
    "renovate-config": "supply-chain",
}
for name, repo in sorted(repos.items()):
    if repo["forge"] != "forgejo" or forgejo_archived(repo) or repo["kind"] not in kinds:
        continue
    resolved = profile_name(repo)
    if repo["kind"] in core_kinds and resolved != "protected-core":
        errors.append(
            f"{name}: kind {repo['kind']} runs code in other repositories or in production, so it resolves to"
            f" profile protected-core (ADR-0084), not {resolved}"
        )
    if resolved == "baseline":
        errors.append(
            f"{name}: an active Forgejo repository is never on profile baseline (ADR-0083);"
            " a repository off the protected profiles can be pushed to directly or tagged by anyone with write access"
        )
    for branch in branches_of(repo):
        pushers = branch_rule(name, branch).get("push")
        if repo["kind"] in writer_kinds:
            if not pushers:
                errors.append(
                    f"{name} {branch}: a {repo['kind']} repository is written by a named account,"
                    " so its rule lists that account under push (ADR-0084)"
                )
        elif pushers is None or pushers:
            errors.append(
                f"{name} {branch}: nobody pushes to a protected branch (ADR-0083), so its rule must say push: []"
                f" (it says {pushers!r}); changes land through pull requests"
            )
for name, kind in sorted(core_repositories.items()):
    if name not in repos:
        errors.append(f"the core repository {name} must be in the model, as kind {kind}")
    elif repos[name].get("kind") != kind:
        errors.append(f"{name}: a core repository is kind {kind}, not {repos[name].get('kind')}")

platform_automerge_gate = "e2e / Lint & static validation (pull_request)"
homelab_main_checks = branch_rule("homelab-cluster", "main")["status_checks"]
if platform_automerge_gate not in homelab_main_checks:
    errors.append(
        f"homelab-cluster main must require '{platform_automerge_gate}'. The Ploeg and Unfold release group"
        " in .renovaterc.json5 uses platformAutomerge, and Forgejo's merge-when-checks-succeed merges at once"
        " when no required check matches, so this check is what holds an untested release pair out of main."
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
    f"validate-repo-config-model: {len(profiles)} profiles, {len(kinds)} kinds,"
    f" {by_forge['forgejo']} Forgejo repos, {by_forge['github']} GitHub repos, 0 errors"
)
PY
