# Bringing the Forge Home

### Leaving GitHub for a self-hosted Forgejo — and discovering, part by part, how many things "GitHub" secretly meant

*Published 2026‑06‑12*

---

## Prologue: the north star

The goal is easy to say and surprisingly hard to finish: **leave GitHub.**

Not "mirror to a backup." Not "self-host a copy and keep working on GitHub anyway." Actually leave — make a Forgejo instance running on the cluster the *source of truth*, demote GitHub to a thing you pull *from* during the transition, stand up Codeberg as an off-site mirror for redundancy, and then, when the dust settles, walk away from GitHub entirely.

It sounds like one move. It is not. "GitHub," it turns out, is not a website you visit; it is a load-bearing assumption threaded through dozens of unrelated-looking systems. It is where your code lives, yes — but it is also your CI engine, your runner autoscaler, your package registry, the **cryptographic identity that signs your container images**, the OIDC issuer a Kyverno admission policy trusts, the bot account your dependency updater logs in as, the webhook that tells your GitOps controller to reconcile, and the place a documentation site quietly fetches from. Pull on the thread marked "git host" and a dozen other systems follow it out of the drawer.

This is the story of finding every one of those threads and, one at a time, re-tying it to something we own. Some are done. Some are half-done and honest about it. One is wedged in the most poetic way possible. The map we're working from looks like this: a **Forge** (Forgejo) at the centre; **GitOps** (Flux) and **CI** (Forgejo Actions + runners) hanging off it; a **Package Registry** (Harbor) feeding deployments; **Identity** (Authentik) vouching for everyone; a constellation of **peripheral applications** that log in through that identity; and a ring of **public mirrors** — Codeberg, a second Forgejo, and a demoted GitHub — for redundancy. Let's walk the map.

---

## The forge itself

The centre of the new world is `forgejo.webgrip.dev` — a [Forgejo](https://forgejo.org/) server, the community fork of Gitea, deployed by the official Helm chart and reconciled by Flux like everything else. It is already live, already public, and already the nicest piece of the migration to look at, because it's the part that's genuinely *done*.

A few deliberate choices define it:

- **It is rootless and deliberately humble.** A single replica, a `Recreate` upgrade strategy, all Linux capabilities dropped, no privilege escalation. Forgejo is not HA-capable and we don't pretend otherwise — one pod, recreated cleanly on upgrade, is the honest configuration. For a homelab forge serving one human and a fleet of automation, "simple and correct" beats "clustered and fragile."
- **Two front doors.** The web UI is exposed publicly through the external Envoy gateway, with a k6 synthetic canary watching the ingress. Git-over-SSH gets its *own* dedicated Cilium LoadBalancer IP — `10.0.0.31`, announced on the LAN by L2, resolving as `forgejo-ssh.webgrip.dev` — so clone URLs render as `git@forgejo-ssh.webgrip.dev:owner/repo.git` and SSH never has to share a port with anything. (The `forgejo` namespace had to be explicitly allow-listed in the Kyverno network-exposure policy to be permitted a LoadBalancer at all; sovereignty has paperwork.)
- **A storage split that keeps the expensive disk small.** This is the quietly clever bit. Git repositories themselves live on a modest 20Gi Longhorn volume — they're small, they want low latency, they belong on fast replicated block storage. But the *heavy* objects — LFS blobs, package-registry artifacts, attachments, avatars, CI artifacts — are pushed out to **Garage S3** (`10.0.0.110:3900`, path-style addressing, plain HTTP, the minio-compatible protocol Forgejo speaks natively). The result: the forge can host gigabytes of LFS and packages without ever inflating a Longhorn claim. Block storage stays lean; object storage absorbs the bulk.
- **Postgres for everything stateful.** A CloudNativePG cluster, `forgejo-db`, backs the server — backed up nightly to Garage S3 with its own dedicated write-ahead-log volume, the standard pattern across this cluster. And sessions live in Postgres too (`session.PROVIDER=db`), which means logins survive pod restarts and the whole thing needs **no Redis**. Cache is in-process memory; the queue is a LevelDB file on the data volume. One database, no auxiliary stateful services, restarts that don't log you out.

It even runs in `OFFLINE_MODE` — no phoning home, no third-party avatars or gravatars, a forge that works the same whether or not the wider internet is reachable. Which is, when you think about it, the whole point.

---

## Identity: who are you, without GitHub?

On GitHub, identity is free and invisible — you *are* your GitHub account, your org membership *is* your authorization, and you never think about it. Take GitHub away and you have to answer the question explicitly: who is allowed in, and who says so?

The answer is **Authentik**, the cluster's OIDC provider. Forgejo trusts it as an OpenID Connect login source via an auto-discovery URL, and the wiring is configured for the post-GitHub world:

- **Auto-provisioning.** First SSO login through Authentik creates the Forgejo account automatically (`ENABLE_AUTO_REGISTRATION`, `ACCOUNT_LINKING=auto`). You don't pre-create users; Authentik vouches for them and Forgejo materialises them.
- **SSO is the *only* front door.** The local signup form is hidden and only external registration is allowed (`ALLOW_ONLY_EXTERNAL_REGISTRATION=true`). There is exactly one way to become a user: log in through Authentik.
- **Break-glass, not daily-driver.** A local `gitea_admin` account exists with `passwordMode: keepUpdated`, but it is strictly an emergency hatch. The human identity is `Ryangr0` — deliberately separated from Authentik's `akadmin` superuser, and placed in the `homelab-users` and `homelab-mfa` groups so that even the forge owner logs in as a normal, MFA-bound mortal.

The piece still on the drawing board is **teams**. On GitHub, org teams gate repository access. The plan is to map **Authentik groups → Forgejo teams**, so that group membership in the identity provider becomes the single source of authorization across the forge — the same way it already gates every other app behind Authentik. It's deferred for now, sequenced after the content actually lands in Forgejo, but it's the move that finally retires "GitHub teams" as a concept.

---

## CI, act one: the autoscaler nobody sees

Here is where leaving GitHub stops being a settings change and becomes engineering.

On GitHub, your workflows run on `ubuntu-latest` and you never think about where. In this cluster they ran on **ARC** — GitHub's Actions Runner Controller — with two pools: a normal pool (`arc-runner-set`, pinned to the `soyo` nodegroup) for linting and tests, and a heavy pool (`arc-runner-set-heavy`, pinned to `fringe`, labelled `dind`) for Docker image builds. ARC is good software. But it is *GitHub's* software, speaking GitHub's runner protocol, and it has no idea Forgejo exists.

The replacement starts one layer down, with a prerequisite most people never have to think about: **KEDA**, the Kubernetes Event-Driven Autoscaler. ARC bundled its own scaling logic; Forgejo's runner does not. So KEDA becomes the general-purpose engine that watches an external signal and turns it into pods — and the external signal, in our case, is "how many CI jobs are pending in Forgejo right now?" KEDA is the unglamorous foundation the whole CI story is built on, and it had to land first.

---

## CI, act two: ephemeral runners that scale to zero

On top of KEDA sits the actual ARC replacement: a **KEDA `ScaledJob`** that is, frankly, a lovely piece of design.

It works like this. A KEDA Forgejo scaler polls the server every thirty seconds, asking how many jobs are queued with the `docker` label. When work appears, KEDA creates **one ephemeral Kubernetes Job per pending CI job** — scaling from zero up to a ceiling of six. Each runner pod runs `forgejo-runner one-job`: it registers itself, executes *exactly one* job, and exits. There are no long-lived runners sitting idle burning memory; when the queue is empty, the runner count is genuinely zero.

And because half of what CI does is build container images, each runner pod ships with **Docker-in-Docker as a native sidecar** — a privileged `dind` container that starts before the runner, exposes a TLS-secured Docker daemon, and is automatically torn down the instant the runner finishes its one job, so the Job completes cleanly instead of hanging on a sidecar that never dies. The runners are pinned to the dedicated `fringe` nodes, mount no service-account token they don't need, and clean up after themselves completely.

It is everything ARC gave us — ephemeral, autoscaling, DinD-capable runners — rebuilt on event-driven primitives we control, pointed at a forge we own. It is proven to sit correctly at zero. There is exactly one honest caveat, and the manifest says so out loud in a code comment: the precise `one-job` invocation hasn't been confirmed against a *real* job yet. Which is the perfect segue, because the thing that proves a runner is a workflow.

---

## CI, act three: rewriting the workflows

This is the part the one-line summary buries and the reality inflates. Migrating CI isn't moving runners; it's **rewriting every workflow**, because GitHub Actions workflows are saturated with GitHub.

Today the repo carries seven of them in `.github/workflows/`: a Flux-manifest validator (`flux-local`), an end-to-end check (`e2e`), two label managers (`labeler`, `label-sync`), two Renovate helpers (`renovate-dry-run`, `renovate-trigger`), and a Claude-powered PR reviewer (`claude-review`). Pull one open — the Flux validator is representative — and count the GitHub-isms:

- `runs-on: ubuntu-latest` — a GitHub-hosted runner that simply does not exist in our world.
- A pile of **Marketplace actions** pinned by digest: `actions/checkout`, `tj-actions/changed-files`, `mshick/add-pr-comment`, `anthropics/claude-code-action`. Forgejo Actions can resolve actions, but *where from* is a decision — proxy to GitHub, or mirror them into a Forgejo `actions/` namespace you control. (Mirroring is the philosophically consistent answer; depending on GitHub's Marketplace to run the CI that's supposed to free you from GitHub is a circular dependency with a sense of humour.)
- Deep coupling to the **GitHub event and API surface**: `github.event.pull_request.number`, `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY`, posting PR comments through GitHub's REST API. Forgejo has analogues, but they are not identical, and the diff-commenting and labeling workflows lean on them hardest.

Against all that, the Forgejo side currently holds a single file — a nine-line `ci.yml` that says `runs-on: docker`, prints a greeting, and runs `docker version`. It looks like nothing. It is, in fact, the beachhead: the one workflow whose only job is to prove the KEDA runner executes a real `docker`-labelled job end to end. Once it goes green, the seven real workflows get ported behind it, one at a time, each re-expressed in Forgejo's dialect. The smoke test is small on purpose. Everything else waits behind it.

---

## The registry: GHCR, and the Harbor-shaped hole

Every image this platform builds lands in **GHCR** — `ghcr.io/webgrip/*`. The plan is to replace it with a self-hosted **Harbor**, so that container images, like source code, live on infrastructure we own.

In the interest of honesty — and this is exactly the kind of thing "go look" is for — Harbor currently has **zero footprint in the cluster.** No manifests, no namespace, no plan document, not so much as a stray reference in a values file. It is, at this moment, purely a box on the architecture diagram and an intention in the operator's head. GHCR is still doing the job.

That's fine; it's just worth naming precisely, because Harbor is not a small domino. The moment images move off GHCR, three other things have to move with them: the CI workflows that `docker push`, the BuildKit registry cache they pull from, and — far more delicately — the entire supply-chain trust chain described next, which currently assumes images live in GHCR and were signed by GitHub. Harbor is the registry, but it's also the keystone of the hardest section of this whole migration.

---

## The trust boundary: from GitHub's OIDC to Authentik's

If there is a part of this migration that will demand real care, it is this one, and it's the part the short brief gestured at with five words — *"GitHub's OIDC → Authentik."* Those five words hide the deepest GitHub dependency in the building.

Here's what's actually wired today. When an application image is built and released, CI doesn't just push it to GHCR — it **signs the image digest with Cosign, keylessly, using GitHub's OIDC identity** (`https://token.actions.githubusercontent.com`). No private key; the signature is anchored to a short-lived token that proves "this was built by this GitHub workflow, on this repo, on this release tag." It then attaches a CycloneDX SBOM and SLSA provenance as further signed attestations, all living in GHCR beside the image.

That signature is not decorative. A **Kyverno admission policy** verifies it at deploy time, and the subject it trusts is spelled out exactly:

> Issuer `https://token.actions.githubusercontent.com`, subject `https://github.com/webgrip/infrastructure/.github/workflows/on_release_published.yml@refs/tags/<tag>`.

Meanwhile **GUAC**, the supply-chain graph, runs an `oci-collector` that continuously polls `ghcr.io/webgrip/*` for exactly these attestations to build its picture of what's running and where it came from. The cluster's whole notion of "is this image trustworthy?" is, right now, a sentence that contains the words *github.com*, *githubusercontent.com*, and *ghcr.io* — three times over, in a security policy.

Leaving GitHub means re-anchoring every clause of that sentence:

- The **keyless signing identity** moves from GitHub's OIDC issuer to **Authentik's** — Authentik becomes the Fulcio-style identity that vouches for "this was built by our CI."
- The **Kyverno subject pattern** is rewritten from a GitHub workflow path to the equivalent Forgejo Actions identity.
- **GHCR → Harbor** for where the image and its attestations live.
- **GUAC's collector** re-points from polling GHCR to polling Harbor.

None of this is started, and it shouldn't be — it depends on Harbor existing and on Forgejo Actions producing a verifiable build identity, both of which are downstream. But it's the reason "leave GitHub" can't be finished by a checkbox. The most security-critical assumption in the cluster is currently the sentence "GitHub built this," and rewriting that sentence is the real boss fight, still ahead of us.

---

## Renovate: the bot changes employers

Dependency updates run through a self-hosted Renovate, driven by an operator. It is, today, thoroughly a GitHub employee: its config declares `"platform": "github"`, it authenticates by minting a **GitHub App installation token** on a schedule (a little CronJob that exchanges an app ID, installation ID, and private key for a short-lived token against `api.github.com`), and it commits as `webgrip-renovate[bot]` with a `users.noreply.github.com` email.

In the post-GitHub world Renovate has to change employers wholesale: platform flipped from `github` to Forgejo's, the GitHub-App token dance replaced by a Forgejo token, the bot identity re-homed. The good news is that Renovate has supported Gitea/Forgejo as a first-class platform for a long time, so this is a configuration migration rather than a rewrite. The subtle part is the *datasources* — Renovate also reaches out to `api.github.com` to discover new versions of upstream dependencies, and that's legitimate; you can leave GitHub as your *source host* while still querying it as a *version oracle*. Telling those two roles apart — GitHub-as-employer (must leave) versus GitHub-as-public-data (fine to keep using) — is most of the work.

Since that audit, this thread has gone from *named* to *designed* — and the shape it took turns on the same ouroboros that wedged the mirror. Renovate can only open a pull request against a repo it can *push branches to*, and you cannot push to a pull-mirror. Every `webgrip/*` repo in Forgejo is, right now, a read-only mirror of its GitHub original; Renovate's Forgejo autodiscover even skips them on sight. So the bot cannot simply be re-pointed at Forgejo and switched on. It can only act on a repo *after* that repo stops being a mirror and becomes authoritative — which is, once again, content-first, cutover-last.

That dictated the design: not a flip, but a **dual-run**. The GitHub-employed Renovate keeps doing its job for every repo still living on GitHub, while a *second* Renovate — a new job, Forgejo-flavoured, committing as a Forgejo bot — comes online beside it and adopts each repo the moment it's de-mirrored. The two coexist for the whole transition; at the very end, when the last repo (you can guess which one) flips, the GitHub half is deleted in a single stroke rather than nervously cut over.

And there's a small, satisfying inversion buried in it. Almost every other thread of this migration *adds* machinery — a runner autoscaler, a webhook bridge, an entire trust chain to re-anchor. Renovate's gets *simpler*. The GitHub employee needs a CronJob that, every thirty minutes, trades an app ID and a private key for a token that expires in an hour; the Forgejo employee just needs a long-lived bot token sitting in OpenBao. The whole token-minting apparatus — CronJob, RBAC, the PEM private key — doesn't get ported. It gets thrown away. Leaving GitHub, here, means *deleting* code.

The honest caveat the audit demanded still holds: Renovate will leave GitHub as an **employer** well before it leaves as a **data oracle**. It keeps reading `api.github.com` for upstream release numbers (a public catalog, not a matter of sovereignty) and keeps pulling GHCR images through a read-only `read:packages` token until Harbor exists. Those are read paths; they retire on their own schedule. The write path — the part that actually matters — moves now. The full design is written up as [a dedicated RFC and three ADRs](../architecture/rfc-renovate-forgejo.md).

---

## The GitOps umbilical

Here is the one that surprises people, and it surprised the audit too. After all of the above — a live forge, live runners, a near-complete mirror — **Flux still pulls the cluster's own desired state from GitHub.** The GitRepository that drives the entire GitOps loop points, today, at `https://github.com/webgrip/homelab-cluster.git`. So does `git remote`. So does the Flux **`Receiver`** — a webhook endpoint of `type: github` that lets a GitHub push trigger an instant reconcile instead of waiting for the poll interval. So do the two credentials sitting at the repo root: a `github-deploy.key` for read access and a `github-push-token.txt` for writes.

This is not an oversight; it's the correct *order*. The GitOps source is the last thing you cut over, not the first, because the moment Flux points at Forgejo, Forgejo's availability becomes your cluster's ability to change itself. You want the forge proven, the mirror complete, and the content verified *before* you make the new git host load-bearing for the platform that hosts it. So the umbilical to GitHub stays connected on purpose — right up until the cutover, when the GitRepository URL, the deploy key, the push token, and the webhook Receiver all swing over to Forgejo in one deliberate, well-rehearsed move. Until then, every section of this post is running on a cluster whose marching orders still come from GitHub. There's a certain tension in that, and it's the right tension to hold.

---

## The mirror, and the most poetic bug in the project

The bridge between the two worlds is **gitea-mirror** (`gitea-mirror.webgrip.dev`) — a small SvelteKit app, SQLite-backed, that bulk-mirrors the entire GitHub account and the `webgrip` org into Forgejo in *continuous* mode: code, issues, pull requests, releases, wikis, the lot, kept in sync rather than copied once. It is the workhorse of the transition, and it has done its job almost completely: roughly **seventy-one of seventy-two repositories** are mirrored and tracking.

Almost. There is exactly one holdout, and you could not script a better one if you tried: **`homelab-cluster` itself** — the very repository that *describes this cluster*, the one these blog posts live in — is wedged in a stale "Mirroring" lock, left over from an earlier out-of-memory event that killed the mirror mid-operation and never released the latch. The repository that defines the infrastructure is the single repository the infrastructure can't finish mirroring. The migration's one open snag is a perfect little ouroboros.

Unsticking it is mechanical — reset the mirror state in gitea-mirror's database, or delete-and-re-mirror the one repo — but it lands on the wrong side of a guardrail: the automation is blocked from `kubectl exec`-ing into pods by the same GitOps-only safety rules that keep the rest of the cluster honest. So it waits for a human hand, or an explicit authorization. The other ninety-nine percent is done; the last one percent is a fittingly recursive joke.

---

## Redundancy: Forgejo → Codeberg, and a second forge

The end-state isn't a single self-hosted forge with no safety net — that would trade GitHub's lock-in for a single point of failure of our own making. The diagram's outer ring is a set of **public mirrors**: **Codeberg** (the community Forgejo host, for genuine off-site redundancy), a **second, separate Forgejo instance** (off-cluster, so a total cluster loss doesn't take the forge with it), and — in a satisfying inversion — **GitHub itself, demoted** from origin to just another downstream mirror.

This is deliberately *not built yet*, and the reasoning is sound enough to state plainly: there's no point standing up `Forgejo → Codeberg` push-mirrors (via Forgejo's native push-mirror feature, or a `forgesync`-style job) *before* the GitHub → Forgejo cutover, because until Forgejo is authoritative, all you'd be doing is laundering GitHub's content sideways into Codeberg. Mirror *from* the new source of truth, not *through* a way-station that's about to be retired. So redundancy is sequenced last: finish the inbound mirror, validate, cut over, *then* fan back out to Codeberg and the second forge. The whole time, the real disaster-recovery floor is the boring, reliable one — CNPG backing `forgejo-db` up to Garage S3, every night.

---

## Documentation, and the smaller pieces

A few more threads, each shorter but real:

- **Documentation hosting.** These very techdocs, today built and served inside the cluster, are slated to move to **Codeberg Pages** — documentation that survives the cluster being down, hosted on infrastructure aligned with the rest of the redundancy story. Planned, not yet wired.
- **The Claude PR reviewer.** One of the seven GitHub workflows runs `anthropics/claude-code-action` to review pull requests. Forgejo Actions can run it too, but PR-review semantics and the comment API differ enough that it's a genuine port, not a copy.
- **Secrets, already handled.** Every secret the forge ecosystem needs — the Forgejo admin and OIDC and S3 credentials, the runner registration and scaler tokens, the gitea-mirror secret — has *already* been migrated off SOPS and onto External Secrets with an OpenBao backend. That was a parallel effort (told in [its own post](2026-06-12-the-long-goodbye-to-sops.md)), and it means the forge migration never had to touch an encrypted file; it just referenced Secrets that manage themselves.

---

## Where we actually are

Stripped of narrative, the honest status board:

| Part | From (GitHub) | To | State |
|---|---|---|---|
| Git host | github.com/webgrip | Forgejo (`forgejo.webgrip.dev`) | **Live** |
| Forge database | — | CNPG `forgejo-db` → Garage S3 | **Live** |
| Bulk storage | — | Git on Longhorn, LFS/packages on Garage S3 | **Live** |
| SSO / identity | GitHub accounts & teams | Authentik OIDC (`Ryangr0`) | **Live** (groups→teams pending) |
| Runner autoscaler | ARC | KEDA | **Live** |
| Runners | ARC scale sets (normal+heavy) | KEDA `ScaledJob` (ephemeral, DinD) | **Live, unproven on a real job** |
| CI workflows | 7× `.github/workflows` | Forgejo Actions | **1 smoke test; 7 to port** |
| Bulk mirror | — | gitea-mirror (continuous) | **~71/72; `homelab-cluster` wedged** |
| Package registry | GHCR | Harbor | **Not started** |
| Signing / trust | GitHub OIDC + GHCR + Kyverno | Authentik OIDC + Harbor | **Not started** |
| Renovate | platform `github` + GitHub App | Forgejo platform (dual-run) | **Designed ([RFC](../architecture/rfc-renovate-forgejo.md) + ADRs); build pending** |
| GitOps source | Flux ← GitHub (+ webhook Receiver) | Flux ← Forgejo | **Not started (cutover last)** |
| Off-site mirrors | — | Codeberg + 2nd Forgejo + demoted GitHub | **Deferred (after cutover)** |
| Docs hosting | in-cluster | Codeberg Pages | **Planned** |

The shape of it: **the forge is home, and people and machines can already live in it.** What remains is the harder, less glamorous half — re-pointing the things that *believe in GitHub* (the registry, the image signatures, the dependency bot, and finally the GitOps controller itself) at the new world, in the right order, with the cutover last so the platform never loses its footing.

---

## Epilogue: what "leaving" really costs, and buys

It would have been easy to declare victory the day `forgejo.webgrip.dev` served its first page. The forge was up; the code was there; you could clone over SSH and log in through SSO. Done, surely?

But "leaving GitHub" was never about where the code is hosted. It's about *whose assumptions you're running on*. The audit that produced this post kept turning up the same shape: a system that looked self-contained, with the word "GitHub" buried three levels down — a Kyverno policy trusting GitHub's OIDC, a Renovate bot logging in as a GitHub App, a Flux controller taking its orders from a GitHub URL, a supply-chain graph polling a GitHub registry. None of those are the git host. All of them are GitHub.

So the work that remains is the work that matters: re-homing the *trust*, not just the *files*. Teaching the cluster to believe in Authentik's signature instead of GitHub's, in Harbor's images instead of GHCR's, in Forgejo's webhooks instead of GitHub's. Each one is a small, careful act of sovereignty, and the order matters — content first, cutover last, redundancy after.

And when it's finished, the prize is the same humble thing the storage split and the offline mode were already reaching for: a system that works because *you* run it, on hardware *you* own, trusting identities *you* issue — that keeps serving whether or not the wider internet, or one very large company, is having a good day. The forge is home. The rest of the house is being rewired around it, one honest thread at a time.

*And somewhere in a SQLite database, a single repository named `homelab-cluster` is still waiting, very patiently, to finish describing the cluster it's stuck inside.*
