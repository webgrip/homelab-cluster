Thread Digest: Migrating webgrip repos to Forgejo-leading (off gitea-mirror)
One-line summary: Built a repeatable procedure + skill + automation script to flip webgrip/* repos from GitHub-leading (gitea-mirror pull-mirror into Forgejo) to Forgejo-leading, then add settings-parity (Actions, push-mirror back to GitHub, branch protection); migrated workflows, renovate-config, claude-config and created org profile repos.
Approx date / status: 2026-06-25 → 2026-06-26 — in progress (git cutovers + parity done; one push-mirror blocker open).

Items
[PROCEDURE] Forgejo-leading repo cutover (the core migration)
Type: PROCEDURE
Verification: [VERIFIED]
What: Per repo, in this order (order is load-bearing — un-mirroring before stopping gitea-mirror lets the next sync re-assert the read-only mirror): (1) in gitea-mirror UI disable/remove the repo from the managed set; (2) in Forgejo repo Settings click Synchronize now (final pull) then convert to writable (see Danger-Zone item); (3) re-point local git remotes. gitea-mirror disable alone does NOT stop Forgejo's own scheduled pull — the convert does.
Why it matters: A GitHub→Forgejo pull-mirror is read-only; in-cluster Forgejo CI must push tags/releases, so the repo must be made writable and the local clone re-pointed.
Snippet:

git remote rename origin github
git remote set-url github git@github.com:webgrip/<repo>.git      # drop any stray ":/"
git remote add origin ssh://git@forgejo-ssh.webgrip.dev/webgrip/<repo>.git
git fetch origin && git fetch github
git rev-parse origin/main github/main        # MUST match (Forgejo synced to GitHub HEAD)
git branch --set-upstream-to=origin/main main
git config remote.pushDefault origin
Suggested home: existing-skill (.claude/skills/forgejo-leading/SKILL.md)
[GOTCHA] Un-mirror is Danger-Zone "Convert to a regular repository", NOT the Mirror-settings panel
Type: GOTCHA
Verification: [VERIFIED]
What: The Forgejo repo Mirror settings panel has no un-mirror button — only Synchronize now / interval / prune. The only way to make a pull-mirror writable is repo Settings → Danger Zone → "Convert to a regular repository" (type repo name to confirm), which flips is_mirror=false. Setting mirror interval to 0 only stops periodic sync; the repo stays read-only. (Original skill draft told the user to "remove the pull-mirror" on the Mirror panel — that was wrong and corrected.)
Why it matters: Without this, the cutover stalls at a dead-end UI page; push to origin keeps returning 403 remote: mirror repository is read-only.
Snippet: Verified on Forgejo 15.0.2 (gitea-1.22) (GET https://forgejo.webgrip.dev/api/v1/version → {"version":"15.0.2+gitea-1.22.0"})
Suggested home: existing-skill / memory
[GOTCHA] Verify un-mirror via the .mirror flag, NOT anon permissions.push
Type: GOTCHA
Verification: [VERIFIED]
What: GET /api/v1/repos/<owner>/<repo> field permissions.push reflects the anonymous caller, so it reads false even for already-converted writable repos. The reliable signal is the top-level .mirror boolean. The other proof is git push origin main succeeding (no 403).
Why it matters: We almost concluded a converted repo was still read-only because anon push:false; the .mirror flag is the truth.
Snippet: curl -fsS https://forgejo.webgrip.dev/api/v1/repos/webgrip/<r> | python3 -c 'import sys,json;print(json.load(sys.stdin)["mirror"])'
Suggested home: existing-skill / memory
[GOTCHA] GitHub push-mirror PAT needs workflow scope, not just repo
Type: GOTCHA
Verification: [VERIFIED] (root cause confirmed; fix not yet applied)
What: A Forgejo→GitHub push-mirror pushes all refs. GitHub rejects any pushed ref that creates/updates a file under .github/workflows/ unless the PAT has the workflow scope. Tags/releases don't touch workflow files so they sync (the "release appears on GitHub"), but a commit/branch changing a workflow file is rejected → the code/branch doesn't land. This is the literal cause of "the release is mirrored but the code isn't."
Why it matters: Repos full of workflow files (e.g. workflows has 51) show a perpetually-failing mirror; repo-only PATs are insufficient. Fix: edit the existing classic PAT and add workflow (keeps the same token value, so Forgejo's stored mirror creds gain the scope with no further change).
Snippet: Error seen in push_mirrors.last_error: ! [remote rejected] <branch> (refusing to allow a Personal Access Token to create or update workflow .github/workflows/<file> without 'workflow' scope). Check scopes: curl -sI -H "Authorization: token $GH_MIRROR_TOKEN" https://api.github.com/user | grep -i x-oauth-scopes
Suggested home: existing-skill / memory / doc
[GOTCHA] Don't copy GitHub status_check_contexts into Forgejo branch protection
Type: GOTCHA
Verification: [VERIFIED] (caught in dry-run before applying)
What: When mirroring GitHub branch protection to Forgejo, copying GitHub's required_status_checks.contexts (e.g. validate (default.json)) deadlocks every Forgejo merge — those are GitHub job names; Forgejo's checks are named differently and will never report them. Keep only structural rules (require PR + approvals, block force-push/deletion). Re-add status checks later under the actual Forgejo check names.
Why it matters: Would silently block all PRs on the migrated repo.
Snippet: Forgejo protection bodies used — baseline: {"rule_name":"main","enable_push":true}; strict (mirror GitHub PR rule): {"rule_name":"main","enable_push":false,"required_approvals":1}. Any rule on main blocks force-push + deletion.
Suggested home: existing-skill
[GOTCHA] Converting a pull-mirror leaves Actions AND Pull-Requests units OFF
Type: GOTCHA
Verification: [VERIFIED]
What: gitea-mirror creates the Forgejo repo with has_actions=false, and converting a pull-mirror to a regular repo leaves has_pull_requests=false (mirrors are read-only). PRs-disabled makes Renovate skip the repo ("pull requests are disabled") and blocks normal PRs. Both must be re-enabled to reach parity. PATCH /repos/{o}/{r} with {"has_actions":true} / {"has_pull_requests":true}.
Why it matters: A freshly-migrated repo silently has no CI and no Renovate until these units are turned on.
Snippet: curl -fsS -H "Authorization: token $FORGEJO_TOKEN" -X PATCH https://forgejo.webgrip.dev/api/v1/repos/webgrip/<r> -d '{"has_actions":true}'
Suggested home: existing-skill
[DECISION] Reusable-workflow library repos keep Forgejo Actions OFF
Type: DECISION
Verification: [ASSERTED]
What: For reusable-workflow library repos (webgrip/workflows), force the Forgejo Actions unit OFF even though GitHub has it on. Their workflows are on: workflow_call and execute in the caller repo's runner; disabling the unit does NOT break uses: consumers. (Encoded in forgejo-sync.sh as ACTIONS_OFF_REPOS="workflows".)
Why it matters: Prevents stray in-repo runs on pushes/PRs to the library.
Snippet: ACTIONS_OFF_REPOS="workflows" ; is_actions_off() forces {"has_actions":false}
Suggested home: existing-skill / memory
[GOTCHA] Forgejo PAT granular scopes — /user 403s, org-list needs read:organization
Type: GOTCHA
Verification: [VERIFIED]
What: A Forgejo PAT scoped only write:repository (correct for repo ops: edit/mirror/protection) 403s on GET /api/v1/user because that needs read:user. Don't use /user to validate the token — probe a repo endpoint instead. Also GET /orgs/{org}/repos (used for --all sweeps) needs read:organization; without it, target repos explicitly. A 403 (not 401) means valid-token-but-missing-scope.
Why it matters: We wasted a cycle thinking the token was stale (it was a scope mismatch on /user).
Snippet: Validate with curl -s -o /dev/null -w '%{http_code}' -H "Authorization: token $FORGEJO_TOKEN" https://forgejo.webgrip.dev/api/v1/repos/webgrip/<r> (expect 200)
Suggested home: existing-skill
[GOTCHA] gh api prints error body to stdout on 404 — fallback must be outside $(...)
Type: GOTCHA
Verification: [VERIFIED] (bug hit, then fixed)
What: On HTTP error (e.g. branch not protected → 404) gh api writes the error JSON to stdout and exits non-zero. Writing x=$(gh api ... || echo '{}') concatenates the error JSON with {} → a "two JSON docs" parse crash. Put the fallback outside the command substitution.
Why it matters: Silent, confusing JSON parse failures in scripts that read optional GitHub state.
Snippet: WRONG: ghp=$(gh api "..." 2>/dev/null || echo '{}') — RIGHT: ghp=$(gh api "..." 2>/dev/null) || ghp='{}'
Suggested home: doc / existing-skill
[FACT] gitea-mirror config/state is in its own SQLite DB — no API, UI-only
Type: FACT
Verification: [ASSERTED] (from gitea-mirror docs)
What: The raylabshq/gitea-mirror app (ghcr.io/raylabshq/gitea-mirror, deployed in the forgejo namespace, data at /app/data/gitea-mirror.db) stores its repo list + sync settings in a private SQLite DB. There is no REST API/CLI to disable a repo's mirroring — it's a web-UI action (or unsupported direct SQLite edits). Disabling a repo there is non-destructive (leaves the Forgejo repo intact). If gitea-mirror auto-imports the whole org, a per-repo disable can be re-added on the next discovery pass — exclude the repo instead.
Why it matters: Migration step 1 cannot be automated; must be a manual UI pause.
Snippet: App tree in repo: kubernetes/apps/forgejo/gitea-mirror/ (helmrelease pins ghcr.io/raylabshq/gitea-mirror:v3.8.4, mem limit 2Gi)
Suggested home: memory / existing-skill
[FACT] Forgejo .github/.github-private equivalents = .profile / .profile-private; no org-wide defaults repo
Type: FACT
Verification: [VERIFIED] for .profile (public) creation; [ASSERTED] for .profile-private members-only rendering
What: Forgejo org profile README = a repo named .profile with README.md at the repo root (NOT profile/README.md like GitHub). Members-only overview = .profile-private (private repo, root README.md) — analog to GitHub .github-private; landed in recent Gitea/Forgejo (feature go-gitea#29503). There is no Forgejo equivalent of GitHub's .github org-wide defaults repo (shared issue/PR templates, health files, default workflows); those stay per-repo (.forgejo/, .gitea/; .github/ read for compat). Shared CI is solved via uses: webgrip/workflows/.forgejo/workflows/<name>@<ref>.
Why it matters: Sets correct expectations when replicating GitHub org features on Forgejo.
Snippet: Created webgrip/.profile (public) + webgrip/.profile-private (private), each pushed over ssh://git@forgejo-ssh.webgrip.dev/webgrip/<name>.git
Suggested home: memory / doc
[PROCEDURE] Two migration shapes: convert-mirror vs create-and-push
Type: PROCEDURE
Verification: [VERIFIED]
What: If the repo exists on Forgejo as a pull-mirror → do the un-mirror/convert flow. If it was never mirrored (GET /api/v1/repos/webgrip/<r> returns 404) → skip the convert; instead create an empty repo on Forgejo (match GitHub visibility) and populate with git push origin --all && git push origin --tags, then re-point. (claude-config was this second shape — HTTP 404 on Forgejo vs 200 for mirrored repos.)
Why it matters: The original skill only covered the mirror-convert case.
Snippet: Distinguish: curl -s -o /dev/null -w '%{http_code}' https://forgejo.webgrip.dev/api/v1/repos/webgrip/<r> (404 = create-and-push)
Suggested home: existing-skill
[REFERENCE] forgejo-sync.sh — settings-parity automation
Type: REFERENCE
Verification: [VERIFIED] (dry-run + --apply ran; Actions/mirror/protect applied to 3 repos)
What: Committed script scripts/forgejo-sync.sh brings a Forgejo repo to parity with its GitHub origin: actions (enable unit, except ACTIONS_OFF_REPOS), prs (enable PRs unit), mirror (add Forgejo→GitHub push-mirror), protect (mirror GitHub's main rule or apply a baseline). Dry-run by default; --apply required to write. Idempotent (checks current state first). Push-mirror remote_username must be the token owner (resolved from https://api.github.com/user), not the org name.
Why it matters: Reusable for the ~65 remaining org repos.
Snippet:

set -a; source ~/.config/webgrip/forgejo.env; set +a   # FORGEJO_TOKEN (write:repository) + GH_MIRROR_TOKEN (GitHub PAT: repo + workflow)
scripts/forgejo-sync.sh --repo <name>            # dry-run
scripts/forgejo-sync.sh --repo <name> --apply
scripts/forgejo-sync.sh --all --only actions,mirror --apply
Suggested home: existing-skill (referenced from forgejo-leading)
[REFERENCE] Forgejo API shapes used (base, auth, endpoints, mirror body)
Type: REFERENCE
Verification: [VERIFIED]
What: Base https://forgejo.webgrip.dev/api/v1; auth header Authorization: token $FORGEJO_TOKEN. Push-mirror create: POST /repos/{o}/{r}/push_mirrors. Trigger sync: POST /repos/{o}/{r}/push_mirrors-sync. Branch protection: GET/POST /repos/{o}/{r}/branch_protections. Repo units: PATCH /repos/{o}/{r} with has_actions/has_pull_requests. Mirror status visible via push_mirrors[].last_error (empty string = success).
Why it matters: Direct API automation reference.
Snippet: push-mirror POST body:

{"remote_address":"https://github.com/webgrip/<r>.git","remote_username":"<token-owner>","remote_password":"<REDACTED>","interval":"8h0m0s","sync_on_commit":true}
Suggested home: existing-skill / doc
[REFERENCE] Credentials & connection facts (forgejo-ssh, token file, CI bot)
Type: REFERENCE
Verification: [VERIFIED] (SSH fetch/push worked; token file sourced)
What: Origin SSH URL form ssh://git@forgejo-ssh.webgrip.dev/webgrip/<repo>.git. The forgejo-ssh.webgrip.dev host key is already trusted (RSA, SHA256:ovdl7TeRTFBAxHxFXmGt4PrMhKbrDAQfLvl/WSk4mSg) and Ryan's ed25519 key is on Forgejo. Tokens live in ~/.config/webgrip/forgejo.env exporting FORGEJO_TOKEN + GH_MIRROR_TOKEN (sourced via set -a; source ...; set +a; never echoed). The webgrip-ci bot has org-wide write via the webgrip/ci team, so CI can push tags once a repo is writable — no per-repo token needed.
Why it matters: No host-key prompts, no per-repo credential setup; reusable across the remaining repos.
Snippet: set -a; source ~/.config/webgrip/forgejo.env; set +a
Suggested home: memory / existing-skill
[DECISION] Use SSH (not HTTPS) for origin; keep github remote as backup; safe-push to main
Type: DECISION
Verification: [VERIFIED]
What: origin re-points to Forgejo over SSH (HTTPS would prompt for creds and can't push with the existing key). Keep the github remote as a manual/backup mirror until GitHub is archived. When committing to the homelab-cluster repo, commit with git -c commit.gpgsign=false commit and safe-push (fetch + verify not-behind before pushing) per the concurrent-agents collision risk.
Why it matters: Matches the infrastructure precedent; avoids credential prompts and clobbering others' pushed work.
Snippet: safe-push guard: git fetch origin; BEHIND=$(git rev-list --count HEAD..@{u}); [ "$BEHIND" = 0 ] && git push || echo DIVERGED
Suggested home: CLAUDE.md / memory
[FACT] infrastructure is NOT double-publishing — .releaserc.js gates publish plugin correctly
Type: FACT
Verification: [VERIFIED] (read the file + release author/dates)
What: infrastructure/.releaserc.js selects the publish plugin by env: const publishPlugin = process.env.SEMANTIC_RELEASE_GITEA ? '@saithodev/semantic-release-gitea' : '@semantic-release/github';. Forgejo CI sets GITEA_URL/SEMANTIC_RELEASE_GITEA, so it publishes to Forgejo only. All GitHub releases on infrastructure are dated ≤ 2026-06-18 (the GitHub-leading era, author webgrip-ci[bot]). GitHub main is stale because infra was migrated before forgejo-sync.sh existed and never got a push-mirror — not because of double-publishing.
Why it matters: Avoided a wrong "CI is publishing to the wrong place" conclusion; the real gap is just a missing mirror.
Snippet: gh api "repos/webgrip/infrastructure/releases?per_page=4" -q '.[] | .tag_name+" | "+.author.login+" | "+.created_at'
Suggested home: memory
[DECISION] Migrate webgrip/workflows first; don't migrate consumers before it
Type: DECISION
Verification: [VERIFIED] (migrated first)
What: webgrip/workflows is the reusable-workflow library every other repo consumes via uses: webgrip/workflows/.forgejo/workflows/<name>@<ref>. Migrate it first so consumers' Forgejo CI resolves it on Forgejo before they migrate. It has 0 tags (consumed by reference, no releases of its own).
Why it matters: Ordering constraint for the org-wide migration.
Suggested home: existing-skill / memory
[OPEN] claude-config is private on Forgejo but public on GitHub
Type: OPEN
Verification: [VERIFIED] (state observed)
What: webgrip/claude-config (the Claude Code plugin marketplace) is private on Forgejo but public on GitHub. If consumed by other repos/people anonymously, it likely needs to be public on Forgejo. Visibility left unchanged pending the owner's call.
Why it matters: Anonymous consumers of the marketplace would fail against a private Forgejo repo.
Suggested home: memory
Open questions / unfinished
Mirror token fix not applied: GH_MIRROR_TOKEN still shows x-oauth-scopes: repo (no workflow); until the classic PAT is edited to add workflow, workflows' push-mirror stays broken (its push_mirrors-sync returned HTTP 500 while in the failed state).
infrastructure mirror: no push-mirror; GitHub main stale + tags diverge (GitHub has techdocs-builder-v1.3.x not on Forgejo). A blind mirror would force-delete those GitHub-only tags — needs a divergence decision before adding one.
GitHub Actions still enabled on migrated repos: an On Release Published run fired on infra's GitHub today; proposed disabling GitHub Actions on Forgejo-leading repos (gh api -X PUT repos/<r>/actions/permissions -f enabled=false) so the downstream backup stops running stale pipelines — not yet done.
--all org sweep needs read:organization added to the Forgejo PAT (currently per-repo only).
renovate-config strict protection intentionally omits status checks; re-add under Forgejo check names once its CI has run once.
.profile-private members-only rendering created but not visually verified on Forgejo 15.
~65 remaining org repos still to migrate (same flow).
Explicit preferences/feedback I gave
Wants a skill (not just a script or runbook) for the migration, authored to the repo's house standard (skillsmith).
Wants automation where possible, and "all the coolest Forgejo features" — but selected specifically: branch protection on main + push-mirror → GitHub, applied via a Forgejo PAT (automated), over UI clicking.
Wants all migrated repos to have Forgejo Actions enabled when enabled on GitHub (parity with GitHub state).
Reset/re-scoped tokens themselves and expects scripts to never print token values (length/HTTP-code/masked diagnostics only).
Casual/collaborative working style; comfortable doing the manual UI steps while the assistant scripts the deterministic parts and verifies.
