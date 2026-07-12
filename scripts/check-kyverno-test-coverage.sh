#!/usr/bin/env bash
# No-enforce-without-tests gate (roadmap #83, ADR-0032).
#
# Every Kyverno ClusterPolicy that enforces at admission (blocks a request) MUST be
# exercised by a CLI test that proves it catches a violation (>=1 `result: fail`).
# Without this, a policy can be promoted Audit→Enforce and silently block legitimate
# workloads — the exact failure the audit→enforce campaign is designed to avoid.
#
# Stronger goal (future tightening, not yet enforced because the existing suites
# predate it): also require a `result: pass` so every enforce policy proves it ADMITS
# a compliant resource. New enforce-promotion tests in the campaign SHOULD include a
# pass case even though the gate currently only mandates a fail case.
#
# "Enforces" = the policy file declares `validationFailureAction: Enforce` (spec level)
# or any rule sets `failureAction: Enforce`. This is deliberately coarse (file level):
# it errs toward REQUIRING a test, never toward letting an enforce slip by untested.
#
# Pre-existing untested enforce policies are baselined in KNOWN_UNTESTED below so this
# gate can be introduced without a flag-day; that list is debt to burn down, NOT a
# place to park new policies. Adding a new enforce policy without a test fails CI.
set -Eeuo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
POLICY_DIR="${ROOT_DIR}/kubernetes/apps/kyverno/policies/app"
CLI_DIR="${ROOT_DIR}/kubernetes/apps/kyverno/tests/cli"

# Pre-existing enforce policies still lacking a CLI test. Burn this down; do not grow it.
KNOWN_UNTESTED=(
    storage-cnpg-governance.yaml
)

is_known_untested() {
    local name="$1"
    for known in "${KNOWN_UNTESTED[@]}"; do
        [[ "${name}" == "${known}" ]] && return 0
    done
    return 1
}

# All result lines from CLI test files that reference a given policy basename. We grep
# each test file for the policy name; if present, the file's results count toward it.
test_files_referencing() {
    local base="$1"
    grep -rlE "(^|/)${base}([^A-Za-z0-9]|$)" "${CLI_DIR}"/*/kyverno-test.yaml 2>/dev/null || true
}

failures=0
baselined=0
checked=0

shopt -s nullglob
for policy in "${POLICY_DIR}"/*.yaml; do
    # Only ClusterPolicy/Policy documents.
    grep -qE '^kind: (ClusterPolicy|Policy)$' "${policy}" || continue
    # Only enforcing ones.
    grep -qE 'validationFailureAction:[[:space:]]*Enforce|failureAction:[[:space:]]*Enforce' "${policy}" || continue

    base="$(basename "${policy}")"

    if is_known_untested "${base}"; then
        echo "WARN  ${base}: enforce policy with no CLI test (baselined — burn down, see roadmap #83)"
        baselined=$((baselined + 1))
        continue
    fi

    checked=$((checked + 1))
    # while-read, not mapfile — bash 3.2 (stock macOS) has no mapfile (2026-07-12)
    refs=()
    while IFS= read -r ref; do
        [[ -n "${ref}" ]] && refs+=("${ref}")
    done < <(test_files_referencing "${base}")
    if [[ ${#refs[@]} -eq 0 ]]; then
        echo "FAIL  ${base}: enforce policy has NO CLI test referencing it (add one under tests/cli/ with a pass AND a fail case)"
        failures=$((failures + 1))
        continue
    fi

    # The referencing test(s) must prove the policy catches a violation.
    if ! grep -hqE '^[[:space:]]*result:[[:space:]]*fail' "${refs[@]}"; then
        echo "FAIL  ${base}: CLI test(s) [${refs[*]##*/cli/}] reference the policy but assert no 'result: fail' (prove it rejects a violation)"
        failures=$((failures + 1))
        continue
    fi
    # Advisory: nudge toward a pass case without failing the build (yet).
    grep -hqE '^[[:space:]]*result:[[:space:]]*pass' "${refs[@]}" || \
        echo "INFO  ${base}: has a fail case but no 'result: pass' — add one to prove it admits compliant resources"
done

echo "---"
echo "kyverno enforce test-coverage: ${checked} checked, ${failures} failing, ${baselined} baselined (debt)"
if [[ ${failures} -gt 0 ]]; then
    echo "FAIL: every enforcing Kyverno policy needs a CLI test with a pass and a fail case."
    exit 1
fi
echo "OK: every enforcing Kyverno policy (outside the baseline) is exercised by a CLI test with a fail case"
