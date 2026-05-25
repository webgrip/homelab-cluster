set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

reconcile:
    flux --namespace flux-system reconcile kustomization flux-system --with-source

verify-oci-digests:
    ./scripts/verify-oci-digests.sh {{ justfile_directory() }}

update-oci-digests:
    ./scripts/update-oci-digests.sh {{ justfile_directory() }}

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
