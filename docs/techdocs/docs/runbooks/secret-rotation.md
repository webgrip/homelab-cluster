# Runbook: Rotating a secret in OpenBao (and how it reaches your pods)

**Status:** active · **Scope:** any *provided/external* value held in OpenBao KV v2 and surfaced
into a pod by External Secrets · **Model:** [ADR-0015 — Secret rotation model](../adr/adr-0015-secret-rotation-model.md)
· **Backend ops:** [External Secrets runbook](external-secrets.md), [OpenBao restore](openbao-restore.md)

> Rotation here is a **single OpenBao write**, propagated automatically. There is no
> `sops --encrypt`, no commit, no manual `kubectl edit secret`. The whole chain is:
>
> ```text
> bao kv put secret/<app>/<name>      ← you change the value (human, OIDC-authed)
>      │
>      ▼
> OpenBao KV v2  ──(ESO ClusterSecretStore/openbao, k8s-auth role external-secrets)
>      │
>      ▼
> ExternalSecret  ── re-reads within refreshInterval (default 1h) OR on force-sync
>      │
>      ▼
> Kubernetes Secret  ── updated IN PLACE (same name/keys)
>      │
>      ▼
> Stakater Reloader (kube-system)  ── restarts the workload **iff** it carries
>      │                               reloader.stakater.com/auto: "true"
>      ▼
> Pod  ── starts with the new env/file
> ```
>
> **The agent cannot do this.** OpenBao auth is interactive Authentik OIDC with no static token
> — `bao kv put` is always a human step from your workstation.

## 0. First decide which *class* of secret you have

Rotation only makes sense for one class. Get this wrong and you either rotate nothing or corrupt
data.

| Class | How to recognise it | Rotate via this runbook? |
| --- | --- | --- |
| **Provided / external** — a value that originates *outside* the cluster (provider API token, OIDC client secret you set, Garage S3 key, a DB password you chose). Lives in OpenBao; its `ExternalSecret` uses `ClusterSecretStore/openbao` and `refreshInterval: 1h`. | `kubectl get es <name> -n <ns> -o yaml` shows `secretStoreRef.name: openbao` and `data[].remoteRef` / `dataFrom.extract`. | **✅ Yes — §3 (planned) / §4 (urgent).** |
| **Generated entropy** — random in-cluster value no human ever knows (admin pw, session/CSRF key). `ExternalSecret` uses `generatorRef: password-generator*` with `refreshInterval: "0"` (generate-once). | The ExternalSecret has `dataFrom.sourceRef.generatorRef` and `refreshInterval: "0"`. | **⚠️ Not "rotated" — regenerated.** See §5.3. Safe **only** before the app stores data. |
| **At-rest encryption key** — decrypts data already on disk (`AUTHENTIK_SECRET_KEY`, Dependency-Track `secret.key`, any `*_ENCRYPTION_KEY`, Harbor `secretKey`). | Generate-once **and** the consumer has **no** auto-reload annotation. | **❌ NEVER.** Regenerating corrupts every row encrypted with the old key. Out of scope by [ADR-0015](../adr/adr-0015-secret-rotation-model.md). |
| **Transit / cosign signing key** | OpenBao Transit, not KV. | ❌ Not here — use [cosign transit key rotation](cosign-transit-key-rotation.md). |

The rest of this runbook is the **provided/external** path unless a section says otherwise.

## 1. Pre-flight — map app → Secret → ExternalSecret → OpenBao path

You need three things before you write: the **ExternalSecret**, the **OpenBao KV path + key**, and
**whether Reloader will restart the consumer**.

```bash
# 1. Find the ExternalSecret and confirm it reads from OpenBao (not a generator)
kubectl get externalsecret -n <ns>
kubectl get es <name> -n <ns> -o yaml | grep -A20 'spec:'
#   want: secretStoreRef.name: openbao  +  refreshInterval: 1h
#   note the remoteRef.key (e.g. "codeberg/pages") and property (e.g. "token"),
#   or dataFrom.extract.key for a whole-path pull.

# 2. Derive the OpenBao path. remoteRef.key OMITS the mount; prepend secret/ for the CLI:
#      remoteRef.key: <app>/<name>   →   bao path: secret/<app>/<name>
#   (KV v2 logical path — do NOT type the "data/" segment yourself.)

# 3. Will the new value actually reach the pod? Check for the Reloader annotation on the
#    consuming workload (Deployment/StatefulSet/DaemonSet):
kubectl get deploy,sts,ds -n <ns> -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.reloader\.stakater\.com/auto}{"\n"}{end}' 2>/dev/null
#   "true"  → Reloader restarts it on the Secret change (automatic).
#   empty   → you must restart it yourself (§3 step 5) or the rotation sits unused.
```

If the consumer is **not** annotated and *should* be (rotatable secret, not an at-rest key), add
`reloader.stakater.com/auto: "true"` to its pod-template/controller annotations in the manifest and
commit — that is the durable fix; the manual restart below is the one-time bridge.

## 2. Authenticate to OpenBao (human, OIDC)

```bash
mise exec -- just bao-addr     # prints the OpenBao URL from the live HTTPRoute (no hardcoded domain)
mise exec -- just bao-login    # bao login -method=oidc (browser via Authentik); token caches in ~/.vault-token
export BAO_ADDR="$(mise exec -- just bao-addr)"   # for the bao commands below in this shell
```

There is no root/static token. If a write fails with a permission error, the `external-secrets`
**read** role can't write — you log in as **yourself** (an admin via OIDC), which can.

## 3. Planned rotation (the happy path)

```bash
# --- 3.1 Write the new value at its source ---
# Single-key path — `put` REPLACES the whole secret at that path (every key):
mise exec -- bao kv put secret/<app>/<name> <key>=<new-value>

#   ⚠️ Multi-key path (e.g. access_key_id + secret_access_key): `put` would WIPE the keys you
#   omit. To change ONE key on a multi-key path, PATCH (merge) instead:
mise exec -- bao kv patch secret/<app>/<name> <key>=<new-value>

# --- 3.2 Confirm OpenBao has it (creates a new KV version; old versions retained) ---
mise exec -- bao kv get secret/<app>/<name>          # check the value + version number

# --- 3.3 Wait for ESO, or converge now ---
# By default the ExternalSecret re-reads within its refreshInterval (1h for almost all of them).
# To not wait, force an immediate re-sync (annotation only — no manifest change, GitOps-safe):
kubectl annotate externalsecret <name> -n <ns> force-sync="$(date +%s)" --overwrite
kubectl get es <name> -n <ns>                        # want READY=True / STATUS=SecretSynced

# --- 3.4 Verify the Kubernetes Secret actually changed ---
kubectl get secret <name> -n <ns> -o jsonpath='{.data.<key>}' | base64 -d; echo
# (or compare resourceVersion before/after; ESO updates in place, same name + keys.)

# --- 3.5 Make the pod pick it up ---
# If the consumer carries reloader.stakater.com/auto: "true" → Reloader already restarted it:
kubectl get pods -n <ns> -w        # watch the new ReplicaSet/pod roll
# If it does NOT (un-annotated, or you want it immediate), restart by hand:
kubectl rollout restart deployment/<workload> -n <ns>   # or statefulset/<workload>

# --- 3.6 Verify the app is healthy and the credential works end-to-end ---
kubectl rollout status deployment/<workload> -n <ns>
# then exercise the actual feature (login, API call, backup, S3 reach) — not just "pod Ready".
```

**Latency:** bounded by `refreshInterval` (1h default) unless you force-sync. Almost all 66
ExternalSecrets (2026-07-02) sit at the conservative 1h; the `harbor-s3` write helper, by contrast,
expects ~1m. Lower the interval on a high-value credential if you rotate it often (§5.5).

## 4. Urgent rotation (suspected leak / compromise)

Don't wait for the poll. Order matters: **revoke at the provider first** if the secret is a token
the attacker can use *right now*, then re-seed.

```bash
# 1. (If externally usable) revoke/expire the OLD value at the provider — Cloudflare token,
#    GitHub PAT, Garage key, OIDC client secret in Authentik, etc. The leaked value is dead.
# 2. Write the new value (§3.1).
mise exec -- bao kv put secret/<app>/<name> <key>=<new-value>      # or patch for multi-key
# 3. Force ESO to re-read immediately (don't wait up to 1h):
kubectl annotate externalsecret <name> -n <ns> force-sync="$(date +%s)" --overwrite
# 4. Restart the consumer immediately even if Reloader would (closes the window now):
kubectl rollout restart deployment/<workload> -n <ns>
# 5. Verify (§3.4–3.6) and check for blast radius — any other secret the same actor could reach.
```

For an OIDC **client secret** you also re-mint in Authentik; see
[Authentik OIDC](authentik-oidc-login.md) and the OIDC-elimination recipe in the
[ESO runbook](external-secrets.md).

## 5. Special cases

### 5.1 Component / shared secrets that fan out to many namespaces

`cnpg-backup-s3`, `observability-s3`, `security-s3` and friends are defined once in a
`kubernetes/components/<name>/` component with **one** OpenBao path behind all copies — rotate that
single path (§3.1) and every namespace re-syncs; then restart consumers (or rely on Reloader).
For CNPG, verify a backup runs clean afterward ([CNPG backups](cnpg-backups.md)).

### 5.2 Multi-key secrets (`dataFrom.extract`)

`dataFrom: [{extract: ...}]` pulls **all** keys at the path. Use `bao kv patch` (§3.1) to change one
key without clobbering the rest, then force-sync.

### 5.3 Regenerating a *generated* secret (entropy, `refreshInterval: "0"`)

No source value to write — instead delete the derived Secret and ESO recreates it from the generator:

```bash
kubectl delete secret <name> -n <ns>     # regenerates ALL dataFrom entries with new random values
```

Safe **only** on a fresh app that has stored nothing yet; if any key is an at-rest key (§5.4), this
corrupts data — do not.

### 5.4 At-rest encryption keys — do not rotate

`AUTHENTIK_SECRET_KEY`, Dependency-Track `secret.key`, Harbor `secretKey`, any `*_ENCRYPTION_KEY`:
changing them makes existing ciphertext undecryptable. By [ADR-0015](../adr/adr-0015-secret-rotation-model.md)
their consumers deliberately carry **no** auto-reload annotation. A genuine compromise is a
data-migration/re-encryption project, not a rotation — escalate, don't `bao kv put`.

### 5.5 Tune propagation latency on a hot credential

Lower the interval in the manifest and commit (trade-off: more OpenBao reads; the urgent path §4
bypasses the poll anyway):

```yaml
# kubernetes/apps/<ns>/<app>/app/<name>.externalsecret.yaml
spec:
  refreshInterval: 10m   # was 1h
```

## 6. Rollback

KV v2 keeps version history, so a bad rotation is reversible without re-typing the value:

```bash
mise exec -- bao kv get secret/<app>/<name>                    # see current version N
mise exec -- bao kv get -version=<N-1> secret/<app>/<name>     # confirm the previous value
mise exec -- bao kv rollback -version=<N-1> secret/<app>/<name># writes it back as a new version
kubectl annotate externalsecret <name> -n <ns> force-sync="$(date +%s)" --overwrite
kubectl rollout restart deployment/<workload> -n <ns>          # if not auto-reloaded
```

If you `put` a multi-key path and wiped keys, the rollback above restores the whole prior version —
that's why §3.1 says **patch, not put** for multi-key paths.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `bao kv put` → permission denied | Using the `external-secrets` **read** role, not your admin OIDC token | `mise exec -- just bao-login` as yourself, retry. |
| Secret didn't change after the write | ExternalSecret hasn't re-read yet | force-sync (§3.3); want `READY=True / SecretSynced`. |
| `ExternalSecret` `SecretSyncedError` | Wrong path/key, or you typed `data/` in the path | Path is `secret/<app>/<name>` (logical, no `data/`); key/property must match `remoteRef`. |
| `ClusterSecretStore/openbao` `READY=False` | OpenBao sealed or down | Re-unseal ([OpenBao restore](openbao-restore.md)). Running apps unaffected (cached Secret); only create/rotate blocked. |
| Secret updated but pod still has the old value | Consumer not annotated for Reloader | `kubectl rollout restart` now; add `reloader.stakater.com/auto: "true"` and commit. |
| Other keys vanished after rotating a multi-key path | Used `put` (replace) instead of `patch` (merge) | Roll back the version (§6); re-do with `bao kv patch`. |
| App broke right after rotating | New value wrong, or the old one is cached without restart | Verify the value at the provider; ensure the pod actually restarted (§3.5). |

Inspection: `kubectl describe externalsecret <name> -n <ns>` · ESO logs
(`kubectl logs -n security deploy/external-secrets --tail=200`) ·
`kubectl get secret <name> -n <ns> -o jsonpath='{.data}' | jq 'keys'`.

## 8. Verification checklist

- [ ] `bao kv get secret/<app>/<name>` shows the new value at a new version.
- [ ] `kubectl get es <name> -n <ns>` → `READY=True / SecretSynced`.
- [ ] The Kubernetes Secret's value changed (decode the key, or watch `resourceVersion`).
- [ ] The consuming pod **restarted** (new pod age) — by Reloader or manual rollout.
- [ ] The credential **works end-to-end** (login / API / backup / S3), not just "pod Ready".
- [ ] (Leak) the old value is **revoked at the provider**, not merely replaced.

## See also

- [ADR-0015 — Secret rotation model](../adr/adr-0015-secret-rotation-model.md) — the *why* (vault-write + Reloader, dynamic creds as endgame).
- [External Secrets runbook](external-secrets.md) — store/generator topology, migration recipes, ESO diagnostics.
- [OpenBao restore](openbao-restore.md) — unseal, raft snapshot restore, lost-contents recovery.
- [cosign transit key rotation](cosign-transit-key-rotation.md) — the *Transit*-key path (different mechanism).
- `external-secrets` skill — in-repo recipes for adding/migrating secrets.
