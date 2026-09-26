#!/usr/bin/env bash
set -euo pipefail

talos_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../talos" && pwd)"
out_dir="${1:-${talos_dir}/clusterconfig}"
inventory="${talos_dir}/nodes.yaml"

set -a
eval "$(yq -o=shell '.' "${talos_dir}/talenv.yaml")"
set +a
talosVersion="${TALOS_VERSION_OVERRIDE:-${talosVersion}}"
kubernetesVersion="${KUBERNETES_VERSION_OVERRIDE:-${kubernetesVersion}}"
export talosVersion kubernetesVersion

umask 077
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

sops --decrypt "${talos_dir}/talsecret.sops.yaml" > "${work}/secrets.yaml"

substituted() {
    local source="$1"
    local target="${work}/patch-$(printf '%s' "${source}" | tr '/' '_')"
    [ -f "${target}" ] || yq '(.. | select(tag == "!!str")) |= envsubst(nu, ne)' "${talos_dir}/${source}" > "${target}"
    printf '@%s' "${target}"
}

patch_flags() {
    local flag="$1" query="$2" source
    while IFS= read -r source; do
        [ -n "${source}" ] || continue
        printf '%s\n%s\n' "${flag}" "$(substituted "${source}")"
    done < <(NODE="${3:-}" yq -r "${query}" "${inventory}")
}

cluster_name="$(yq -r '.clusterName' "${inventory}")"
endpoint="$(yq -r '.endpoint' "${inventory}")"
additional_sans="$(yq -r '.additionalSans | join(",")' "${inventory}")"
installer_registry="$(yq -r '.installerRegistry' "${inventory}")"

common=(
    "${cluster_name}" "${endpoint}"
    --with-secrets "${work}/secrets.yaml"
    --talos-version "${configContract}"
    --kubernetes-version "${kubernetesVersion}"
    --additional-sans "${additional_sans}"
    --with-docs=false --with-examples=false
    --force
)

mkdir -p "${out_dir}"

while IFS=$'\t' read -r host role disk schematic; do
    patches=()
    while IFS= read -r flag; do patches+=("${flag}"); done < <(
        patch_flags --config-patch '.patches.all[]'
        if [ "${role}" = "controlplane" ]; then
            patch_flags --config-patch-control-plane '.patches.controlplane[]'
        else
            patch_flags --config-patch-worker '.patches.worker[]'
        fi
        patch_flags --config-patch '.nodes[] | select(.hostname == env(NODE)) | .patches[]' "${host}"
    )
    talosctl gen config "${common[@]}" \
        --output-types "${role}" \
        --install-disk "${disk}" \
        --install-image "${installer_registry}/${schematic}:${talosVersion}" \
        "${patches[@]}" \
        --output "${out_dir}/kubernetes-${host}.yaml"
    echo "rendered ${out_dir}/kubernetes-${host}.yaml (${role}, ${schematic:0:12}, ${talosVersion})"
done < <(yq -r '.nodes[] | [.hostname, .role, .installDisk, .schematic] | @tsv' "${inventory}")

talosctl gen config "${common[@]}" --output-types talosconfig --output "${out_dir}/talosconfig"
control_planes=()
while IFS= read -r address; do control_planes+=("${address}"); done < <(yq -r '.nodes[] | select(.role == "controlplane") | .address' "${inventory}")
all_nodes=()
while IFS= read -r address; do all_nodes+=("${address}"); done < <(yq -r '.nodes[].address' "${inventory}")
talosctl --talosconfig "${out_dir}/talosconfig" config endpoint "${control_planes[@]}"
talosctl --talosconfig "${out_dir}/talosconfig" config node "${all_nodes[@]}"
echo "rendered ${out_dir}/talosconfig"
