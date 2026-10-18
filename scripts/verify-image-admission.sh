#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SIGNATURE_POLICY="${ROOT_DIR}/kubernetes/apps/kyverno/policies/app/image-verify-harbor-enforce.yaml"
SIGNATURE_RULE="require-webgrip-signature"
FIRST_PARTY_PATTERN='^harbor\.[a-z0-9.-]+/webgrip/[^@]+@sha256:[a-f0-9]{64}$'

usage() {
    cat <<'USAGE'
Usage: scripts/verify-image-admission.sh [--live] [IMAGE...]

Runs the Kyverno engine with the enforcing signature policy against first-party
images over the network, the way admission will, and fails if any image would be
refused. --live adds every first-party image that runs or is templated in the
cluster, plus the images HelmRelease values name for workloads that the
applications launch themselves (keys ending in Image), all read-only. Needs `docker login` to Harbor and read access to the
security/cosign-webgrip-pub ConfigMap, or COSIGN_PUB_FILE pointing at the key.
USAGE
}

live=false
declare -a images=()
for arg in "$@"; do
    case "${arg}" in
        --live) live=true ;;
        -h | --help) usage; exit 0 ;;
        *) images+=("${arg}") ;;
    esac
done

if [[ "${live}" == true ]]; then
    workloads="$(kubectl get pods,deployments,statefulsets,daemonsets,jobs,cronjobs -A -o json)"
    while IFS= read -r image; do
        images+=("${image}")
    done < <(
        jq -r '.items[] | (.spec.jobTemplate.spec.template.spec // .spec.template.spec // .spec) as $s
            | ($s.containers + ($s.initContainers // []))[].image' <<<"${workloads}"
    )
    releases="$(kubectl get helmreleases.helm.toolkit.fluxcd.io -A -o json)"
    while IFS= read -r image; do
        images+=("${image}")
    done < <(
        jq -r '.items[].spec.values // {} | paths(type == "string") as $p
            | select(($p[-1] | tostring) | test("[iI]mage$")) | getpath($p)' <<<"${releases}"
    )
fi

declare -a first_party=()
while IFS= read -r image; do
    [[ -n "${image}" ]] && first_party+=("${image}")
done < <(printf '%s\n' ${images[@]+"${images[@]}"} | grep -E "${FIRST_PARTY_PATTERN}" | sort -u)

if [[ ${#first_party[@]} -eq 0 ]]; then
    echo "FAIL: no digest-pinned first-party images to verify; pass --live or IMAGE arguments" >&2
    exit 2
fi

domain="$(printf '%s\n' "${first_party[0]}" | sed -E 's|^harbor\.([^/]+)/.*|\1|')"
workdir="$(mktemp -d)"
trap 'rm -rf -- "${workdir}"' EXIT

if [[ -n "${COSIGN_PUB_FILE:-}" ]]; then
    cp -- "${COSIGN_PUB_FILE}" "${workdir}/cosign.pub"
else
    kubectl -n security get configmap cosign-webgrip-pub -o jsonpath='{.data.cosign\.pub}' >"${workdir}/cosign.pub"
fi
grep -q 'BEGIN PUBLIC KEY' "${workdir}/cosign.pub" || { echo "FAIL: no cosign public key found" >&2; exit 2; }

sed "s|\${SECRET_DOMAIN}|${domain}|g" "${SIGNATURE_POLICY}" |
    awk '/imageRegistryCredentials:/ {skip=1; next} skip && /^          [a-zA-Z]/ {skip=0} !skip' >"${workdir}/policy.yaml"

{
    printf 'apiVersion: cli.kyverno.io/v1alpha1\nkind: Values\npolicies:\n'
    printf '  - name: image-verify-harbor-enforce\n    rules:\n'
    printf '      - name: %s\n        values:\n          cosignpub:\n            data:\n              cosign.pub: |\n' "${SIGNATURE_RULE}"
    sed 's/^/                /' "${workdir}/cosign.pub"
} >"${workdir}/values.yaml"

index=0
for image in "${first_party[@]}"; do
    index=$((index + 1))
    printf -- '---\napiVersion: v1\nkind: Pod\nmetadata:\n  name: image-%03d\n  namespace: admission-sweep\n  annotations:\n    sweep/image: "%s"\nspec:\n  containers:\n    - name: app\n      image: %s\n' \
        "${index}" "${image}" "${image}"
done >"${workdir}/pods.yaml"

mise exec -- kyverno apply "${workdir}/policy.yaml" \
    --resource "${workdir}/pods.yaml" \
    --values-file "${workdir}/values.yaml" \
    --registry --policy-report >"${workdir}/apply.log" 2>&1 || true

sed -n '/^apiVersion: openreports/,$p' "${workdir}/apply.log" >"${workdir}/report.yaml"
if [[ ! -s "${workdir}/report.yaml" ]]; then
    cat "${workdir}/apply.log" >&2
    echo "FAIL: kyverno produced no policy report" >&2
    exit 2
fi
mise exec -- yq -r '.results[] | [.resources[0].name, .result] | @tsv' "${workdir}/report.yaml" >"${workdir}/verdicts.tsv"

refused=0
index=0
for image in "${first_party[@]}"; do
    index=$((index + 1))
    pod="$(printf 'image-%03d' "${index}")"
    results="$(awk -F'\t' -v pod="${pod}" '$1 == pod {print $2}' "${workdir}/verdicts.tsv" | sort -u | paste -sd, -)"
    [[ -n "${results}" ]] || results=none
    printf '%-10s %s\n' "${results}" "${image}"
    [[ "${results}" == pass ]] || refused=$((refused + 1))
done

echo "---"
echo "image admission sweep: ${#first_party[@]} first-party images, ${refused} would be refused"
[[ ${refused} -eq 0 ]] || exit 1
