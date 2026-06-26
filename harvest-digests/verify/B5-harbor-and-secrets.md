## Harbor operations & supply-chain

### Harbor's native SBOM column is gated by `sbom:create` (NOT `scan:create`), fed only by Harbor's own scanner
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED] from Harbor source at the deployed tag)
- **What:** Triggering Harbor's native SBOM accessory via `POST .../artifacts/{ref}/scan {"scan_type":"sbom"}` is authorized by RBAC resource `sbom` + action `create` (in `scan.go`: `if scanType == ScanTypeSbom { res = ResourceSBOM }`) — a DIFFERENT resource from the vuln scan's `scan:create`. Granting `scan:create` (the intuitive guess) does NOT fix the 403. The "SBOM" UI column is populated EXCLUSIVELY by Harbor's own native (Trivy-backed) `.sbom` accessory — a `cosign attest --type cyclonedx` produces a `.att` accessory shown under "Signed" but never in the SBOM column (different media types: attestation → Kyverno + DT; `.sbom` → Harbor UI/policies). Needs Harbor ≥2.11 + an SBOM-capable scanner. The CI robot lacked the grant → release SBOM step 403'd (fixed least-privilege, commit 9938e09, live-verified). Harbor's auto-scan-on-push also scans the `sha256-<digest>` signature/attestation accessory rows (~5 MiB, "Signed") emitting spurious warnings — expected noise; the rows that matter are full image manifests.
- **Snippet:** RBAC `{resource:sbom, action:create}`; access list `{"resource":"sbom","action":"create"}` alongside repository push/pull.
- **Sources:** batches 2 (copy 2, copy 3), 3 (copy 4)

### The robot provisioner set permissions only on FIRST creation — fix = convergence PUT reusing the stored full name
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED] by code path + live job behavior)
- **What:** `robot$webgrip+ci` (project-level, id=2) is created/converged by `configure.sh` in `harbor-proxy-config.configmap.yaml` (CronJob `harbor-proxy-config`, ns `harbor`, `17 * * * *`). `ensure_webgrip_robot()` POSTed permissions only when the robot didn't exist; for an existing robot it merely PATCHed the secret, so editing the create-body's permissions array is a no-op against the live robot. Fix: a convergence `PUT /robots/{id}` resending the desired spec every run. Caveats: `UpdateRobot` rejects a changed name/level; `GET /robots/{id}` returns the full name `robot$webgrip+ci` (create used bare `ci`) — the PUT must reuse the exact stored name. `GET /robots` lists only SYSTEM robots — find a project robot via `q=Level%3Dproject%2CProjectID%3D<id>`. There is NO Harbor robot/project/scanner IaC in `webgrip/infrastructure` — only this homelab-cluster file touches Harbor RBAC.
- **Why it matters:** Classic idempotency footgun: "I updated the IaC" ≠ "the running resource changed."
- **Snippet:** `_rname="$(hc GET "/robots/$_rid" | jq -r '.name')"; hc PUT "/robots/$_rid" "{\"name\":\"$_rname\",...,\"permissions\":$_perms}"`
- **Sources:** batches 2 (copy 2), 3 (copy 4)

### Talos registry mirror is a silent no-op unless nodes can DNS-resolve the Harbor hostname
- **Type:** GOTCHA · **Confidence:** HIGH ([VERIFIED]; `extraHostEntries` confirmed in `talos/patches/global/machine-network.yaml`)
- **What:** The mirror endpoints point at `https://harbor.${secretDomain}/v2/…`, but nodes resolve via `1.1.1.1/1.0.0.1` and `harbor.webgrip.dev` is LAN-only → containerd got `dial tcp: lookup harbor.webgrip.dev on 127.0.0.53:53: no such host` and silently fell back to upstream on every pull. The fail-open drill passed trivially (fallback was the only working path) and all proxy projects stayed empty. Image pulls use **node DNS** (kubelet/containerd), not pod/cluster DNS. Fix: a static Talos `extraHostEntries` mapping `harbor.${secretDomain}` → `10.0.0.27` (envoy-internal LAN VIP).
- **Why it matters:** A mirror can be fully configured and verified-present on every node yet route nothing, with zero errors. Always verify a node can resolve the mirror host before declaring success.
- **Snippet:** `mise exec -- talosctl -n <ip> read /etc/hosts | grep harbor` → `10.0.0.27 harbor.webgrip.dev`
- **Sources:** batch 1 (copy 11)

### Route images via transparent Talos mirror (fail-open); apply with no drain/reboot
- **Type:** DECISION + PROCEDURE · **Confidence:** HIGH ([VERIFIED]; `overridePath: true` confirmed)
- **What:** Per-registry `machine.registries.mirrors` with `overridePath: true`, composed with Spegel `prependExisting: true` (Spegel peers → Harbor proxy → upstream). Manifests keep upstream refs. `skipFallback` default `false` → Harbor down ⇒ fall back to upstream (fail-open), never ImagePullBackOff. Six upstreams: `docker.io→dockerhub, ghcr.io→ghcr, quay.io→quay, mirror.gcr.io→gcrmirror, registry.k8s.io→k8s, code.forgejo.org→forgejo`. `overridePath: true` is mandatory or containerd appends its own `/v2/`. `machine.registries.mirrors` + `extraHostEntries` are containerd/`/etc/hosts` reloads — no reboot/drain: `task talos:apply-node IP=… MODE=no-reboot` (NOT `apply-node-safe`, which drains; avoiding the drain matters because draining soyo triggers Longhorn/CNPG incidents); one node at a time, control-plane last. Inspect via `talosctl get mc v1alpha1` (NOT `registriesconfig`, which isn't a registered resource → false "not applied").
- **Sources:** batch 1 (copy 11, copy 16)

### Harbor 2.15 proxy returns the FULL upstream tag list → Renovate works; `registryAliases` keys on host only
- **Type:** FACT + GOTCHA · **Confidence:** HIGH ([VERIFIED] — app-template 15/15 tags identical to ghcr.io on a cold repo; matches MEMORY)
- **What:** The old "Harbor only returns cached tags, breaks Renovate" limitation is gone in 2.15 — a proxy-cache `tags/list` proxies the complete upstream list even for uncached repos. `registryAliases` cannot disambiguate multiple upstreams behind one Harbor host (`/ghcr`, `/quay`) because it keys on the host alone (and is applied at extraction, before packageRules, so it can't be set in a packageRule). The working lever for Harbor-proxied OCI charts is to widen the `ghcr.io` packageRules to also match the Harbor path.
- **Snippet:** `matchPackageNames: ["/^ghcr\\.io\\//", "/^harbor\\.webgrip\\.dev\\//"]`
- **Sources:** batch 1 (copy 11)

### Charts go through Harbor by URL-rewrite; only non-bootstrap OCI; NOT fail-open
- **Type:** DECISION · **Confidence:** HIGH ([VERIFIED] — rewritten OCIRepositories Ready)
- **What:** Flux source-controller fetches charts directly (no containerd), so the Talos mirror does nothing for charts — the only lever is the OCIRepository `url:`. Rewrote 25 non-bootstrap OCI chart sources `oci://ghcr.io/… → oci://harbor.webgrip.dev/ghcr/…`. Unlike images this is NOT fail-open: while Harbor is down, affected apps can't install/upgrade (running releases keep running). Keep upstream (bootstrap/reach-Harbor path): flux-operator, flux-instance, cilium, coredns, cert-manager, external-secrets, kyverno, k8s-gateway, envoy-gateway, spegel, trust-manager. HTTP HelmRepository sources stay upstream (Harbor's proxy is OCI-only; ChartMuseum removed in 2.8). OCIRepository bumps come from a `custom.regex` manager in the shared preset; pinned `@sha256:` digests stay valid through the proxy (content-addressable).
- **Sources:** batch 1 (copy 11)

### A manifest GET through the proxy doesn't register/persist; only a full pull does — warm via skopeo Job, not respawn
- **Type:** FACT + PROCEDURE · **Confidence:** HIGH (mechanism [VERIFIED]; full warm run pending)
- **What:** Fetching only the manifest (`crane manifest`, a bare `/v2/.../manifests/<ref>` GET) is proxied but not stored as a catalog artifact, doesn't cache blobs, and doesn't enable Trivy scanning — killed the "warm just the manifests" idea. To get an image into Harbor (registered, cached, scannable) you must do a real pull. A digest-pinned running image is byte-identical to what Harbor would serve (content-addressable + Kyverno verify), so "image in Harbor == image running" is guaranteed by the digest pin WITHOUT forcing pulls through Harbor; forcing all running images through Harbor only adds cache-of-record + Trivy coverage at real Garage cost — not worth a risky mass-respawn ("batched rollouts → storage collapse"). To warm without restart: an in-cluster skopeo Job enumerating running images, `skopeo copy docker://<harborref> dir:/scratch/_w` one at a time (on worker-1, emptyDir scratch, digest-pinned skopeo base). skopeo rejects refs with BOTH tag and digest (`sed -E 's#:[^/@]*@sha256:#@sha256:#'`); the image-ref→proxy-path mapping must normalize bare/implicit docker.io names (first segment is a registry only if it contains `.`/`:` or is `localhost`; `library/` prepended for single-segment).
- **Sources:** batch 1 (copy 11)

### Harbor proxy-cache provisioner originally skipped credential-less (anonymous) registries; GC + retention + scan-on-push
- **Type:** GOTCHA + PROCEDURE · **Confidence:** HIGH ([VERIFIED] — code fix; flux-local passed)
- **What:** `ensure_registry()` did `return 0` (skipped creation) when no user/pass was supplied — fine for dockerhub/ghcr (creds lift rate limits) but it blocked anonymous upstreams (quay/gcrmirror/k8s/forgejo). Fixed to always create the endpoint, including the credential block only when both user and pass are present. Proxy projects: `dockerhub→docker.io, ghcr→ghcr.io, quay→quay.io, gcrmirror→mirror.gcr.io, k8s→registry.k8s.io, forgejo→code.forgejo.org` (generic docker-registry, public, `storage_limit: -1`). GC + retention are complementary: retention (`POST /retentions`, template `latestPushedK`, exclude tag `cache`) untags old versions; GC (`POST/PUT /system/gc/schedule`, `delete_untagged:true`, cron `0 30 3 * * 0`) reclaims bytes incl. orphaned `:cache` manifests; per-project `auto_scan`/`auto_sbom_generation` (≥2.11) via `PUT /projects/{id}`. Shell `$` doubled to `$$` for Flux post-build substitution (so an un-doubled `${var}` referencing an undefined var doesn't get blanked); build jq programs by interpolating doubled shell vars into the program string, NOT `jq --arg` (a jq `$var` looks like a Flux `$VAR`). The sibling `forgejo-actions-secrets` ks deliberately has NO `postBuild.substituteFrom`, so its script uses single `$`. Never `kubectl apply` the raw git file (`$$` would land live; reproduce Flux's render with `sed 's/\$\$/\$/g'`, syntax-check `sh -n`).
- **Sources:** batches 1 (copy 11), 2 (copy 2), 3 (copy 4)

### Harbor coordinates, version, private project & break-glass
- **Type:** REFERENCE · **Confidence:** HIGH ([VERIFIED])
- **What:** Harbor `goharbor/harbor-core:v2.15.1` (Helm chart 1.19.1). OCI registry `harbor.webgrip.dev`, LAN-only (HTTPRoute on envoy-internal `10.0.0.27`, split-DNS, valid TLS). In-cluster plain HTTP at `harbor.harbor.svc.cluster.local:80` (nginx front-end serves `/v2/` + `/api/`; forgejo→harbor:80 already open — sidesteps TLS/DNS/`${SECRET_DOMAIN}`). Private project `webgrip` (pushed images invisible to anon/non-member views) — OIDC (`oidc_admin_group: harbor-admins`); local break-glass `admin` (NOT `harbor-admin`, the secret name), password from the `harbor-admin` secret, login at `/account/sign-in`. Robot token in OpenBao `secret/harbor/robot-webgrip`. Storage growth via `harbor_statistics_total_storage_consumption` / `harbor_project_quota_usage_byte` (Garage's own capacity is NOT scraped — external `10.0.0.110:3900`, confirm headroom out-of-band). Verify an RBAC requirement credential-free by reading Harbor source at the deployed tag (`src/server/v2.0/handler/*.go`, `src/common/rbac/const.go`).
- **Sources:** batches 1 (copy 11, copy 16), 3 (copy 4, copy 7), 2 (copy 2)

---

## Provisioning org secrets & OpenBao access

### Provision Forgejo org Actions secrets via OpenBao + a CronJob; reserved prefixes
- **Type:** PROCEDURE + GOTCHA · **Confidence:** HIGH ([VERIFIED])
- **What:** Add an ExternalSecret reading e.g. `secret/github/ci-pat`; add env vars + `put_secret` calls to `forgejo-actions-secrets.cronjob.yaml`. The Forgejo Actions secrets API is **write-only** — verify by the cronjob log (`created org secret webgrip/GHCR_TOKEN`), not by reading back; the provisioner PUTs every tick (create-or-update). No ESO push-provider for Forgejo Actions secrets exists. The org API **rejects** secret/variable names beginning with `FORGEJO_`, `GITHUB_`, or `GITEA_` (secret PUT 400; var POST/PUT 400/404) — use a `WEBGRIP_` prefix (token `WEBGRIP_CI_TOKEN`, URL `WEBGRIP_FORGEJO_URL`/`WEBGRIP_CI_BOT_NAME`). `GHCR_*`, `CODEBERG_TOKEN`, `HARBOR_ROBOT_*`, `DT_API_KEY` are fine. (`secrets.FORGEJO_TOKEN` inside a workflow is the built-in per-job token, distinct from the org bot token.) Trigger now: `kubectl -n forgejo create job fas-manual --from=cronjob/forgejo-actions-secrets`.
- **Sources:** batches 3 (copy 4, copy 5), 2 (copy 8)

### Write to OpenBao as admin via OIDC (root token is revoked)
- **Type:** PROCEDURE · **Confidence:** HIGH ([VERIFIED])
- **What:** OpenBao revokes the initial root token and persists only the unseal key (Secret `openbao-keys`). Admin is OIDC via Authentik: the `admins` policy (path `"*"`) is granted to identity group `openbao-admins` ← Authentik `homelab-admins`. `kubectl exec` into the pod gives a non-admin token → 403 on `sys/internal/ui/mounts`. Correct: OpenBao Web UI OIDC login or CLI `bao login -method=oidc role=default`, then `bao kv put`. Break-glass: `bao operator generate-root` using the unseal key. Mount `secret` (KV v2); ESO policy grants `secret/data/*`. `VAULT_ADDR=http://openbao.security.svc.cluster.local:8200` (in-cluster) or `https://openbao.webgrip.dev` (CLI).
- **Snippet:** `bao login -method=oidc role=default; bao kv put secret/github/ci-pat username='<gh-user>' token='<REDACTED>'`
- **Sources:** batch 3 (copy 4)

---
