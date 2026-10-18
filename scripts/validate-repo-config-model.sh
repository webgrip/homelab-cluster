#!/usr/bin/env bash
set -euo pipefail

root="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
model="${REPO_CONFIG_MODEL_DIR:-${root}/kubernetes/apps/repo-config/repo-config/model}"

for file in profiles repos; do
  check-jsonschema --schemafile "${model}/schema/${file}.schema.json" "${model}/${file}.yaml"
done

python3 - "${model}" <<'PY'
import pathlib
import sys

import yaml

model = pathlib.Path(sys.argv[1])
profiles = yaml.safe_load((model / "profiles.yaml").read_text())["profiles"]
repos = yaml.safe_load((model / "repos.yaml").read_text())["repos"]
unknown = sorted(f"{name} -> {repo['profile']}" for name, repo in repos.items() if repo["profile"] not in profiles)
if unknown:
    print("validate-repo-config-model: repos name a profile that profiles.yaml does not define:", *unknown, sep="\n  ")
    sys.exit(1)
print(f"validate-repo-config-model: {len(profiles)} profiles, {len(repos)} repos, 0 errors")
PY
