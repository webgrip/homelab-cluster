## Signing, verification & registry policy

### cosign signing via OpenBao Transit, authorized by Forgejo Actions OIDC, key-only Kyverno verify (no Rekor)
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** Harbor (and GHCR) images are signed **keyed, not keyless**: `cosign sign --tlog-upload=false --key hashivault://cosign-webgrip` calls OpenBao's Transit engine (ECDSA-P256); the private key never leaves OpenBao. Authorization is per-job: the release job enables OIDC, Forgejo mints a token (issuer `https://forgejo.webgrip.dev/api/actions`), OpenBao's JWT auth (`auth/forgejo`, role `cosign-signer`) exchanges it for a sign-only Transit token only when bound claims match (OIDC disabled for fork PRs). The public key is published to a `cosign-webgrip-pub` ConfigMap by a CronJob; Kyverno `image-verify-harbor-audit` verifies against it **key-only** (no rekor block → no tlog lookup; the GHCR keyless policy explicitly sets `rekor.url`). `--tlog-upload=false` avoids leaking digests/timestamps to public Rekor and any internet dependency. Requires a one-time `generate-root` break-glass to enable Transit + the forgejo jwt auth. The sign-attest action signs BY DIGEST (`docker buildx imagetools inspect … --format '{{.Manifest.Digest}}'`) and is generalized to `REGISTRY_USERNAME`/`REGISTRY_TOKEN` so one key signs both registries.
- **Why it matters:** Keyless/Fulcio won't trust a private Authentik; this is the keyed equivalent with per-workflow identity; explains the Harbor-vs-GHCR policy difference.
- **Sources:** batches 3 (copy 5, copy 4), 2 (copy 3, copy 2)

### OpenBao `cosign-signer` JWT role must bind the Forgejo `workflow_dispatch`/branch claim shape
- **Type:** FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** The `auth/forgejo` JWT role originally bound `event_name=release` + `ref=refs/tags/*` (GitHub shape) → OpenBao 400'd the login because the Forgejo flow triggers via `workflow_dispatch` on a branch. Rebind `bound_claims` to `{"repository":"webgrip/infrastructure","event_name":"workflow_dispatch","ref":"refs/heads/*"}` (verified: `aud=openbao-cosign`, `event_name=workflow_dispatch`, `ref=refs/heads/main`). The Forgejo OIDC token request URL may lack a query string, so append `audience=` with `?` vs `&` correctly (malformed URL → default audience → 400).
- **Snippet:** `case "$ACTIONS_ID_TOKEN_REQUEST_URL" in *\?*) sep='&';; *) sep='?';; esac`
- **Sources:** batch 3 (copy 4 — refines copy 5's old `event_name=release`/`refs/tags/*` binding)

### The Harbor SBOM trigger lives only in the Forgejo action; the two cosign actions are NOT symmetric
- **Type:** DECISION + FACT · **Confidence:** HIGH ([VERIFIED])
- **What:** The Harbor-native-SBOM step lives ONLY in `.forgejo/actions/cosign-sign-attest` (gated `if: contains(inputs.registry, 'harbor')`); GHCR has no server-side SBOM API, so the step there is meaningless. The Forgejo/Harbor path signs key-based via OpenBao Transit (`--tlog-upload=false`), while the `.github` mirror pushes to GHCR via keyless OIDC/Fulcio/Rekor — changes must be evaluated per-target, not blindly mirrored. The SBOM step is fail-soft (logs `::warning::` on non-2xx; the cosign attestation already proves provenance + Trivy Operator covers analysis). Tokens passed via a `0600` curl config file (`-K`), not `-u`, to keep the robot token out of the process list (the literal `$`/`+` in `robot$webgrip+ci` survive inside the quoted `user = "..."`). The action installs cosign v2.4.3 + Syft v1.21.0 (pinned to absolute github.com URLs because `data.forgejo.org` 404s), generates CycloneDX+SPDX, signs+attests via Forgejo OIDC → OpenBao Transit, uploads SBOM to in-cluster Dependency-Track (fail-soft). OpenBao role `cosign-signer`, JWT path `/v1/auth/forgejo/login`, audience `openbao-cosign`. DT `http://dependency-track-api-server.security.svc.cluster.local:8080/api/v1/bom`.
- **Sources:** batches 2 (copy 3, copy 2), 3 (copy 4)

### Kyverno policies are Audit-only; Harbor "Deployment security" stays OFF
- **Type:** DECISION · **Confidence:** HIGH (Audit [VERIFIED]; Harbor-off [ASSERTED] single-source)
- **What:** Kyverno policies `kubernetes/apps/kyverno/policies/app/{image-verify-audit,image-attestations-audit,image-verify-harbor-audit}.yaml` are all `validationFailureAction: Audit` — flip Audit→Enforce only once a release is green with zero false positives (explicitly NOT done). Leave Harbor project Deployment-security OFF: Harbor's cosign check only verifies a signature exists (not against your key) and blocks pulls of unsigned artifacts including the buildx `:cache` tag (breaking cache-from); "Prevent vulnerable images" can make a running image unpullable on a new CVE. Enforce only at Kyverno admission.
- **Sources:** batches 3 (copy 4, copy 5)

---
