#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit): skill-extracted guards.
# Enforces the mechanically-checkable invariants that used to live as PROSE in
# .claude/skills/* so those skills can stay terse (saves tokens on every load) and
# the rules are enforced deterministically. The model only pays tokens when it slips
# (this fix-up message). Read-only; exit 2 feeds the violation back to fix.
set -uo pipefail
input="$(cat)"
jqx(){ command -v jq >/dev/null 2>&1 && jq "$@" || mise exec -- jq "$@"; }

file="$(printf '%s' "$input" | jqx -r '.tool_input.file_path // empty' 2>/dev/null || true)"
[ -n "$file" ] || exit 0
case "$file" in *.yaml|*.yml) ;; *) exit 0;; esac
[ -f "$file" ] || exit 0
c="$(cat "$file")"
base="$(basename "$file")"

problems=""
add(){ problems+="  • $1
"; }
has(){ printf '%s' "$c" | grep -qE "$1"; }
matchP(){ printf '%s' "$c" | grep -nP "$1" | head -3 | tr '\n' ' '; }

# ── grafana-dashboard: envsubst escaping (breaks things SILENTLY) ─────────────
if printf '%s' "$file" | grep -q 'grafana/app/dashboards/' || has '^kind: GrafanaDashboard'; then
  g1="$(matchP '(?<!\$)\$[{(]')"
  [ -n "$g1" ] && add "[grafana] single '\$' before '{' or '(' → envsubst FAILS THE WHOLE grafana Kustomization (no dashboards update at all). Double it (\$\$). at: $g1"
  g2="$(matchP '(?<!\$)\$(__|[A-Za-z])')"
  [ -n "$g2" ] && add "[grafana] single-'\$' macro/var (e.g. \$model, \$__range) → envsubst blanks it → silent 'No data'. Every Grafana token must be \$\$. at: $g2"
  has 'allValue:[[:space:]]*"?\$*__all' && add "[grafana] allValue \$__all is not a real all-value → 'All' matches nothing (silent No data). Use allValue: \".*\" or omit it."
fi

# ── grafana CRD hygiene (any namespace) ──────────────────────────────────────
if has '^kind: Grafana(Dashboard|Datasource|Folder|AlertRuleGroup|ContactPoint|NotificationPolicy)'; then
  has 'instanceSelector' || add "[grafana] CRD missing spec.instanceSelector.matchLabels {grafana.internal/instance: grafana}."
fi
has '^kind: GrafanaDatasource' && { has 'editable:[[:space:]]*true' || add "[grafana] GrafanaDatasource missing 'editable: true' (operator may reject updates)."; }
has 'grafana_dashboard:[[:space:]]*"1"' && add "[grafana] dashboard ConfigMaps are dead (sidecar removed) — use a GrafanaDashboard CRD, not a ConfigMap."

# ── cnpg-database: WAL volume + storage class ─────────────────────────────────
if has 'apiVersion: postgresql\.cnpg\.io' && has '^kind: Cluster'; then
  has 'walStorage:' || add "[cnpg] Cluster has no walStorage → pg_wal shares the data disk; if Garage S3 is unreachable WAL grows unbounded and the DB CrashLoops 'no free disk space for WALs' (took Grafana + Dependency-Track down). Add a dedicated walStorage volume."
  has 'storageClass:[[:space:]]*longhorn-(general|rwx)' && add "[cnpg] CNPG storage should use storageClass 'longhorn' (reserved for CNPG), not longhorn-general/longhorn-rwx."
fi

# ── add-app: Gateway API, not Ingress ────────────────────────────────────────
case "$file" in *kubernetes/apps/*) has '^kind: Ingress$' && add "[ingress] use Gateway API (HTTPRoute via envoy-internal/envoy-external), not Ingress.";; esac

# ── add-app: app ks.yaml must not re-declare injected fields ──────────────────
if has 'apiVersion: kustomize\.toolkit\.fluxcd\.io' && has '^kind: Kustomization'; then
  case "$file" in *kubernetes/apps/*/ks.yaml)
    has '^[[:space:]]*decryption:' && add "[flux] app ks.yaml re-declares 'decryption:' — the root cluster-apps Kustomization injects decryption + remediation into every child; remove it.";;
  esac
fi

# ── authentik-oidc: blueprint ordering prefix ────────────────────────────────
case "$file" in *kubernetes/apps/authentik/app/blueprints/*)
  printf '%s' "$base" | grep -qE '^[0-9]+-' || add "[authentik] blueprint '$base' needs a numeric '<nn>-' filename prefix — blueprints apply in alphabetical order.";;
esac

if [ -n "$problems" ]; then
  printf 'Skill guard(s) failed for %s:\n%s\n(Enforced from .claude/skills/ — fix before continuing.)\n' "$file" "$problems" >&2
  exit 2
fi
exit 0
