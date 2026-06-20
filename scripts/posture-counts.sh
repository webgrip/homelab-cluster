#!/usr/bin/env bash
# Verified hardening-posture counts for the roadmap-topup skill (step 1).
# Prints a compact labeled count block from the manifests under kubernetes/.
# Read-only; no cluster access. Single source of truth for these greps so they
# don't rot inside the skill.
set -Eeuo pipefail

ROOT_DIR="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "${ROOT_DIR}"

# count <extended-regex> [path]  -> number of files matching (0 on no match)
count() { { grep -rlE "$1" "${2:-kubernetes/}" 2>/dev/null || true; } | wc -l | tr -d ' '; }

echo "Hardening posture (file counts under kubernetes/):"
echo "  PodDisruptionBudget:   $(count 'kind: PodDisruptionBudget')"
echo "  NetworkPolicy:         $(count 'kind: NetworkPolicy')"
echo "  CiliumNetworkPolicy:   $(count 'kind: (CiliumNetworkPolicy|CiliumClusterwideNetworkPolicy)')"
echo "  ResourceQuota:         $(count 'kind: ResourceQuota')"
echo "  SecurityPolicy:        $(count 'kind: SecurityPolicy')"

echo
echo "Kyverno validationFailureAction (Audit vs Enforce):"
for f in kubernetes/apps/kyverno/policies/app/*.yaml; do
  [ -e "$f" ] || continue
  grep -m1 'validationFailureAction:' "$f" || true
done | sort | uniq -c | sed 's/^/  /'

echo
echo "Namespaces with a NetworkPolicy:"
{ grep -rl 'kind: NetworkPolicy' kubernetes/apps/ 2>/dev/null || true; } \
  | sed 's|kubernetes/apps/||;s|/.*||' | sort -u | sed 's/^/  /'
