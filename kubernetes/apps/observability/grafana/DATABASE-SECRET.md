# Grafana database bootstrap secret

Before the `grafana-db` Flux Kustomization can reconcile, you must create and
SOPS-encrypt the `grafana-db-secret` secret in this directory.

## Steps

1. **Create the plaintext secret file:**

```bash
cat > kubernetes/apps/observability/grafana/app/grafana-db-secret.sops.yaml << 'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: grafana-db-secret
  namespace: observability
stringData:
  username: grafana
  password: <replace-with-strong-random-password>
EOF
```

Generate a strong password:
```bash
openssl rand -base64 32
```

2. **Encrypt it with SOPS:**

```bash
sops --encrypt --in-place \
  kubernetes/apps/observability/grafana/app/grafana-db-secret.sops.yaml
```

3. **Commit and push:**

```bash
git add kubernetes/apps/observability/grafana/app/grafana-db-secret.sops.yaml
git commit -m "secret(grafana): add CNPG database bootstrap secret"
git push
```

## What this secret does

CloudNativePG uses `grafana-db-secret` during `initdb` bootstrap to set the
initial password for the `grafana` database owner. After bootstrapping, CNPG
generates a second secret `grafana-db-app` with the connection details
(host, port, dbname, user, password, uri) — Grafana reads the `password` key
from `grafana-db-app` via the `GF_DATABASE_PASSWORD` env var.

## What happens after you push

1. Flux reconciles `grafana-db` Kustomization → creates CNPG Cluster + ObjectStore + ScheduledBackup
2. CNPG boots a PostgreSQL pod, runs initdb, creates the `grafana` database
3. CNPG creates `grafana-db-app` secret with connection details
4. Flux reconciles `grafana` Kustomization → Grafana HelmRelease deploys, picks up the new DB
5. Grafana migrates from SQLite to PostgreSQL on first start (fresh schema, dashboards re-provisioned from sidecar)

## Old SQLite PVC cleanup

After Grafana is confirmed working with PostgreSQL, you can delete the old SQLite PVC:

```bash
kubectl delete pvc grafana -n observability
```
