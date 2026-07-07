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

# One-time seeding of ntfy's declarative auth into OpenBao (secret/ntfy/auth):
# users (bcrypt), tokens, and the bare alertmanager_token that the Alertmanager
# routing config templates in as the Bearer credential. Only the "phone" password
# is human-known (you type it into the ntfy app); "alertmanager" is token-only.
ntfy-auth-cred:
    #!/usr/bin/env bash
    set -euo pipefail
    python3 -c 'import bcrypt' 2>/dev/null || { echo "needs python3 bcrypt module (pip install bcrypt)"; exit 1; }
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    bao token lookup >/dev/null 2>&1 || bao login -method=oidc
    phone_pw="$(gum input --password --placeholder 'password for user "phone" (typed into the ntfy app)')"
    phone_pw2="$(gum input --password --placeholder 'repeat phone password')"
    [ -n "${phone_pw}" ] && [ "${phone_pw}" = "${phone_pw2}" ] || { echo "empty or mismatched password, aborting"; exit 1; }
    am_pw="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
    token="tk_$(python3 -c 'import secrets, string; print("".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(29)))')"
    bhash() { PW="$1" python3 -c 'import bcrypt, os; print(bcrypt.hashpw(os.environ["PW"].encode(), bcrypt.gensalt(10)).decode())'; }
    bao kv put secret/ntfy/auth \
        users="alertmanager:$(bhash "${am_pw}"):user,phone:$(bhash "${phone_pw}"):user" \
        tokens="alertmanager:${token}:alertmanager-publish" \
        alertmanager_token="${token}"
    echo 'wrote secret/ntfy/auth (users, tokens, alertmanager_token)'
    echo 'force the ESO refresh now (or wait out the 1h interval):'
    echo '  kubectl -n observability annotate externalsecret ntfy-auth force-sync=$(date +%s) --overwrite'
    echo '  kubectl -n observability annotate externalsecret vmalertmanager-config force-sync=$(date +%s) --overwrite'

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
