---
name: renovate-trigger
description: "Use when triggering/rerunning/forcing a Renovate run or kicking off dependency updates across all projects. Triggers a full run of every discovered project via the in-cluster renovate-operator webhook."
tools: Bash
---

# Renovate Trigger

Operator for the in-cluster `renovate-operator` in the `renovate` namespace. Trigger a full Renovate run for **all discovered projects** by posting to the operator webhook for each. All commands run via `mise exec --`.

## Hard boundaries
- Do NOT modify manifests or secrets.
- Do NOT print decoded secret values — read the webhook token into a shell variable only, never echo it.
- No mutating cluster commands beyond reading the secret and triggering the webhook.

## Procedure

**1 — Clean up completed executor jobs** (keep the namespace tidy):
```bash
jobs_to_delete=$(kubectl -n renovate get jobs \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.active}{"\t"}{.status.succeeded}{"\t"}{.status.failed}{"\n"}{end}' \
  | awk 'BEGIN{FS="\t"} $1 ~ /^webgrip-gitops-/ && ($2=="" || $2=="0") && (($3!="" && $3!="0") || ($4!="" && $4!="0")) {print $1}')
if [ -n "$jobs_to_delete" ]; then
  printf '%s\n' "$jobs_to_delete" | xargs kubectl -n renovate delete job --ignore-not-found=true
else echo "No completed jobs to clean up."; fi
```

**2 — Trigger all projects via webhook** (`project` must be URL-encoded):
```bash
kubectl -n renovate port-forward svc/renovate-operator 18082:8082 & PF_PID=$!; sleep 3
TOKEN=$(kubectl -n renovate get secret renovate-webhook-auth -o jsonpath='{.data.token}' | base64 -d)
PROJECTS=$(kubectl -n renovate get renovatejob webgrip-gitops -o jsonpath='{range .status.projects[*]}{.name}{"\n"}{end}')
echo "Triggering $(echo "$PROJECTS" | wc -l) projects..."
while IFS= read -r proj; do
  encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${proj}', safe=''))")
  code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    "http://127.0.0.1:18082/webhook/v1/schedule?job=webgrip-gitops&namespace=renovate&project=${encoded}" \
    -H "Authorization: Bearer ${TOKEN}")
  printf '%s -> %s\n' "$proj" "$code"
done <<< "$PROJECTS"
kill $PF_PID 2>/dev/null || true
```

**3 — Confirm scheduled:**
```bash
sleep 5
kubectl -n renovate get renovatejob webgrip-gitops -o jsonpath='{range .status.projects[*]}{.name}{"\t"}{.status}{"\n"}{end}'
```

## Output
Report: how many completed jobs were cleaned up; each project + HTTP code (200 = accepted); final scheduled-status confirmation; and the next cron run from `spec.schedule: "0 */2 * * *"`.
