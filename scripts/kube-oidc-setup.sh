#!/usr/bin/env bash
set -euo pipefail

CLIENT_ID="${KUBERNETES_OIDC_CLIENT_ID:-}"
CLUSTER="kubernetes"
CONTEXT="homelab-oidc"
USER_NAME="oidc"
KUBECONFIG_PATH="${KUBECONFIG:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)/kubeconfig}"

die() { printf 'error: %s\n' "$1" >&2; exit 1; }
ok() { printf 'ok: %s\n' "$1"; }

command -v kubectl >/dev/null || die "kubectl not found; run 'mise install' from the repo root"
kubectl oidc-login --version >/dev/null 2>&1 || die "kubelogin not found; run 'mise install' from the repo root"
ok "kubelogin present"

[[ -n "$CLIENT_ID" ]] || CLIENT_ID="$(sed -n 's/^ *oidc-client-id: *//p' "$(dirname "$0")/../talos/patches/controller/cluster.yaml" | head -1)"
[[ -n "$CLIENT_ID" ]] || die "no client id: talos/patches/controller/cluster.yaml carries none yet, or set KUBERNETES_OIDC_CLIENT_ID"
ok "client id ${CLIENT_ID}"

kubectl --kubeconfig "$KUBECONFIG_PATH" config get-clusters | grep -qx "$CLUSTER" \
  || die "cluster '$CLUSTER' is not in $KUBECONFIG_PATH; fetch the admin kubeconfig once with 'just bootstrap-talos' or talosctl kubeconfig"
ok "cluster '$CLUSTER' found"

for port in 18000 8000; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | grep -q 'IPv6'; then
    holder=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk '$5=="IPv6"{print $1; exit}')
    printf 'warning: %s listens on [::]:%s and will shadow the login callback\n' "${holder:-something}" "$port" >&2
  fi
done

SECRET="${KUBERNETES_OIDC_CLIENT_SECRET:-}"
if [[ -z "$SECRET" ]]; then
  printf 'Client secret (bao kv get -field=client_secret secret/security/kubernetes-oidc): '
  read -r -s SECRET
  echo
fi
[[ -n "$SECRET" ]] || die "no client secret given"

kubectl --kubeconfig "$KUBECONFIG_PATH" config set-credentials "$USER_NAME" \
  --exec-api-version=client.authentication.k8s.io/v1beta1 \
  --exec-command=kubectl \
  --exec-arg=oidc-login \
  --exec-arg=get-token \
  --exec-arg=--oidc-issuer-url=https://accounts.google.com \
  --exec-arg=--oidc-client-id="$CLIENT_ID" \
  --exec-arg=--oidc-client-secret="$SECRET" \
  --exec-arg=--oidc-extra-scope=email \
  --exec-arg=--oidc-extra-scope=profile \
  --exec-arg=--listen-address=127.0.0.1:18000 \
  --exec-arg=--listen-address=127.0.0.1:8000 >/dev/null
ok "credentials '$USER_NAME' written to $KUBECONFIG_PATH"

kubectl --kubeconfig "$KUBECONFIG_PATH" config set-context "$CONTEXT" --cluster="$CLUSTER" --user="$USER_NAME" >/dev/null
ok "context '$CONTEXT' written"

echo "Signing you in; a browser tab will open."
kubectl --kubeconfig "$KUBECONFIG_PATH" --context "$CONTEXT" auth whoami \
  || die "login failed: cancelled browser login, wrong client secret, or hd=webgrip.nl not satisfied; see docs/techdocs/docs/runbooks/kubernetes-login.md"

if [[ "${1:-}" == "--no-switch" ]]; then
  ok "done; the current context was not changed"
else
  kubectl --kubeconfig "$KUBECONFIG_PATH" config use-context "$CONTEXT" >/dev/null
  ok "done; '$CONTEXT' is now the default context in $KUBECONFIG_PATH"
fi
echo "Confirm:   kubectl auth whoami        (expect oidc:you@webgrip.nl)"
echo "Rights:    kubectl auth can-i --list  (Forbidden everywhere is expected until the model grants you a tier)"
