set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

reconcile:
    flux --namespace flux-system reconcile kustomization flux-system --with-source

# Print the OpenBao address, derived from the live in-cluster HTTPRoute (no hardcoded domain).
bao-addr:
    @echo "https://$(kubectl get httproute openbao -n security -o jsonpath='{.spec.hostnames[0]}')"

# Log in to OpenBao via Authentik OIDC (opens a browser). Token caches in ~/.vault-token.
bao-login:
    #!/usr/bin/env bash
    set -euo pipefail
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    echo "OpenBao: ${BAO_ADDR}"
    bao login -method=oidc
    printf '\nFor further bao commands this shell:\n  export BAO_ADDR=%s\n' "${BAO_ADDR}"

# One-time entry of Harbor's Garage S3 registry key into OpenBao (secret/harbor/s3).
# Prompts via gum so the secret never lands in shell history; logs in if needed.
harbor-s3-cred:
    #!/usr/bin/env bash
    set -euo pipefail
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    bao token lookup >/dev/null 2>&1 || bao login -method=oidc
    key_id="$(gum input --placeholder 'Garage access key ID  -> REGISTRY_STORAGE_S3_ACCESSKEY')"
    secret="$(gum input --password --placeholder 'Garage secret key  -> REGISTRY_STORAGE_S3_SECRETKEY')"
    bao kv put secret/harbor/s3 \
        REGISTRY_STORAGE_S3_ACCESSKEY="${key_id}" \
        REGISTRY_STORAGE_S3_SECRETKEY="${secret}"
    echo "wrote secret/harbor/s3 — ESO syncs the harbor-s3 Secret within ~1m"

verify-oci-digests:
    ./scripts/verify-oci-digests.sh {{ justfile_directory() }}

update-oci-digests:
    ./scripts/update-oci-digests.sh {{ justfile_directory() }}

kyverno-test:
    ./scripts/run-kyverno-cli-tests.sh {{ justfile_directory() }}

kyverno-chainsaw:
    ./scripts/run-kyverno-chainsaw.sh {{ justfile_directory() }}

bootstrap-talos:
    #!/usr/bin/env bash
    set -euo pipefail
    cd talos
    [ -f talsecret.sops.yaml ] || talhelper gensecret | sops --filename-override talos/talsecret.sops.yaml --encrypt /dev/stdin > talsecret.sops.yaml
    talhelper genconfig
    talhelper gencommand apply --extra-flags="--insecure" | bash
    until talhelper gencommand bootstrap | bash; do sleep 10; done
    until talhelper gencommand kubeconfig --extra-flags="{{ justfile_directory() }} --force" | bash; do sleep 10; done

bootstrap-apps:
    bash ./scripts/bootstrap-apps.sh

talos-generate-config:
    cd talos && talhelper genconfig

talos-apply-node IP MODE="auto" INSECURE="false":
    #!/usr/bin/env bash
    set -euo pipefail
    cd talos
    extra_flags="--mode={{ MODE }}"
    if [ "{{ INSECURE }}" = "true" ]; then extra_flags="${extra_flags} --insecure --endpoints={{ IP }}"; fi
    talhelper gencommand apply --node {{ IP }} --extra-flags "${extra_flags}" | bash

talos-upgrade-node IP INSECURE="false":
    #!/usr/bin/env bash
    set -euo pipefail
    cd talos
    talos_image=$(yq '.nodes[] | select(.ipAddress == "{{ IP }}") | .talosImageURL' talconfig.yaml)
    talos_version=$(yq '.talosVersion' talenv.yaml)
    extra_flags="--image=${talos_image}:${talos_version} --timeout=10m"
    if [ "{{ INSECURE }}" = "true" ]; then extra_flags="${extra_flags} --insecure --endpoints={{ IP }}"; fi
    talhelper gencommand upgrade --node {{ IP }} --extra-flags "${extra_flags}" | bash

talos-upgrade-k8s:
    #!/usr/bin/env bash
    set -euo pipefail
    cd talos
    kubernetes_version=$(yq '.kubernetesVersion' talenv.yaml)
    talhelper gencommand upgrade-k8s --extra-flags "--to '${kubernetes_version}'" | bash

talos-reset:
    cd talos && talhelper gencommand reset --extra-flags="--reboot --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --graceful=false --wait=false" | bash
