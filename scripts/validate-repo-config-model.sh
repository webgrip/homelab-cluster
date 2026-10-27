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
staged_layer = profile_set["staged"]
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


def forgejo_archived(repo):
    return repo.get("settings", {}).get("archived", False)


def profile_name(repo):
    if repo["forge"] != "forgejo":
        return repo["profile"]
    if forgejo_archived(repo):
        return "baseline"
    if "writer" in repo:
        return "workspace"
    if repo.get("core"):
        return "protected-core"
    return "protected"


def archived(repo, profile):
    forge_settings = profile.get(repo["forge"], {}).get("settings", {})
    return {**forge_settings, **repo.get("settings", {})}.get("archived", False)


def renovate_presets(policy):
    if "profile" in policy:
        return [f"local>webgrip/renovate-config:{policy['profile']}"]
    return policy.get("presets")


def kind_renovate(repo):
    return kinds.get(repo.get("kind"), {}).get("renovate")


for name, repo in sorted(repos.items()):
    forge = repo["forge"]
    if profile_name(repo) not in profiles:
        errors.append(f"{name}: names profile {profile_name(repo)}, which profiles.yaml does not define")
        continue
    profile = profiles[profile_name(repo)]
    if forge not in profile:
        errors.append(f"{name}: profile {profile_name(repo)} carries no {forge} block, so the {forge} module has nothing to apply")
        continue
    active_source = not archived(repo, profile) and "mirror_of" not in repo
    if active_source and "renovate" not in repo and kind_renovate(repo) is None:
        errors.append(
            f"{name}: an active repository must state its Renovate policy (renovate.profile, renovate.presets,"
            " or renovate.absent) unless its kind carries one, or the renovate_policy_matches_live check has nothing to compare"
        )
    default = kind_renovate(repo)
    own = repo.get("renovate", {})
    if default and own and set(own) <= {"profile", "presets"} and renovate_presets(own) == renovate_presets(default):
        errors.append(f"{name}: its Renovate policy is what kind {repo['kind']} already gives it; drop renovate here")
    if forge == "forgejo" and forgejo_archived(repo):
        carried = [field for field in ("kind", "core", "staged", "writer") if field in repo]
        if carried:
            errors.append(f"{name}: archived, so {', '.join(carried)} would never apply; an archived repository is on baseline")
    if repo.get("core") and "writer" in repo:
        errors.append(f"{name}: a core repository needs a second person on every change, so no account writes its main directly")
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

def derived_rules(repo):
    rules = {
        branch: dict(rule)
        for branch, rule in profiles.get(profile_name(repo), {}).get("forgejo", {}).get("branches", {}).items()
    }
    if repo.get("staged"):
        for branch, rule in staged_layer["branches"].items():
            rules[branch] = {**rules.get(branch, {}), **rule}
    if "writer" in repo:
        rules["main"] = {**rules.get("main", {}), "push": [repo["writer"]]}
    return rules


def branches_of(name):
    return set(derived_rules(repos[name])) | set(repos[name].get("branches", {}))


def branch_rule(name, branch):
    repo = repos[name]
    return {**derived_rules(repo).get(branch, {}), **repo.get("branches", {}).get(branch, {})}


review_guards = ("dismiss_stale_approvals", "block_on_rejected_reviews", "block_on_outdated_branch")
required_check_events = ("(pull_request)", "(pull_request_target)")
repositories_adr_0083_named_core = {"agent-standards", "workflows", "renovate-config", "homelab-cluster", "unfold-cluster"}
for name, repo in sorted(repos.items()):
    if repo["forge"] != "forgejo" or forgejo_archived(repo):
        continue
    if name in repositories_adr_0083_named_core and not repo.get("core"):
        errors.append(f"{name}: ADR-0083 made it a core repository, so it says core: true")
    for branch in sorted(branches_of(name)):
        rule = branch_rule(name, branch)
        pushers = rule.get("push")
        allowed = [repo["writer"]] if "writer" in repo and branch == "main" else []
        if pushers != allowed:
            errors.append(
                f"{name} {branch}: only a workspace's writer pushes to its main; every other protected branch says"
                f" push: [] (ADR-0083), and this one says {pushers!r}; changes land through pull requests"
            )
        derived = derived_rules(repo).get(branch, {})
        if rule.get("required_approvals", 0) < derived.get("required_approvals", 0):
            errors.append(
                f"{name} {branch}: a repository rule may only tighten what its profile derives; it lowers"
                f" required_approvals from {derived['required_approvals']} to {rule['required_approvals']}"
            )
        loosened = [guard for guard in review_guards if derived.get(guard) and rule.get(guard) is False]
        if loosened:
            errors.append(f"{name} {branch}: a repository rule may only tighten what its profile derives; it turns off {', '.join(loosened)}")
        not_on_pull_requests = [check for check in rule.get("status_checks", []) if not check.endswith(required_check_events)]
        if not_on_pull_requests:
            errors.append(
                f"{name} {branch}: requires {', '.join(not_on_pull_requests)}, which no pull request reports;"
                " a required check that never reports blocks every merge"
            )
missing_core = sorted(repositories_adr_0083_named_core - set(repos))
if missing_core:
    errors.append(f"the core repositories {', '.join(missing_core)} must be in the model, with core: true")

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
    branches = branches_of(name)
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
    f"validate-repo-config-model: {len(profiles)} profiles, {len(kinds)} kinds,"
    f" {by_forge['forgejo']} Forgejo repos, {by_forge['github']} GitHub repos, 0 errors"
)
PY
