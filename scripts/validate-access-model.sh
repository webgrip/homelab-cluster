#!/usr/bin/env bash
set -euo pipefail

root="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
model="${root}/kubernetes/apps/security/access-plane/model"

for file in capabilities roles projects people; do
  check-jsonschema --schemafile "${model}/schema/${file}.schema.json" "${model}/${file}.yaml"
done

if python3 -c 'import yaml' >/dev/null 2>&1; then
  python3 "${root}/scripts/validate_access_model.py" "${root}"
else
  uv run --script "${root}/scripts/validate_access_model.py" "${root}"
fi
