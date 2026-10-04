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

[doc('Render talos/clusterconfig/ from talos/nodes.yaml, talenv.yaml and patches/ [out=dir]')]
[group('talos')]
talos-generate-config out="":
    @just _need talosctl sops yq
    @just _file {{ root }}/talos/nodes.yaml {{ root }}/talos/talenv.yaml {{ root }}/.sops.yaml "${SOPS_AGE_KEY_FILE}"
    {{ root }}/scripts/talos-genconfig.sh {{ if out == "" { root / "talos/clusterconfig" } else { out } }}

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
        '.nodes[] | select(.hostname == env(NODE) or .address == env(NODE)) | .hostname' nodes.yaml)"
    configured_ip="$(NODE="${node}" yq -r \
        '.nodes[] | select(.hostname == env(NODE) or .address == env(NODE)) | .address' nodes.yaml)"
    # An empty host means `node` matched nothing; fail loudly rather than
    # building a talosctl command around an empty filename.
    if [ -z "${host}" ]; then
        echo "node='${node}' matches no hostname or address in talos/nodes.yaml" >&2
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
# identity in both nodes.yaml and Kubernetes, so one argument serves the drain,
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
        '.nodes[] | select(.hostname == env(NODE) or .address == env(NODE)) | .hostname' nodes.yaml)"
    if [ -z "${host}" ]; then
        echo "node='{{ node }}' matches no hostname or address in talos/nodes.yaml" >&2
        exit 1
    fi
    echo "==> draining ${host}"
    kubectl drain "${host}" --ignore-daemonsets --delete-emptydir-data --timeout=600s
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
        '.nodes[] | select(.hostname == env(NODE) or .address == env(NODE))
         | [.hostname, .address, .schematic] | join(" ")' nodes.yaml)"
    if [ -z "${match}" ]; then
        echo "node='{{ node }}' matches no hostname or address in talos/nodes.yaml" >&2
        exit 1
    fi
    read -r host configured_ip schematic <<< "${match}"
    image="$(yq -r .installerRegistry nodes.yaml)/${schematic}"
    version="$(yq -r '.talosVersion' talenv.yaml)"
    target="${at:-${configured_ip}}"
    insecure_flag=""
    control_plane_endpoints_unless_insecure=""
    if [ "${insecure}" = "true" ]; then
        insecure_flag="--insecure"
        control_plane_endpoints_unless_insecure="--endpoints=${target}"
        talosctl get disks --nodes "${target}" --endpoints "${target}" --insecure >/dev/null
    else
        talosctl config info >/dev/null
        talosctl --nodes "${target}" --endpoints "${target}" get machineconfig >/dev/null
    fi
    echo "==> ${host} — upgrading to ${image}:${version} via ${target}"
    talosctl upgrade \
        --talosconfig=./clusterconfig/talosconfig \
        --nodes="${target}" ${control_plane_endpoints_unless_insecure} \
        --image="${image}:${version}" --timeout=10m ${insecure_flag}

# Upgrade Kubernetes to the version pinned in talos/talenv.yaml
[group('talos')]
talos-upgrade-k8s:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need talosctl yq
    just _file "${TALOSCONFIG}"
    cd {{ root }}/talos
    talosctl config info >/dev/null
    kubernetes_version="$(yq -r '.kubernetesVersion' talenv.yaml)"
    first_control_plane="$(yq -r '[.nodes[] | select(.role == "controlplane")][0].address' nodes.yaml)"
    talosctl upgrade-k8s --talosconfig=./clusterconfig/talosconfig \
        --nodes="${first_control_plane}" --to="${kubernetes_version}"

# DESTRUCTIVE — reset every node back to maintenance mode
[confirm('This destroys the cluster and resets every node to maintenance mode. Continue?')]
[group('talos')]
talos-reset:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need talosctl yq
    cd {{ root }}/talos
    for address in $(yq -r '.nodes[].address' nodes.yaml); do
        talosctl reset --talosconfig=./clusterconfig/talosconfig --nodes="${address}" \
            --reboot --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --graceful=false --wait=false
    done

# --- bootstrap --------------------------------------------------------------

# Bootstrap the Talos cluster from nothing
[group('bootstrap')]
bootstrap-talos:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need talosctl sops yq
    just _file {{ root }}/.sops.yaml {{ root }}/talos/nodes.yaml "${SOPS_AGE_KEY_FILE}"
    cd {{ root }}/talos
    if [ ! -f talsecret.sops.yaml ]; then
        bundle_dir="$(mktemp -d)"
        trap 'rm -rf "${bundle_dir}"' EXIT
        talosctl gen secrets --output-file "${bundle_dir}/secrets.yaml"
        sops --filename-override talos/talsecret.sops.yaml --encrypt "${bundle_dir}/secrets.yaml" > talsecret.sops.yaml
    fi
    just talos-generate-config
    while IFS=$'\t' read -r host address; do
        talosctl apply-config --talosconfig=./clusterconfig/talosconfig --nodes="${address}" \
            --file="./clusterconfig/kubernetes-${host}.yaml" --insecure
    done < <(yq -r '.nodes[] | [.hostname, .address] | @tsv' nodes.yaml)
    first_control_plane="$(yq -r '[.nodes[] | select(.role == "controlplane")][0].address' nodes.yaml)"
    until talosctl bootstrap --talosconfig=./clusterconfig/talosconfig --nodes="${first_control_plane}"; do sleep 10; done
    until talosctl kubeconfig --talosconfig=./clusterconfig/talosconfig --nodes="${first_control_plane}" {{ root }} --force; do sleep 10; done

# Bootstrap the core apps into a freshly built cluster
[group('bootstrap')]
bootstrap-apps:
    @just _file {{ root }}/.sops.yaml {{ root }}/scripts/bootstrap-apps.sh "${KUBECONFIG}" "${SOPS_AGE_KEY_FILE}"
    bash {{ root }}/scripts/bootstrap-apps.sh

# --- omnigraph --------------------------------------------------------------

[doc('Cache your Omnigraph token from secret/omnigraph/<actor> into ~/.omnigraph/credentials (0600) and write the homelab server entry if missing; the token is never printed')]
[group('omnigraph')]
omnigraph-login actor="ryan":
    #!/usr/bin/env bash
    set -euo pipefail
    just _need bao omnigraph kubectl
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    bao token lookup >/dev/null 2>&1 || bao login -method=oidc >&2
    config="${OMNIGRAPH_HOME:-$HOME/.omnigraph}/config.yaml"
    if [ ! -f "$config" ]; then
        mkdir -p "$(dirname "$config")"
        url="https://$(kubectl get httproute omnigraph -n ai -o jsonpath='{.spec.hostnames[0]}')"
        printf 'defaults:\n  server: homelab\n  default_graph: brain\nservers:\n  homelab:\n    url: %s\nprofiles:\n  brain: {server: homelab, default_graph: brain}\n  memory: {server: homelab, default_graph: memory}\n  webgrip: {server: homelab, default_graph: webgrip}\n' "$url" > "$config"
        echo "wrote $config"
    fi
    bao kv get -field=token "secret/omnigraph/{{ actor }}" | omnigraph login homelab
    if [ "{{ actor }}" = ryan ]; then
        omnigraph graphs list --server homelab >/dev/null
        echo "omnigraph: homelab credential for act-ryan works"
    else
        echo "omnigraph: stored the act-{{ actor }} credential for server homelab"
    fi

[doc('Convert one extracted meeting (see docs runbook) and load it onto a fresh review branch of <graph> as act-ingest; prints the review and merge commands')]
[group('omnigraph')]
omnigraph-ingest-meeting graph extraction raw source_kind="notes":
    #!/usr/bin/env bash
    set -euo pipefail
    just _need bao omnigraph python3 openssl
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    bao token lookup >/dev/null 2>&1 || bao login -method=oidc >&2
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    umask 077
    bao kv get -field=key "secret/omnigraph/{{ graph }}-hmac" > "$work/key"
    python3 scripts/omnigraph_meeting_to_ndjson.py --extraction "{{ extraction }}" --raw "{{ raw }}" \
        --client-key-file "$work/key" --source-kind "{{ source_kind }}" --extractor "claude-code/$(whoami)" > "$work/meeting.ndjson"
    branch="ingest/$(openssl rand -hex 6)"
    OMNIGRAPH_TOKEN_HOMELAB="$(bao kv get -field=token secret/omnigraph/ingest)" \
        omnigraph load --server homelab --graph "{{ graph }}" --branch "$branch" --from main --mode merge --data "$work/meeting.ndjson"
    printf '\nLoaded onto %s. Review, then merge as yourself:\n' "$branch"
    printf '  omnigraph commit list --server homelab --graph %s --branch %s --json\n' "{{ graph }}" "$branch"
    printf '  omnigraph branch merge %s --into main --server homelab --graph %s\n' "$branch" "{{ graph }}"

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

[doc('Print export lines for every key at secret/<path>; use as eval "$(just secret-env <path>)"')]
[group('secrets')]
secret-env path:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need bao python3
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    bao token lookup >/dev/null 2>&1 || bao login -method=oidc >&2
    bao kv get -format=json "secret/{{ path }}" | python3 -c 'import json, shlex, sys; [print(f"export {k}={shlex.quote(str(v))}") for k, v in json.load(sys.stdin)["data"]["data"].items()]'

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

# One-time seeding of the Cloudflare deploy + manager tokens into OpenBao
# (secret/cloudflare/deploy + secret/cloudflare/token-manager). From there the
# forgejo-actions-secrets publisher pushes CLOUDFLARE_* to the webgrip org and
# cloudflare-token-roller rolls the deploy token monthly — nothing here is
# ever typed again. Prompts via gum so no value lands in shell history.
[doc('Seed the Cloudflare deploy + manager tokens into OpenBao (secret/cloudflare/*)')]
[group('secrets')]
cloudflare-deploy-cred:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need bao gum kubectl
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    bao token lookup >/dev/null 2>&1 || bao login -method=oidc
    account_id="$(gum input --placeholder 'Cloudflare Account ID (zone Overview, rechtsonder)')"
    deploy_token="$(gum input --password --placeholder 'forgejo-ci-wrangler token VALUE (Workers Scripts:Edit + Account Settings:Read + Workers Routes:Edit op twente.dev + webgrip.nl)')"
    deploy_token_id="$(gum input --placeholder 'forgejo-ci-wrangler token ID (uit de API Tokens-lijst, niet de waarde)')"
    manager_token="$(gum input --password --placeholder 'homelab-token-roller token VALUE (alleen Account API Tokens:Edit)')"
    bao kv put secret/cloudflare/deploy \
        CLOUDFLARE_API_TOKEN="${deploy_token}" \
        CLOUDFLARE_ACCOUNT_ID="${account_id}" \
        CLOUDFLARE_DEPLOY_TOKEN_ID="${deploy_token_id}"
    bao kv put secret/cloudflare/token-manager \
        CLOUDFLARE_MANAGER_TOKEN="${manager_token}"
    echo "wrote secret/cloudflare/deploy + secret/cloudflare/token-manager"
    echo "ESO syncs within ~1h (or: kubectl -n forgejo annotate externalsecret forgejo-cloudflare-deploy force-sync=$(date +%s) --overwrite)"
    echo "the forgejo-actions-secrets CronJob publishes CLOUDFLARE_* to the webgrip org on its next hourly tick (:23)"

[doc('Seed the OpenTofu credential set for webgrip/cloudflare into OpenBao (secret/cloudflare/tofu)')]
[group('secrets')]
cloudflare-tofu-cred:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need bao gum kubectl openssl
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    bao token lookup >/dev/null 2>&1 || bao login -method=oidc
    tofu_token="$(gum input --password --placeholder 'forgejo-ci-tofu token VALUE (Zone Read + DNS Write op twente.dev + webgrip.nl, Single Redirect Write op webgrip.nl, Workers R2 Storage Write)')"
    tofu_token_id="$(gum input --placeholder 'forgejo-ci-tofu token ID (uit de API Tokens-lijst, niet de waarde)')"
    state_key_id="$(gum input --placeholder 'R2 API token Access Key ID (Object Read & Write, alleen bucket tofu-state)')"
    state_secret="$(gum input --password --placeholder 'R2 API token Secret Access Key')"
    passphrase="$(gum input --password --placeholder 'State-passphrase, minimaal 16 tekens (leeg = genereren)')"
    if [ -z "${passphrase}" ]; then passphrase="$(openssl rand -base64 48)"; fi
    bao kv put secret/cloudflare/tofu \
        CLOUDFLARE_TOFU_TOKEN="${tofu_token}" \
        CLOUDFLARE_TOFU_TOKEN_ID="${tofu_token_id}" \
        TOFU_STATE_ACCESS_KEY_ID="${state_key_id}" \
        TOFU_STATE_SECRET_ACCESS_KEY="${state_secret}" \
        TOFU_ENCRYPTION_PASSPHRASE="${passphrase}"
    echo "wrote secret/cloudflare/tofu"
    echo "ESO syncs within ~1h (or: kubectl -n forgejo annotate externalsecret forgejo-cloudflare-tofu force-sync=$(date +%s) --overwrite)"
    echo "the forgejo-actions-secrets CronJob publishes the four secrets to the webgrip/cloudflare repo on its next hourly tick (:23)"

[doc('Seed the Open VSX publish token for webgrip/de-vloer into OpenBao (secret/openvsx/de-vloer)')]
[group('secrets')]
openvsx-cred:
    #!/usr/bin/env bash
    set -euo pipefail
    just _need bao gum kubectl curl
    BAO_ADDR="$(just bao-addr)"; export BAO_ADDR
    bao token lookup >/dev/null 2>&1 || bao login -method=oidc
    ovsx_token="$(gum input --password --placeholder 'open-vsx.org access token (avatar -> Settings -> Access Tokens, publisher agreement signed)')"
    code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
        -d '{"name":"webgrip"}' "https://open-vsx.org/api/-/namespace/create?token=${ovsx_token}")"
    if [ "$code" = "401" ] || [ "$code" = "000" ]; then
        echo "Open VSX rejected that token (HTTP ${code}); nothing written." >&2
        exit 1
    fi
    bao kv put secret/openvsx/de-vloer OVSX_PAT="${ovsx_token}"
    echo "wrote secret/openvsx/de-vloer (verified against open-vsx.org first)"
    echo "force the sync: kubectl -n forgejo annotate externalsecret forgejo-openvsx-publish force-sync=$(date +%s) --overwrite"
    echo "wait for SecretSynced, THEN: kubectl -n forgejo create job --from=cronjob/forgejo-actions-secrets forgejo-actions-secrets-now"

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
