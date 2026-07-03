#!/usr/bin/env bash
# Shift-left guard for the W7 zero-trust netpols.
#
# Any app in a zero-trust namespace (Namespace labelled
# kyverno.io/default-network-policies: "true", which makes Kyverno generate a
# default-deny) that does SERVER-SIDE OIDC discovery — i.e. its pod fetches a
# .well-known/openid-configuration or oidc_endpoint that resolves to a gateway
# VIP — MUST pull in the shared components/gateway-egress component. Without it
# Cilium drops the post-DNAT egress to the envoy backend ("dial tcp
# 10.0.0.27:443: i/o timeout") and OIDC login returns 500. This failure passes
# kubeconform + flux-local render and only surfaces on a live login, so we gate
# it at build time instead. See components/gateway-egress and ADR-0005.
set -Eeuo pipefail
ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

APPS_DIR="${ROOT_DIR}/kubernetes/apps"
# Server-side OIDC discovery/endpoint that an app's pod fetches itself (the
# consumer side). Deliberately NOT "application/o/", which also appears in
# Authentik's provider blueprints (the producer side).
OIDC_RE='well-known/openid-configuration|oidc_endpoint'
COMPONENT_RE='components/gateway-egress'

# Namespaces that get a Kyverno-generated default-deny (zero-trust).
zt_namespaces=""
while IFS= read -r nsfile; do
    if grep -qE 'kyverno\.io/default-network-policies:[[:space:]]*"true"' "${nsfile}"; then
        zt_namespaces+="$(basename "$(dirname "${nsfile}")")"$'\n'
    fi
done < <(find "${APPS_DIR}" -mindepth 2 -maxdepth 2 -name namespace.yaml)

fail=0
checked=0
while IFS= read -r hit; do
    appdir="$(dirname "${hit}")"
    rel="${appdir#"${APPS_DIR}/"}"
    ns="${rel%%/*}"
    # only enforce inside zero-trust namespaces — elsewhere egress is open
    grep -qxF "${ns}" <<<"${zt_namespaces}" || continue
    kfile="${appdir}/kustomization.yaml"
    if [[ ! -f "${kfile}" ]]; then
        log warn "server-side OIDC discovery found but no sibling kustomization.yaml" "path=${rel}"
        continue
    fi
    checked=$((checked + 1))
    if ! grep -qE "${COMPONENT_RE}" "${kfile}"; then
        log error "zero-trust app does server-side OIDC discovery but is missing the gateway-egress component" \
            "namespace=${ns}" \
            "kustomization=${rel}/kustomization.yaml" \
            "fix=add '../../../../components/gateway-egress' under components:"
        fail=1
    fi
done < <(grep -rlE "${OIDC_RE}" "${APPS_DIR}" --include='*.yaml')

if ((fail)); then
    log error "gateway-egress guard FAILED — see fixes above"
    exit 1
fi
log info "gateway-egress guard passed" "zero-trust-oidc-apps=${checked}"
