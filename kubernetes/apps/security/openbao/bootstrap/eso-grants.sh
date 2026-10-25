#!/bin/sh
grants="${ESO_GRANTS_FILE:-/grants/eso-grants.txt}"
export BAO_ADDR="${BAO_ADDR:-http://openbao.security.svc.cluster.local:8200}"
if [ -z "${BAO_TOKEN:-}" ]; then
  BAO_TOKEN="$(bao write -field=token auth/kubernetes/login role=openbao-config jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)")" || exit 1
  export BAO_TOKEN
fi
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

render_read_policy() {
  awk -v ns="$1" '
    $1 == ns && $2 == "read" {
      printf "path \"secret/data/%s\" {\n  capabilities = [\"read\"]\n}\n", $3
      printf "path \"secret/metadata/%s\" {\n  capabilities = [\"read\"]\n}\n", $3
    }
    $1 == ns && $2 == "database" {
      printf "path \"database/%s\" {\n  capabilities = [\"read\"]\n}\n", $3
    }
  ' "$grants"
}

render_push_policy() {
  awk -v ns="$1" '
    $1 == ns && $2 == "push" {
      printf "path \"secret/data/%s\" {\n  capabilities = [\"create\", \"read\", \"update\", \"delete\"]\n}\n", $3
      printf "path \"secret/metadata/%s\" {\n  capabilities = [\"create\", \"read\", \"update\", \"delete\", \"list\"]\n}\n", $3
    }
  ' "$grants"
}

write_tenant() {
  name="$1"
  namespace="$2"
  service_account="$3"
  policy_file="$4"
  if bao policy write "$name" "$policy_file" >/dev/null \
    && bao write "auth/kubernetes/role/$name" \
      bound_service_account_names="$service_account" bound_service_account_namespaces="$namespace" \
      policies="$name" audience=openbao ttl=1h >/dev/null; then
    echo "$name" >>"$work/desired"
  else
    echo "   WARN: $name policy or role write FAILED"
    echo "$name" >>"$work/desired"
  fi
}

if [ ! -s "$grants" ]; then
  echo "   WARN: $grants is empty or missing; leaving per-namespace roles untouched"
  exit 0
fi
: >"$work/desired"

for namespace in $(awk '$2 == "read" || $2 == "database" {print $1}' "$grants" | sort -u); do
  render_read_policy "$namespace" >"$work/read-$namespace.hcl"
  write_tenant "eso-read-$namespace" "$namespace" eso-openbao "$work/read-$namespace.hcl"
done

for namespace in $(awk '$2 == "push" {print $1}' "$grants" | sort -u); do
  render_push_policy "$namespace" >"$work/push-$namespace.hcl"
  write_tenant "eso-push-$namespace" "$namespace" eso-openbao-push "$work/push-$namespace.hcl"
done

for stale in $(bao policy list | grep -E '^eso-(read|push)-'); do
  if ! grep -qx "$stale" "$work/desired"; then
    bao delete "auth/kubernetes/role/$stale" >/dev/null 2>&1
    bao policy delete "$stale" >/dev/null && echo "   removed stale $stale"
  fi
done

echo "   $(wc -l <"$work/desired") per-namespace ESO roles converged"
