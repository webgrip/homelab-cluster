# webgrip baseline

These rules hold in every webgrip repository. The repository's own text outside this block wins where it disagrees.

- GitOps first: desired state lives in Git and Flux reconciles it. Change a manifest or values file instead of running `kubectl apply/patch/delete` or `helm install/upgrade`; reading is fine. A rollout is live only once the reconciled revision and the running image digest match.
- Secrets have a level, and OpenBao holds the only original ([homelab-cluster ADR-0055](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/docs/techdocs/docs/adr/adr-0055-one-secrets-model-six-levels.md)). Never put a plaintext value in a file or add a `*.sops.yaml` outside the floor. Write the manifests and hand the person the `bao kv put` command; never handle the value. The `secrets-levels` skill places a secret and the `guard-secrets` hook enforces the floor.
- Follow the branching model the repository's `AGENTS.md` states; without one, commit to `main`. After a push, check the commit is on the remote (`git merge-base --is-ancestor <sha> origin/<branch>`). A forced update of a shared branch is an incident.
- Several sessions share one working tree. Commit only the paths you wrote (`git commit -- <paths>`), never `git add -A`, `git add .` or `git commit -a`, and expect any local commit to be pushed by another session at any moment ([shared working tree](https://forgejo.webgrip.dev/webgrip/agent-standards/src/branch/main/docs/shared-working-tree.md)).
- Run tools through mise (`mise exec -- <cmd>`); versions are pinned in `mise.toml`.
- Write Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`) with an optional scope, one change per commit.
- Renovate owns dependency versions: review its pull requests instead of bumping what it manages.
- Reuse before building: generate, then reference (a pinned `uses:` or an `@webgrip` package), then sync pull requests, then a one-off copy ([reuse and releases](https://forgejo.webgrip.dev/webgrip/agent-standards/src/branch/main/docs/reuse-and-releases.md)).
- No comments in code. Carry intent in names, types, small functions and tests; reasoning goes to `docs/` or an ADR. Machine-read directives stay: shebangs, `# syntax=`, `# renovate:`, schema hints, `@ts-*`, `eslint-*`, `# shellcheck`, `# noqa`, `//go:*` and doc comments a tool reads ([ai-skills ADR-0001](https://forgejo.webgrip.dev/webgrip/ai-skills/src/branch/main/org/adrs/adr-0001-no-comments-in-code.md)).
- Deployable apps follow `application-template`; Helm plumbing comes from `common-charts` and `helm-dependency-values`. A ServiceMonitor or PrometheusRule needs `release: kube-prometheus-stack`, or it is never scraped.
- Docs are TechDocs (MkDocs under `docs/`) and change with the behaviour. Durable knowledge goes into the repository, skill or command that owns it, never into agent memory.
- Validate with the repository's documented gate before committing, and say plainly what failed or was skipped. Check the primary source before claiming something works or never worked.
- Never hardcode secret domains or IPs; template them. Escape runtime shell variables in manifests as `$${...}`, because Flux postBuild substitution eats `$`.
- Keep organisations apart: no names, hosts, ids or people of an employer or client in a webgrip repository.
- The Bash tool may run zsh: quote variables, use arrays, `set -o pipefail` before gating on a pipeline, and close stdin (`< /dev/null`) for CLIs that may read it.
