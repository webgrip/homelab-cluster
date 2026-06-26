
Thread Digest: Harbor native-SBOM 403 — CI robot missing sbom:create
One-line summary: A release pipeline's Harbor "generate native SBOM" step returned HTTP 403; root cause was the Harbor CI robot account lacking the sbom:create RBAC permission, fixed (and live-verified) by adding it to the robot provisioner in the homelab-cluster repo.
Approx date / status: 2026-06-26 — done.

Items
[FACT] Harbor SBOM generation requires the dedicated sbom:create RBAC permission, not scan:create
Type: FACT
Verification: [VERIFIED] (read from Harbor source at the exact deployed tag v2.15.1)
What: Triggering Harbor's native SBOM accessory via POST /api/v2.0/projects/{project}/repositories/{repo}/artifacts/{ref}/scan with body {"scan_type":"sbom"} is authorized by RBAC resource sbom + action create. In src/server/v2.0/handler/scan.go: if scanType == v1.ScanTypeSbom { res = rbac.ResourceSBOM } then RequireProjectAccess(ctx, projectName, rbac.ActionCreate, res). In src/common/rbac/const.go: ResourceSBOM = Resource("sbom"), and {Resource: ResourceSBOM, Action: ActionCreate} is in the ScopeProject policy map (so project-level robots can be granted it). A vulnerability scan (scan_type absent/vulnerability) uses scan:create instead — a different resource.
Why it matters: Granting scan:create (the intuitive guess) would NOT fix the 403; SBOM is gated by its own resource. This is the crux of the whole fix.
Snippet: https://raw.githubusercontent.com/goharbor/harbor/v2.15.1/src/common/rbac/const.go and .../src/server/v2.0/handler/scan.go
Suggested home: doc
[FACT] The webgrip Harbor CI robot is provisioned as code in an idempotent ConfigMap shell script
Type: FACT
Verification: [VERIFIED]
What: The robot robot$webgrip+ci (project-level, id=2) is created/converged by configure.sh inside kubernetes/apps/harbor/harbor/app/harbor-proxy-config.configmap.yaml in the homelab-cluster repo (/home/ryan/projects/webgrip/homelab-cluster). It runs via CronJob harbor-proxy-config in namespace harbor (schedule 17 * * * *, hourly). Same script also ensures pull-through proxy registries, projects, GC schedule, retention, and project scan/SBOM-on-push settings. Harbor project/robot settings are otherwise NOT in any other IaC.
Why it matters: Harbor-side permission/robot changes belong in this file, not in the infrastructure repo that consumes the robot.
Snippet: kubernetes/apps/harbor/harbor/app/harbor-proxy-config.configmap.yaml → function ensure_webgrip_robot()
Suggested home: memory
[GOTCHA] The robot provisioner only set permissions on FIRST creation — existing robots silently kept stale perms
Type: GOTCHA
Verification: [VERIFIED] (confirmed by code path + live job behavior)
What: ensure_webgrip_robot() POSTed permissions only when the robot didn't yet exist; for an existing robot it merely PATCHed the secret. So editing the create-body's permissions array alone is a no-op against the live robot. Fix: add a convergence PUT /robots/{id} that resends the desired spec (with the new permissions) every run. Harbor's UpdateRobot rejects a changed name or level ("cannot update the level or name of robot"), and GET /robots/{id} returns the full name robot$webgrip+ci (while create used bare ci) — so the PUT must reuse the exact stored name fetched from GET.
Why it matters: Classic idempotency footgun: "I updated the IaC" ≠ "the running resource changed." Any add-a-permission change to an existing Harbor robot needs the PUT convergence path.
Snippet:

_perms='[{"kind":"project","namespace":"webgrip","access":[{"resource":"repository","action":"push"},{"resource":"repository","action":"pull"},{"resource":"sbom","action":"create"}]}]'
# ...resolve _rid...
_rname="$(hc GET "/robots/$_rid" 2>/dev/null | jq -r '.name // empty' 2>/dev/null)"
_upd="{\"name\":\"$_rname\",\"description\":\"webgrip CI push/pull (managed)\",\"duration\":-1,\"level\":\"project\",\"disable\":false,\"permissions\":$_perms}"
hc PUT "/robots/$_rid" "$_upd"
Suggested home: doc
[GOTCHA] GET /api/v2.0/robots lists only SYSTEM robots; project robots need a query filter
Type: GOTCHA
Verification: [VERIFIED] (per code comment + working script)
What: To find a project-level robot via the Harbor API you must query GET /robots?q=Level%3Dproject%2CProjectID%3D<project_id> (URL-encoded Level=project,ProjectID=<id>). A bare GET /robots returns system robots only and will appear to "not find" the project robot.
Why it matters: Easy to think the robot is missing when it's just filtered out.
Snippet: _q="Level%3Dproject%2CProjectID%3D$_pid"; hc GET "/robots?q=$_q&page_size=100"
Suggested home: doc
[GOTCHA] This ConfigMap goes through Flux post-build substitution ($$→$); never kubectl apply the raw git file
Type: GOTCHA
Verification: [VERIFIED] (compared git file vs live ConfigMap)
What: The git source doubles every shell $ to $$ so Flux's post-build substitution leaves the script intact; Flux restores $$→$ at apply time. The live ConfigMap has single $. This file has no real ${VAR} substitution tokens — the only ${...} is the escaped $${WEBGRIP_CI_TOKEN} (a runtime shell env var, not a Flux var). Consequence: applying the raw git file with kubectl apply would push broken $$ into the live ConfigMap. To locally reproduce exactly what Flux renders, run sed 's/\$\$/\$/g' on the file (the only transform). To syntax-check the runtime script: undouble then sh -n.
Why it matters: Prevents corrupting a Flux-managed ConfigMap during manual testing; also tells you how to validate the script offline.
Snippet: sed 's/\$\$/\$/g' harbor-proxy-config.configmap.yaml > rendered.yaml ; offline check: undouble $$→$, then sh -n
Suggested home: doc
[GOTCHA] Inside this ConfigMap, build JSON via shell-string interpolation into the jq program — don't use jq --arg/$var
Type: GOTCHA
Verification: [ASSERTED] (reasoned from Flux behavior + matched existing script style; not independently tested in isolation)
What: A jq program containing a jq variable like $perms would be mangled by Flux post-build substitution (it looks like $VAR). The existing script avoids jq --arg/--argjson entirely and instead interpolates shell vars (doubled $$_perms) directly into the jq program string, e.g. jq -c ".permissions = $$_perms". New code in this file must follow that pattern.
Why it matters: Keeps additions consistent and avoids a subtle Flux-substitution breakage.
Snippet: prefer jq -c ".permissions = $$_perms" over jq -c --argjson p "$$_perms" '.permissions=$p'
Suggested home: doc
[FACT] Harbor's "SBOM column" is a separate accessory from the cosign SBOM attestation
Type: FACT
Verification: [ASSERTED] (stated in code comments; consistent with observed behavior)
What: The pipeline's cosign attest ... --type cyclonedx produces a .att accessory consumed by Kyverno admission + Dependency-Track. It does NOT populate Harbor's own "SBOM" UI column, which is fed only by Harbor's native scanner-backed SBOM generator (a separate .sbom accessory). The native SBOM is requested via the POST .../scan {"scan_type":"sbom"} call. The project already had auto_sbom_generation (sbom-on-push) enabled, so Harbor likely also generates it automatically at push time — making the explicit POST a belt-and-suspenders rather than the sole path.
Why it matters: Explains why a "successful" supply-chain run can still leave Harbor's SBOM column empty, and that the 403 only affected convenience visibility (signatures/attestations/DT upload were unaffected).
Snippet: none
Suggested home: doc
[FACT] HTTP 403 vs 401 distinction was the key diagnostic
Type: FACT
Verification: [VERIFIED]
What: Harbor returning 403 {"errors":[{"code":"FORBIDDEN","message":"forbidden"}]} means the robot authenticated successfully but is not authorized (missing permission) — as opposed to 401 (bad/absent credentials). This immediately points at RBAC/permissions, not login/secret problems.
Why it matters: Narrows the search from "wrong token" to "missing permission" in one step.
Snippet: none
Suggested home: doc
[REFERENCE] Deployed Harbor version + how to read it
Type: REFERENCE
Verification: [VERIFIED]
What: Harbor is goharbor/harbor-core:v2.15.1 (Helm chart 1.19.1). The sbom RBAC resource and auto_sbom_generation need Harbor ≥ 2.11 (chart ≥ 1.15 — chart→app mapping is [ASSERTED]). The authenticated GET /api/v2.0/systeminfo returned harbor_version: null, so read the version from the image tag instead.
Why it matters: Confirms feature availability and gives a credential-free way to get the version.
Snippet: kubectl -n harbor get deploy harbor-core -o jsonpath='{.spec.template.spec.containers[0].image}'
Suggested home: memory
[REFERENCE] Harbor host reachability from the dev sandbox
Type: REFERENCE
Verification: [VERIFIED]
What: https://harbor.webgrip.dev resolves and responds from the sandbox (auth_mode: oidc_auth, provider authentik). il.webgrip.dev does NOT resolve from the sandbox (it's the in-cluster/LAN name). kubectl is cluster-admin (current-context: admin@kubernetes), namespace harbor exists.
Why it matters: Tells you which endpoints/tools are usable for live verification.
Snippet: curl -fsS "https://harbor.webgrip.dev/api/v2.0/systeminfo" | jq '{harbor_version, auth_mode}'
Suggested home: memory
[PROCEDURE] Verify a Harbor RBAC requirement from source at the exact deployed tag (credential-free)
Type: PROCEDURE
Verification: [VERIFIED]
What: When you can't (or shouldn't) hit the live API with admin creds, confirm what permission an endpoint enforces by fetching Harbor's source at the deployed version tag and reading the handler + RBAC const files. Resource/action enforcement lives in src/server/v2.0/handler/*.go; resource/action constants and the per-scope policy map live in src/common/rbac/const.go.
Why it matters: Authoritative, non-mutating verification that survives the auto-mode classifier blocking credential use.
Snippet: WebFetch https://raw.githubusercontent.com/goharbor/harbor/v<TAG>/src/common/rbac/const.go and .../src/server/v2.0/handler/scan.go
Suggested home: new-skill
[PROCEDURE] Apply + live-verify a homelab-cluster Flux change immediately (don't wait for the hourly reconcile)
Type: PROCEDURE
Verification: [VERIFIED]
What: After committing+pushing to main, Flux reconciles within ~minutes. Confirm Flux applied your commit via the Kustomization status (Applied revision: refs/heads/main@sha1:<your-sha>). To exercise a CronJob's script right now, spawn a one-off job from it and read its logs; clean up the manual job afterward. The ConfigMap is owned by field manager kustomize-controller.
Why it matters: Turns "should work" into live-verified without waiting an hour or breaking Flux ownership.
Snippet:

kubectl get kustomization -A | grep harbor   # check "Applied revision: ...@sha1:<sha>"
kubectl -n harbor create job --from=cronjob/harbor-proxy-config harbor-proxy-config-sbomverify
kubectl -n harbor wait --for=condition=complete job/harbor-proxy-config-sbomverify --timeout=180s
kubectl -n harbor logs job/harbor-proxy-config-sbomverify | grep -iE 'robot|sbom|converged|WARN'
kubectl -n harbor delete job harbor-proxy-config-sbomverify
Suggested home: new-skill
[FACT] hc curl wrapper uses curl -fsS, so a logged success branch IS proof of HTTP 2xx
Type: FACT
Verification: [VERIFIED]
What: In configure.sh, the hc() API wrapper uses curl -fsS, which exits non-zero on any HTTP ≥ 400. Therefore the job logging webgrip robot (id=2) access converged (...) (the if _out="$(hc PUT ...)" success branch, with no WARN) is direct evidence that Harbor accepted the PUT with 2xx — i.e., the sbom:create grant was accepted live.
Why it matters: Lets you trust the job's own log lines as verification without separately querying the API.
Snippet: hc() { curl -fsS -u "$AUTH" -X "$_m" ... }
Suggested home: doc
[DECISION] Grant only sbom:create (least privilege), and fix it in homelab-cluster — not the pipeline repo
Type: DECISION
Verification: [VERIFIED] (implemented + verified)
What: Added only {resource: sbom, action: create} (not sbom:stop/sbom:read, not scan:create) — the single verb the endpoint needs. The infrastructure repo's pipeline step (.forgejo/actions/cosign-sign-attest/action.yml) was left unchanged: it is correctly fail-soft (warns, never fails the release), so the only correct fix is the permission grant in the robot provisioner. Committed directly to homelab-cluster main (commit 9938e09) and ran the job, per user's choice over a PR flow.
Why it matters: Keeps the robot least-privileged (a stated roadmap goal) and puts the change where the resource is actually defined.
Snippet: commit fix(harbor): grant CI robot sbom:create so release SBOM generation stops 403ing
Suggested home: memory
Open questions / unfinished
[OPEN] The actual pipeline call (POST .../scan {"scan_type":"sbom"} as the robot) returning 202 was NOT directly exercised — firing it needs the robot token (a credential the auto-mode classifier blocked). Proof is by construction (endpoint requires sbom:create [VERIFIED source] + robot now has it [VERIFIED live]); final visual confirmation will be the next real release turning the ::warning:: HTTP 403 into Harbor SBOM generation queued and populating Harbor's SBOM column.
[OPEN] Whether the explicit pipeline SBOM POST is even necessary given the project already has auto_sbom_generation (sbom-on-push) enabled — possibly redundant now.
Explicit preferences/feedback I gave
"Make sure it works" was interpreted (and accepted) as: verify end-to-end against the real cluster/source, not just reason on paper — including live job execution, not just syntax checks.
When asked how to do the live verification, I chose commit + run the job now over the commit + PR + let Flux apply option (direct-to-main is acceptable for this homelab GitOps repo; PR/review path was explicitly declined).
Note (constraint, not a stated preference): the auto-mode classifier blocked extracting the Harbor admin password from cluster secrets to call the shared Harbor API, and that block was respected (not worked around). Plan live-verification approaches that don't require pulling credentials — use in-cluster jobs (which use their own mounted secrets) + read-only kubectl/log observation + source inspection instead.
