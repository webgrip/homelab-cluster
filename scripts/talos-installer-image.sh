#!/usr/bin/env bash
set -euo pipefail

host="$1"
talos_version="$2"
inventory="${3:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../talos" && pwd)/nodes.yaml}"

node_field() {
    NODE="${host}" yq -r ".nodes[] | select(.hostname == env(NODE)) | .$1 // \"\"" "${inventory}"
}

[ -n "$(node_field hostname)" ] || { echo "no node ${host} in ${inventory}" >&2; exit 1; }

installer_image="$(node_field installerImage)"
if [ -z "${installer_image}" ]; then
    printf '%s/%s:%s\n' "$(yq -r '.installerRegistry' "${inventory}")" "$(node_field schematic)" "${talos_version}"
    exit 0
fi

pinned='^[a-z0-9.-]+(:[0-9]+)?/[a-z0-9._/-]+:([A-Za-z0-9._-]+)@sha256:[a-f0-9]{64}$'
[[ "${installer_image}" =~ ${pinned} ]] || {
    echo "${host}: installerImage must be <registry>/<repository>:<tag>@sha256:<digest>, got ${installer_image}" >&2
    exit 1
}
tag="${BASH_REMATCH[2]}"
[[ "${tag}" == "${talos_version}-"* ]] || {
    echo "${host}: installerImage tag ${tag} is not built for Talos ${talos_version}; rebuild it for ${talos_version} or remove installerImage" >&2
    exit 1
}
printf '%s\n' "${installer_image}"
