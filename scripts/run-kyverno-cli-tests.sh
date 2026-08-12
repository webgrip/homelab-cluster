#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/kyverno-tests.sh"

check_cli docker find mktemp rsync sed python3

workspace="$(mktemp -d)"
trap 'rm -rf "${workspace}"' EXIT

prepare_kyverno_test_workspace "${ROOT_DIR}" "${workspace}"

log info "Running Kyverno CLI tests" "workspace=${workspace}" "image=${KYVERNO_CLI_IMAGE}"
results="${workspace}/results.txt"
set +e
docker run --rm \
    -v "${workspace}:/work" \
    "${KYVERNO_CLI_IMAGE}" \
    test /work/cli 2>&1 | tee "${results}"
cli_status="${PIPESTATUS[0]}"
set -e
[[ "${cli_status}" -ne 0 ]] && exit "${cli_status}"

# NO-VACUOUS-ASSERTIONS GATE (added 2026-08-12).
#
# `kyverno test` scores an assertion about a resource the policy does NOT match as
# `Pass / Excluded` — green. So an assertion can stop testing anything the moment the
# policy's matchConstraints stop covering that kind, and the suite stays 100% green.
#
# That is not hypothetical. image-supply-chain-audit declared `spec.autogen.podControllers`,
# which Kyverno 1.18.1 accepts and ignores; the policy silently covered Pods only, and
# live PolicyReports showed 81 Pod results and ZERO for any controller. Controller
# assertions added to catch it ALSO passed — as Excluded — until this gate existed.
#
# `Excluded` is legitimate for exactly one thing: an assertion that expects `skip`
# (image-verify-audit / image-attestations-audit on a third-party image). Those pairs are
# collected from the test YAML and allowed; every other Excluded row is a vacuous
# assertion and fails the build.
allowed_skips="${workspace}/allowed-skips.txt"
# python3, not yq: yq is not a declared dependency of this script and silently produced
# an EMPTY allow-list when first written, which made the gate reject the two legitimate
# skip assertions. A tool that is missing rather than broken fails quietly here because
# the extraction is best-effort.
python3 - "${workspace}/cli" >"${allowed_skips}" <<'PYEOF'
import os, re, sys
out = []
for root, _, files in os.walk(sys.argv[1]):
    for fn in files:
        if fn != "kyverno-test.yaml":
            continue
        blocks = re.split(r"\n  - (?=policy:)", open(os.path.join(root, fn)).read())
        for b in blocks:
            if not re.search(r"^\s*result:\s*skip\s*$", b, re.M):
                continue
            pol = re.search(r"policy:\s*(\S+)", b)
            if not pol:
                continue
            for res in re.findall(r"^\s*-\s+(\S+)\s*$", b, re.M):
                out.append(f"{pol.group(1)}|{res.split('/')[-1]}")
print("\n".join(sorted(set(out))))
PYEOF

vacuous=0
while IFS= read -r line; do
    pol="$(echo "${line}" | awk -F'│' '{gsub(/^[ \t]+|[ \t]+$/, "", $3); print $3}')"
    res="$(echo "${line}" | awk -F'│' '{gsub(/^[ \t]+|[ \t]+$/, "", $5); print $5}')"
    name="${res##*/}"
    if ! grep -qxF "${pol}|${name}" "${allowed_skips}"; then
        echo "FAIL  vacuous assertion: ${pol} asserts on ${res}, which the policy does not match (scored Excluded)"
        vacuous=$((vacuous + 1))
    fi
done < <(grep 'Excluded' "${results}" || true)

if [[ "${vacuous}" -gt 0 ]]; then
    echo "FAIL: ${vacuous} assertion(s) test nothing — the policy does not match the asserted resource."
    exit 1
fi
echo "OK: no vacuous assertions (every non-skip assertion is actually evaluated)"
