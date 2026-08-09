set shell := ["bash", "-euo", "pipefail", "-c"]

# `just` is the only task runner in this repo — Taskfile.yaml and .taskfiles/
# were removed 2026-08-02. Everything runs through mise, which exports
# KUBECONFIG, SOPS_AGE_KEY_FILE and TALOSCONFIG (see .mise.toml), so recipes do
# not set them again:
#
#     mise exec -- just <recipe>
#
# `just` has no equivalent of Taskfile's `preconditions:`, and those caught
# several real mistakes during the 2026-08-02 node work — an empty node name, a
# missing rendered config, an unreachable node. They are re-implemented as the
# explicit `_need` / `_file` guards below. Keep them: a talosctl command built
# from an empty variable still does something, just not what you meant.

root := justfile_directory()

default:
    @just --list --unsorted

# --- guards -----------------------------------------------------------------
# Stand-ins for Taskfile `preconditions:`. Private, so they stay out of --list.

# Fail unless every named binary is on PATH.
[private]
_need +bins:
    #!/usr/bin/env bash
    set -euo pipefail
    missing=
    for b in {{ bins }}; do
        command -v "$b" >/dev/null 2>&1 || missing="${missing} $b"
    done
    if [ -n "${missing}" ]; then
        echo "missing required tool(s):${missing}" >&2
        echo "all of them are pinned in .mise.toml — run through 'mise exec -- just ...'" >&2
        exit 1
    fi

# Fail unless every named file exists.
[private]
_file +paths:
    #!/usr/bin/env bash
    set -euo pipefail
    for p in {{ paths }}; do
        [ -f "$p" ] || { echo "missing required file: $p" >&2; exit 1; }
    done

# --- cluster ----------------------------------------------------------------

# Force Flux to pull in changes from Git
[group('cluster')]
reconcile:
    @just _need flux
    @just _file "${KUBECONFIG}"
    flux --namespace flux-system reconcile kustomization flux-system --with-source

# --- validation -------------------------------------------------------------

# Validate the Flux manifests your local changes affect (fast; auto-scoped to git diff)
[group('validate')]
flux-local:
    @just _need docker
    {{ root }}/scripts/run-flux-local-test.sh {{ root }}

# Validate ALL ~90 Flux kustomizations (~20min; needed for flux-root/component edits)
[group('validate')]
flux-local-full:
    @just _need docker
    FLUX_LOCAL_FULL=1 {{ root }}/scripts/run-flux-local-test.sh {{ root }}

# Run the Kyverno CLI policy regression tests
[group('validate')]
kyverno-test:
    @just _need docker
    {{ root }}/scripts/run-kyverno-cli-tests.sh {{ root }}

# Run the Chainsaw admission tests in a disposable KinD cluster
[group('validate')]
kyverno-chainsaw:
    @just _need curl docker go
    {{ root }}/scripts/run-kyverno-chainsaw.sh {{ root }}

# Kubescape posture scan against the live cluster (NSA + MITRE ATT&CK)
#
# THE `--submit=false` IS THE POINT OF THIS RECIPE. Without it kubescape offers to
# upload the cluster's posture — namespaces, workloads, RBAC, failing controls — to
# ARMO's hosted SaaS. .mise.toml has told readers since 2026-08-06 to "see the just
# recipe" for exactly this reason; the recipe did not exist until now, so the only
# record of the safe invocation was prose in an RFC. Baking the flag in means the
# documented path cannot leak, whatever the caller remembers.
#
# ASSURANCE LAYER, NOT AN ADMISSION ENGINE. Our Kyverno policies grade their own
# homework; kubescape scores the cluster against published frameworks independently
# and disagrees with us by an order of magnitude on several controls (C-0053: 289
# vs our 17; C-0013: 111 vs our 14). Treat divergence as a question, not a defect.
#
# CLI ONLY, DELIBERATELY: the in-cluster operator ships an eBPF node agent, and this
# cluster removed Falco and Tetragon for resource pressure. Evaluating the operator
# is a separate, gated decision (rfc-policy-estate-gap-analysis.md step 9).
#
# CIS is NOT the default framework. It scored 43/100 at 59% coverage and is
# uninformative here — mostly file-permission checks that are meaningless on an
# immutable OS. Pass it explicitly if you want it: `just kubescape cis-v1.10.0`.
#
# Baseline to compare against: 70/100, coverage 86% (38/40), taken 2026-08-06.
#
# Kubescape posture scan (NSA + MITRE); never submits to ARMO SaaS
[group('validate')]
kubescape framework="nsa,mitre":
    @just _need kubescape
    kubescape scan framework {{ framework }} --submit=false

# Verify OCIRepository spec.ref.digest values against the registry
[group('validate')]
verify-oci-digests:
    @just _need curl jq
    {{ root }}/scripts/verify-oci-digests.sh {{ root }}

# Update OCIRepository spec.ref.digest values from the registry
[group('validate')]
update-oci-digests:
    @just _need curl jq
    {{ root }}/scripts/update-oci-digests.sh {{ root }}

# --- talos ------------------------------------------------------------------

# Render talos/clusterconfig/ from talconfig.yaml
[group('talos')]
talos-generate-config:
    @just _need talhelper sops
    @just _file {{ root }}/talos/talconfig.yaml {{ root }}/.sops.yaml "${SOPS_AGE_KEY_FILE}"
    cd {{ root }}/talos && talhelper genconfig

# Apply a node's Talos config [node=hostname|ip, at=current addr, mode, insecure]
#
# `node` selects WHICH config to apply (hostname, or the ipAddress in
# talconfig). `at` is WHERE the machine is reachable right now, defaulting to
# the configured address.
#
# Identical in steady state; different in the two cases that matter — a new node
# still on DHCP, and any node being renumbered. Passing the node straight to
# `talhelper gencommand apply` always emits --nodes=<the address in talconfig>
# with no way to override it, so both cases fell out of the tooling and got
# driven by hand-written talosctl. --extra-flags cannot patch around it either:
# talosctl's --nodes is a string slice, so a second one appends and you target
# both addresses at once.
#
#   just talos-apply-node worker-1                      # steady state
#   just talos-apply-node worker-2 10.0.0.29            # renumbering
#   just talos-apply-node worker-3 10.0.0.70 auto true  # new node, maintenance mode
[doc("Apply a node's Talos config [node=hostname|ip, at=current addr, mode, insecure]")]
[group('talos')]
talos-apply-node node at="" mode="auto" insecure="false":
    #!/usr/bin/env bash
    set -euo pipefail
    just _need talosctl yq
    just _file "${TALOSCONFIG}"
    cd {{ root }}/talos
    node='{{ node }}'; at='{{ at }}'; mode='{{ mode }}'; insecure='{{ insecure }}'
    # Match on hostname OR configured IP so either identifies the node. env()
    # keeps the value out of the yq expression, so no quoting games.
    host="$(NODE="${node}" yq -r \
        '.nodes[] | select(.hostname == env(NODE) or .ipAddress == env(NODE)) | .hostname' talconfig.yaml)"
    configured_ip="$(NODE="${node}" yq -r \
        '.nodes[] | select(.hostname == env(NODE) or .ipAddress == env(NODE)) | .ipAddress' talconfig.yaml)"
    # An empty host means `node` matched nothing; fail loudly rather than
    # building a talosctl command around an empty filename.
    if [ -z "${host}" ]; then
        echo "node='${node}' matches no hostname or ipAddress in talos/talconfig.yaml" >&2
        exit 1
    fi
    target="${at:-${configured_ip}}"
    # Absolute: `just _file` is a fresh `just` process, and just resets cwd to
    # the justfile directory, so a relative path here would never resolve.
    just _file "{{ root }}/talos/clusterconfig/kubernetes-${host}.yaml"
    # Reachability probe, which also proves the mode: a node in maintenance
    # answers `get disks --insecure` and nothing else; a joined node answers
    # `get machineconfig` over mTLS.
    insecure_flag=""
    if [ "${insecure}" = "true" ]; then
        insecure_flag="--insecure"
        talosctl get disks --nodes "${target}" --endpoints "${target}" --insecure >/dev/null
    else
        talosctl config info >/dev/null
        talosctl --nodes "${target}" --endpoints "${target}" get machineconfig >/dev/null
    fi
    echo "==> ${host} — applying kubernetes-${host}.yaml via ${target} (configured ${configured_ip})"
    talosctl apply-config \
        --talosconfig=./clusterconfig/talosconfig \
        --nodes="${target}" --endpoints="${target}" \
        --file="./clusterconfig/kubernetes-${host}.yaml" \
        --mode="${mode}" ${insecure_flag}

# Drain, apply, wait Ready, uncordon [node=hostname|ip, at=current addr, mode, insecure]
#
# Same node/at contract as talos-apply-node — the hostname is the node's
# identity in both talconfig and Kubernetes, so one argument serves the drain,
# the apply and the uncordon. Delegates the apply itself rather than repeating
# the talosctl invocation, so the DHCP/renumber handling cannot drift between
# the two recipes.
#
#   just talos-apply-node-safe worker-1
#   just talos-apply-node-safe worker-2 10.0.0.29
[doc('Drain, apply, wait Ready, uncordon [node=hostname|ip, at=current addr, mode, insecure]')]
[group('talos')]
talos-apply-node-safe node at="" mode="auto" insecure="false":
    #!/usr/bin/env bash
    set -euo pipefail
    just _need talosctl yq kubectl
    just _file "${TALOSCONFIG}"
    cd {{ root }}/talos
    host="$(NODE='{{ node }}' yq -r \
        '.nodes[] | select(.hostname == env(NODE) or .ipAddress == env(NODE)) | .hostname' talconfig.yaml)"
    if [ -z "${host}" ]; then
        echo "node='{{ node }}' matches no hostname or ipAddress in talos/talconfig.yaml" >&2
        exit 1
    fi
    echo "==> draining ${host}"
    kubectl drain "${host}" --ignore-daemonsets --delete-emptydir-data --timeout=120s
    just talos-apply-node '{{ node }}' '{{ at }}' '{{ mode }}' '{{ insecure }}'
    echo "==> waiting for ${host} to report Ready again"
    kubectl wait "node/${host}" --for=condition=Ready --timeout=300s
    kubectl uncordon "${host}"

# Upgrade Talos on one node [node=hostname|ip, at=current addr, insecure]
[group('talos')]
talos-upgrade-node node at="" insecure="false":
    #!/usr/bin/env bash
    set -euo pipefail
    just _need talosctl yq
    just _file "${TALOSCONFIG}"
    cd {{ root }}/talos
    at='{{ at }}'; insecure='{{ insecure }}'
    # One yq pass for all three fields. Captured into a variable first, not
    # piped into `read` — an empty match would make `read` hit EOF and, under
    # `set -e`, abort before the explanatory error below ever runs.
    match="$(NODE='{{ node }}' yq -r \
        '.nodes[] | select(.hostname == env(NODE) or .ipAddress == env(NODE))
         | [.hostname, .ipAddress, .talosImageURL] | join(" ")' talconfig.yaml)"
    if [ -z "${match}" ]; then
        echo "node='{{ node }}' matches no hostname or ipAddress in talos/talconfig.yaml" >&2
        exit 1
    fi
    read -r host configured_ip image <<< "${match}"
    version="$(yq -r '.talosVersion' talenv.yaml)"
    target="${at:-${configured_ip}}"
    insecure_flag=""
    if [ "${insecure}" = "true" ]; then
        insecure_flag="--insecure"
        talosctl get disks --nodes "${target}" --endpoints "${target}" --insecure >/dev/null
    else
        talosctl config info >/dev/null
        talosctl --nodes "${target}" --endpoints "${target}" get machineconfig >/dev/null
    fi
    echo "==> ${host} — upgrading to ${image}:${version} via ${target}"
    talosctl upgrade \
        --talosconfig=./clusterconfig/talosconfig \
        --nodes="${target}" --endpoints="${target}" \
        --image="${image}:${version}" --timeout=10m ${insecure_flag}

# Upgrade Kubernetes to the version pinned in talos/talenv.yaml
[group('talos')]
talos-upgrade-k8s:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need talhelper talosctl yq
    just _file "${TALOSCONFIG}"
    cd {{ root }}/talos
    talosctl config info >/dev/null
    kubernetes_version="$(yq -r '.kubernetesVersion' talenv.yaml)"
    talhelper gencommand upgrade-k8s --extra-flags "--to '${kubernetes_version}'" | bash

# DESTRUCTIVE — reset every node back to maintenance mode
[confirm('This destroys the cluster and resets every node to maintenance mode. Continue?')]
[group('talos')]
talos-reset:
    @just _need talhelper
    cd {{ root }}/talos && talhelper gencommand reset --extra-flags="--reboot --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --graceful=false --wait=false" | bash

# --- bootstrap --------------------------------------------------------------

# Bootstrap the Talos cluster from nothing
[group('bootstrap')]
bootstrap-talos:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need talhelper talosctl sops
    just _file {{ root }}/.sops.yaml {{ root }}/talos/talconfig.yaml "${SOPS_AGE_KEY_FILE}"
    cd {{ root }}/talos
    [ -f talsecret.sops.yaml ] || talhelper gensecret | sops --filename-override talos/talsecret.sops.yaml --encrypt /dev/stdin > talsecret.sops.yaml
    talhelper genconfig
    talhelper gencommand apply --extra-flags="--insecure" | bash
    until talhelper gencommand bootstrap | bash; do sleep 10; done
    until talhelper gencommand kubeconfig --extra-flags="{{ root }} --force" | bash; do sleep 10; done

# Bootstrap the core apps into a freshly built cluster
[group('bootstrap')]
bootstrap-apps:
    @just _file {{ root }}/.sops.yaml {{ root }}/scripts/bootstrap-apps.sh "${KUBECONFIG}" "${SOPS_AGE_KEY_FILE}"
    bash {{ root }}/scripts/bootstrap-apps.sh

# --- secrets ----------------------------------------------------------------

# Print the OpenBao address, derived from the live HTTPRoute (no hardcoded domain)
[group('secrets')]
bao-addr:
    @echo "https://$(kubectl get httproute openbao -n security -o jsonpath='{.spec.hostnames[0]}')"

# Log in to OpenBao via Authentik OIDC (opens a browser). Token caches in ~/.vault-token.
[group('secrets')]
bao-login:
    #!/usr/bin/env bash
    set -euo pipefail
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    echo "OpenBao: ${BAO_ADDR}"
    bao login -method=oidc
    printf '\nFor further bao commands this shell:\n  export BAO_ADDR=%s\n' "${BAO_ADDR}"

# One-time entry of Harbor's Garage S3 registry key into OpenBao (secret/harbor/s3).
# Prompts via gum so the secret never lands in shell history; logs in if needed.
[doc('Seed Harbor’s Garage S3 registry key into OpenBao (secret/harbor/s3)')]
[group('secrets')]
harbor-s3-cred:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need bao gum kubectl
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
[doc('Seed ntfy’s declarative auth (users, tokens) into OpenBao (secret/ntfy/auth)')]
[group('secrets')]
ntfy-auth-cred:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need bao gum kubectl python3
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
