
Thread Digest: Harbor SBOM column not populated by cosign attestation
One-line summary: Why Harbor's "SBOM" column stays empty despite the CI pipeline producing an SBOM, and adding a CI step to trigger Harbor's native SBOM generation.
Approx date / status: 2026-06-26 — done (code change made, not yet committed or run in CI).

Items
[FACT] Harbor's "SBOM" column is fed only by Harbor's own scanner, not by pushed cosign attestations
Type: FACT
Verification: [ASSERTED]
What: A cosign attest --type cyclonedx produces a signed in-toto attestation accessory tagged sha256-<digest>.att. Harbor displays this as a nested accessory under the "Signed" badge but does NOT surface it in the "SBOM" column. That column is populated exclusively by Harbor's own native (scanner/Trivy-backed) SBOM generator, which produces a separate .sbom accessory. The two artifacts have different OCI media types and serve different consumers (attestation → Kyverno admission + Dependency-Track; .sbom → Harbor UI/API + Harbor SBOM policies).
Why it matters: Prevents the false conclusion that "my pipeline makes an SBOM, so Harbor's column should show it." They are independent; pushing a cosign CycloneDX attestation will never light up Harbor's SBOM column.
Snippet: none
Suggested home: doc
[FACT] cosign sig/attestation accessories appear as separate ~5MiB rows and trigger spurious scan/SBOM warnings in Harbor
Type: FACT
Verification: [ASSERTED]
What: In Harbor's Artifacts view, the sha256-<imagedigest> tagged rows (~5.43 MiB, shown as ❌ Signed, with "View Log" ⚠ on both Vulnerabilities and SBOM columns) are the cosign signature/attestation accessories for the real image. Harbor's auto-scan-on-push tries to scan/SBOM these signature blobs and emits warnings because they aren't runnable images. This is expected noise — the rows that matter are the full image manifests (e.g. 537 MiB).
Why it matters: Avoids misdiagnosing the warning rows as the actual image's SBOM/scan failing.
Snippet: none
Suggested home: doc
[REFERENCE] Harbor native SBOM-generation API
Type: REFERENCE
Verification: [VERIFIED] (endpoint + schema confirmed against Harbor swagger.yaml; not yet exercised against the live Harbor)
What: Trigger Harbor-native SBOM generation for an artifact via the scan endpoint with a scan_type body. Requires Harbor ≥ 2.11 and an SBOM-capable scanner (Trivy). reference may be a digest. Returns 202 Accepted. The repository path segment must be URL-encoded (/ → %2F); single-segment names are unaffected. This API call works regardless of the project's "Automatically generate SBOM on push" toggle, which is why it's more robust than relying on that toggle.
Why it matters: Lets CI deterministically populate Harbor's SBOM column in-code rather than depending on an out-of-band per-project UI setting.
Snippet:

POST https://<registry>/api/v2.0/projects/{project}/repositories/{repo}/artifacts/{reference}/scan
Content-Type: application/json
{"scan_type":"sbom"}
ScanType definition (Harbor api/v2.0/swagger.yaml): scan_type is a string with enum: [ vulnerability, sbom ].
Suggested home: doc
[PROCEDURE] How to fetch a truncated Harbor swagger definition via gh
Type: PROCEDURE
Verification: [VERIFIED]
What: WebFetch truncated the large swagger.yaml; pulling it via the GitHub contents API (base64-decoded) and grepping worked to extract the exact ScanType schema.
Why it matters: Reusable technique when a raw file is too big for WebFetch.
Snippet:

gh api repos/goharbor/harbor/contents/api/v2.0/swagger.yaml --jq '.content' | base64 -d | grep -n -A15 "ScanType:"
Suggested home: doc
[DECISION] Harbor SBOM trigger added only to the Forgejo action, not the .github mirror
Type: DECISION
Verification: [VERIFIED] (confirmed .github action targets GHCR by reading it)
What: The new Harbor SBOM-generation step was added ONLY to .forgejo/actions/cosign-sign-attest/action.yml. The .github/actions/cosign-sign-attest/action.yml mirror pushes to GHCR via keyless OIDC/Fulcio; GHCR has no server-side SBOM-generation API to trigger, so adding the step there would be meaningless. This deliberately deviates from the original "update both mirrors" framing.
Why it matters: The two cosign-sign-attest actions are NOT symmetric — Forgejo→Harbor (OpenBao Transit key signing) vs GitHub→GHCR (keyless Fulcio/Rekor). Changes must be evaluated per-target, not blindly mirrored.
Snippet: none
Suggested home: CLAUDE.md
[DECISION] Harbor SBOM step is fail-soft and keeps the robot token out of argv
Type: DECISION
Verification: [VERIFIED] (bash -n passed; URL-construction smoke-tested)
What: The step never fails the release on a non-2xx (logs ::warning::), matching the existing Dependency-Track upload's philosophy — the signed cosign attestation already proves provenance, so the SBOM column is convenience-only. Credentials are passed via a 0600 curl config file (-K), not -u, to keep the robot token out of the process list. The robot username carries a literal $/+ (robot$webgrip+ci) which survives verbatim inside the quoted curl-config user = "..." value.
Why it matters: Consistent with the repo's supply-chain hygiene (tokens never in argv) and resilience (cluster-side Trivy Operator + Harbor scanner cover analysis even if this call fails).
Snippet: (the step as added to .forgejo/actions/cosign-sign-attest/action.yml)

digest="${IMAGE##*@}"
repo_path="${IMAGE%@*}"; repo_path="${repo_path#*/}"
project="${repo_path%%/*}"; repository="${repo_path#*/}"
repo_enc="${repository//\//%2F}"
url="https://${REGISTRY}/api/v2.0/projects/${project}/repositories/${repo_enc}/artifacts/${digest}/scan"
umask 077
cfg="$(mktemp)"; trap 'rm -f "$cfg"' EXIT
printf 'user = "%s:%s"\n' "$HARBOR_ROBOT_USER" "$HARBOR_ROBOT_TOKEN" > "$cfg"
code="$(curl -sS -K "$cfg" -o /tmp/sbom-gen.json -w '%{http_code}' \
  -X POST "$url" -H 'Content-Type: application/json' \
  --data '{"scan_type":"sbom"}' || echo 000)"
case "$code" in
  200|202) echo "Harbor SBOM generation queued for ${project}/${repository}@${digest}" ;;
  *) echo "::warning::Harbor SBOM generation request returned HTTP ${code} (non-fatal): $(cat /tmp/sbom-gen.json 2>/dev/null)" ;;
esac
Suggested home: existing-skill
[GOTCHA] Harbor robot needs an explicit SBOM-generation permission
Type: GOTCHA
Verification: [OPEN]
What: The robot robot$webgrip+ci likely needs the SBOM generation permission (Harbor ≥ 2.11) for the scan API with scan_type=sbom to succeed. Without it, the fail-soft step logs ::warning:: ... HTTP 403 in the Sign & Attest job and the SBOM column stays empty. Grant under Projects → webgrip → Robot Accounts → edit → enable SBOM (generate), or on the system robot depending on scope.
Why it matters: This is the most likely reason the new step won't populate the column; it's an out-of-band Harbor config the code can't set.
Snippet: none
Suggested home: doc
[FACT] Harbor project config is not in this repo's IaC
Type: FACT
Verification: [VERIFIED] (grep for "harbor" outside CI returned only .releaserc.js)
What: There is no Harbor project IaC (project settings, scanner config, "auto-generate SBOM on push" toggle, robot permissions) in the webgrip/infrastructure repo. Those are managed elsewhere (homelab-cluster repo or manually in the Harbor UI).
Why it matters: Explains why the in-CI API call was preferred over the project toggle (the toggle isn't reproducible/in-code here), and where to look for Harbor-side config.
Snippet: none
Suggested home: CLAUDE.md
[REFERENCE] Existing supply-chain pipeline shape (Forgejo → Harbor)
Type: REFERENCE
Verification: [VERIFIED] (read from source)
What: .forgejo/workflows/on_release_published.yml parses tag <image>-v<version>, builds/pushes to harbor.webgrip.dev/webgrip/<image> via reusable webgrip/workflows/.forgejo/workflows/docker-build-and-push-harbor-fast.yml@main (amd64-only, runs-on docker), then release-sign-and-attest runs .forgejo/actions/cosign-sign-attest. That action: installs cosign v2.4.3 + Syft v1.21.0 (pinned to https://github.com/... absolute URLs because Forgejo's default action host data.forgejo.org 404s), resolves digest, generates CycloneDX+SPDX SBOM with Syft, signs+attests via Forgejo OIDC → OpenBao Transit (hashivault://cosign-webgrip, --tlog-upload=false), and uploads SBOM to in-cluster Dependency-Track (fail-soft).
Why it matters: Context for any future change to the signing/SBOM path; documents the version pins and the OpenBao-Transit (not Fulcio) signing model.
Snippet: Key paths: .forgejo/actions/cosign-sign-attest/action.yml, .forgejo/workflows/on_release_published.yml. OpenBao: VAULT_ADDR=http://openbao.security.svc.cluster.local:8200, role cosign-signer, JWT auth path /v1/auth/forgejo/login, audience openbao-cosign. Dependency-Track: http://dependency-track-api-server.security.svc.cluster.local:8080/api/v1/bom.
Suggested home: doc
[FACT] cosign signing here is key-based (OpenBao Transit), so no Rekor tlog and Kyverno verifies key-only
Type: FACT
Verification: [VERIFIED] (read from action comments/code)
What: The Forgejo/Harbor path signs with --tlog-upload=false using a static OpenBao Transit key that never leaves OpenBao. Verification is key-only: the Kyverno image-verify-harbor-audit policy has no rekor block (unlike the GHCR keyless policy), so it never looks up a transparency-log entry. This keeps signing fully in-cluster with no internet dependency and avoids publishing image digests/timestamps to the public sigstore tlog.
Why it matters: Explains the --tlog-upload=false choice and the difference between the Harbor (key-based) and GHCR (keyless Fulcio/Rekor) verification policies.
Snippet: cosign sign --yes --tlog-upload=false --key "hashivault://cosign-webgrip" "$IMAGE"
Suggested home: doc
Open questions / unfinished
Whether the robot robot$webgrip+ci actually has the Harbor SBOM-generation permission (will show as HTTP 403 warning if not). [OPEN]
Whether the live Harbor is ≥ 2.11 with an SBOM-capable scanner configured. [OPEN]
Whether Harbor's API is reachable over https://harbor.webgrip.dev from the in-cluster runner with a trusted cert (curl will fail-soft if not). [OPEN]
The change is not yet committed or exercised in CI; verification is pending the next techdocs-builder release bump. [OPEN]
Explicit preferences/feedback I gave
Chose "Add API call to CI" over flipping the Harbor project toggle or leaving the column empty — preferring in-repo, deterministic, reproducible config over out-of-band UI settings, consistent with the repo's GitOps/hardening approach.
Do not commit or push unless explicitly asked (I was asked whether to commit, and waited).
