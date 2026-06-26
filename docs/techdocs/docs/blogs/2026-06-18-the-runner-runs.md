# The Runner Runs

### Four doors between a green smoke test and a real job — and the read-only mirror waiting on the other side

*Published 2026‑06‑18*

---

[Bringing the Forge Home](2026-06-12-bringing-the-forge-home.md) left the CI runner in a very
specific state of almost: *"Live, unproven on a real job."* The KEDA `ScaledJob` sat correctly at
zero, the smoke test was green, and the manifest carried an honest little code comment promising to
validate the `one-job` invocation against a *real* workflow before trusting it. The thing that
proves a runner is a workflow. So someone pushed one — a real `webgrip/infrastructure` build — and
watched what happened.

What happened is the subject of this post. The job did not get picked up. Then it got picked up and
the pod was denied. Then the pod ran and the runner died. Then the runner lived and the job failed.
Then the job ran and *couldn't push*. Four doors, each opening onto another door, each invisible
until the one in front of it was unlocked — and behind the last one, the most predictable plot twist
in the whole migration, the [first post](2026-06-12-bringing-the-forge-home.md) practically
spoiled it.

Every failure below passed `kubeconform` and a `flux-local` render. Every one only showed up live.
That's the genre.

---

## Door 1 — KEDA is innocent

The first symptom looked exactly like the thing you'd blame: "my job isn't being picked up by the
runner." The instinct is to suspect the scaler. The scaler was fine. Its status said so plainly —
`triggersActivity.s0-forgejo.isActive: true`, conditions `ScalerActive`, "Scaling is performed
because triggers are active." KEDA had seen the pending `docker` job and was, every thirty seconds,
*trying* to create a runner Job. The operator log told the rest:

```
admission webhook "validate.kyverno.svc-fail" denied the request:
  pod-security-baseline-enforce / autogen-privileged-containers:
  Privileged mode is disallowed ... /spec/template/spec/initContainers/1/securityContext/privileged/
```

`initContainers[1]` is the `dind` sidecar. This is **`forgejo-runner`** — Forgejo's own runner, not
upstream `act_runner`; the failure modes and flags below reason from `forgejo-runner`, not from `act`.
Each runner is a KEDA `ScaledJob` that spawns an **ephemeral, host-mode, three-container pod** — an
init that copies the static `forgejo-runner` binary out of its image, a privileged `dind` sidecar, and
the toolchain container the steps actually run inside — and it advertises exactly **one honest label,
`docker`** (no `ubuntu-latest`/`default` masks; the label is true, not a costume). It builds images
with a **privileged** Docker-in-Docker today — rootless BuildKit is the destination, not the present
([ADR-0008](../adr/adr-0008-rootless-ci-image-builds.md)) — and `forgejo` is an *application* namespace,
where Kyverno's `pod-security-baseline-enforce` policy forbids privileged containers. So KEDA created
the Job, the Job was rejected at admission, no pod ever existed, and the workflow sat pending forever. The runner
had, in fact, *never successfully created a pod* since it shipped — the smoke test that "proved" it
had been measuring the wrong thing (a runner that scales to zero correctly also creates zero pods
when it's blocked).

The cluster already had the pattern for this: a narrowly-scoped Kyverno `PolicyException`, matched by
label, waiving *only* the `privileged-containers` rule for *only* the runner's Job and Pod. The
ARC runners had one; the Forgejo runner needed its own. Door one, unlocked.

## Door 2 — the gate that isn't in Git

The Kyverno denials stopped. KEDA's next Job was admitted. And then no pod appeared anyway, for a
*different* reason, from a *different* gatekeeper:

```
Warning  FailedCreate  job/forgejo-runner-xrb42:
  pods "..." is forbidden: violates PodSecurity "baseline:latest":
  privileged (container "dind" must not set securityContext.privileged=true)
```

This is Kubernetes' **built-in Pod Security Admission**, not Kyverno — a second, independent
privileged gate, enforcing the `baseline` level on the namespace. The confusing part: the
`pod-security.kubernetes.io/enforce: baseline` label that triggers it *is not in the namespace
manifest*. It's injected by a Kyverno **mutate** rule (`namespace-tenancy-audit`'s `+()`
add-if-absent) onto every application namespace. So the label was real, live, and invisible to
`grep`.

PSA can't be exempted per-pod — it's namespace-scoped — so the fix is the same move the `security`
namespace already makes for Falco and Tetragon: pin `pod-security.kubernetes.io/enforce: privileged`
on the `forgejo` namespace explicitly. Kyverno's baseline policy (with the runner-only exception)
stays the real gate for everything *else* in the namespace; PSA just stops being a redundant second
lock that only the runner trips. The lesson worth keeping: **a privileged workload in an app
namespace needs two doors opened, not one**, and they look identical until you read *which* admission
controller is talking.

## Door 3 — a UUID that was never a UUID

Pod admitted. The dind daemon came up. The runner container started, and exited 1:

```
Error: invalid configuration: malformed `uuid` "3e63f24215cd5e92": invalid UUID length: 16
```

`forgejo-runner one-job` reads a `--uuid` and a token from a Secret and reuses that one identity
across every ephemeral pod — the documented KEDA-Forgejo pattern (a static, shared, *non*-ephemeral
runner registration). But the stored `uuid` was sixteen hex characters, not a 36-character UUID. It
had been **seeded from the retired SOPS secret** during the great [migration off
SOPS](2026-06-12-the-long-goodbye-to-sops.md), and whatever was in that field had never been a valid
runner identity. The runner had nothing to register *as*.

There was no provisioner for it, either — the CI-bot token had one, the *runner registration* did
not. So this door took the most actual work: a Tier-1 idempotent Job
([the bootstrap pattern](../adr/adr-0019-bootstrap-task-pattern.md), mirroring the CI-bot
provisioner) that registers one persistent global runner through Forgejo's admin API
(`POST /api/v1/admin/actions/runners`, `ephemeral: false` — an *ephemeral* registration gets deleted
by Forgejo after one job, which would shatter a shared identity), captures the server-issued UUID and
token, and writes them into the Secret. It no-ops when the stored UUID already looks real. The Secret
stopped being ESO-managed and became provisioner-owned — the same model as the CI token: a *minted*
credential, not a stored one. (The previous read-only-mirror seed loop is also why it kept reappearing
malformed.)

The provisioner ran, registered `keda-global-docker`, wrote a real 36-character UUID — and a runner
pod finally fetched `task 1 repo webgrip/infrastructure` and ran it.

## Door 4 — host-mode forgets where Node lives

The runner ran the job. The job failed:

```
⭐ Run Main Checkout Repository
Cannot find: node in PATH
❌  Failure - Post Checkout Repository
```

This one the manifest *predicted*. Topology A runs steps **host-mode** — inside the toolchain
container itself (so they share the pod netns with the dind sidecar and reach the daemon at
`localhost:2376` for free). But JavaScript actions — `actions/checkout`, `tj-actions/changed-files` —
need `node`, and the `github-runner` toolchain image bundles Node under the actions-runner
`externals/` directory *without putting it on `PATH`*. A pull of the image confirms it:
`/home/runner/externals/node20/bin/node` (v20.20.2) and `node24` are right there, executable, just
not findable. The fix is a single line in the runner's command — prepend
`/home/runner/externals/node20/bin` to `PATH` before exec'ing the agent — and the JS actions resolve.

Four doors. The runner now registers, schedules, admits, finds Node, and runs real jobs end to end.
ADR-0008's "prove the runner first" — the prerequisite the whole rootless-BuildKit plan waits behind —
is, at last, actually true.

---

## The room behind the doors: a read-only mirror

With the runner working, the workflow ran far enough to fail on its own terms — first a small bug,
then the big one.

The small one: the release job's only step was a local `uses: ./.forgejo/actions/...` composite
action, with **no `actions/checkout` before it**. A local action needs the repo on disk; the
workspace starts empty; the runner couldn't read the action's `action.yml`
(`failed to read action ... no files found`). Each ephemeral job is a fresh pod, so *every* job that
uses a local action has to check out first — the `.github` twin did, the `.forgejo` one had dropped
the step. One commit restored it.

And then, the big one — the plot twist the first post set up three different times:

```
[semantic-release] ✘  The command "git push ... HEAD:main" failed:
  remote: mirror repository is read-only
  fatal: ... The requested URL returned error: 403.
```

`semantic-release` cuts a release by **pushing a git tag**. But `webgrip/infrastructure` on Forgejo
is a **read-only pull-mirror** — gitea-mirror keeps it in sync *from* GitHub, and you cannot push to
a mirror. The [Renovate section](2026-06-12-bringing-the-forge-home.md) of the first post named this
exact ouroboros — *"Renovate can only open a pull request against a repo it can push branches to, and
you cannot push to a pull-mirror"* — and here it was again, wearing a release tag instead of a PR.
It's not even fixable in place: even if the mirror *were* writable, the next 8-hour sync would
force-overwrite any tag Forgejo created. **"Forgejo runs the write-back CI" and "Forgejo holds a
read-only mirror" are mutually exclusive.**

Which forced the decision the migration was always going to reach, just sooner than planned for this
repo: stop mirroring it, and make Forgejo *authoritative*. That's [ADR-0024](../adr/adr-0024-forgejo-leading-application-repos.md) —
de-mirror, convert the Forgejo repo to a normal writable one, re-point `origin` at Forgejo and demote
GitHub to a named `github` remote, archive GitHub later. `webgrip/infrastructure` is the first repo
through it. Content-first, cutover-last, exactly as the umbilical section promised — only now the
"cutover" has started, one repo at a time, beginning with the one whose CI needed to write home.

---

## A warm runner, and the cost of a warm runner

One more change, small and worth it: a **warm pool**. Scale-from-zero is elegant and free, but it
means the first job after an idle stretch waits for a pod to schedule, a dind daemon to boot, and a
runner to register — cold every time. KEDA's `ScaledJob` supports a `minReplicaCount`, which keeps N
runners running permanently; the natural ask is "keep a couple warm so routine jobs start instantly,
and still burst higher under load."

It needed one companion change that isn't obvious. A scale-from-zero pod is only ever created when a
job is *already* pending, so `one-job` finds work immediately. A *warm* pod starts with **no** job
waiting — and without `--wait`, `one-job` would see an empty queue and exit instantly, and KEDA would
spawn a replacement, and you'd have a hot-loop of pods being born and dying. The `--wait` flag makes
the agent *block until Forgejo assigns a task* — harmless for burst pods, essential for warm ones.
With `minReplicaCount` and `--wait` together, a warm runner sits patiently blocked, grabs the next
job the instant it lands, runs it, exits, and KEDA backfills.

The honest footnote is capacity. The runners are pinned to the `fringe` nodegroup, and right now
that's **one node**. Asking for two warm runners got one `Running` and one stuck
`Pending: Insufficient memory` — two privileged dind pods (each able to balloon to gigabytes) don't
both fit alongside everything else on a single workstation-class node. Given this cluster's
[history with memory pressure](2026-06-09-longhorn-oom-cascade.md), the right move was not to shave
requests until it wedged in, but to set the warm pool to **one** and write down *why* — bump it back
when `fringe` grows. A warm pool is a comfort you pay rent on.

---

## Field notes

The condensed version, in the spirit of the first post's collection — each one green in CI, red only
at runtime:

- **"Job not picked up" is rarely the scaler.** Read the ScaledJob `status` (`triggersActivity`) and
  the KEDA operator log *before* suspecting KEDA. Here the scaler was right every time; four different
  things downstream were wrong.
- **A privileged workload in an app namespace has two locks, not one** — a Kyverno
  `PolicyException` *and* `pod-security.kubernetes.io/enforce: privileged` on the namespace. The PSA
  label is injected by a Kyverno mutate, so it won't be in your namespace manifest; `kubectl get ns
  <ns> -o jsonpath` to see what's actually live.
- **A runner Job completing `1/1` does not mean the workflow passed.** `forgejo-runner one-job` exits
  0 after running its one job *even if that job failed* — the pass/fail lives in the Forgejo job log,
  not the pod's. Don't read green pods as green builds.
- **`one-job --uuid` wants a 36-char UUID**, not the 16-hex first-half of an ephemeral-runner secret.
  If a credential was seeded from an old secret store, verify its *shape*, not just its presence.
- **Host-mode runners need `node` on `PATH`.** The actions-runner base bundles it under
  `externals/node20/bin`; nothing puts it on `PATH` for you.
- **Local `uses: ./...` actions require `actions/checkout` first**, in *every* job that uses them —
  fresh ephemeral pods start with an empty workspace.
- **You cannot push to a pull-mirror.** Any repo whose in-cluster CI writes back (releases, Renovate
  branches) has to stop being a mirror and become authoritative first. It is the same wall, every
  time.
- **The runner has no CPU limit, so the speed lever isn't a CPU cap.** Neither the `runner` nor the
  `dind` container sets a CPU *limit* — a lone job is free to use the whole idle node. The constraint
  under contention is the CPU *request*, plus the cold start every scale-from-zero job pays. Don't
  "fix CI speed" by raising a limit that doesn't exist.
- **The dominant CI cost was emulated arm64, not action clones.** The shared build composite defaulted
  to `linux/amd64,linux/arm64`; this cluster is amd64-only Talos, so every image spent minutes
  building an arm64 artifact *nothing here runs*, under QEMU. Defaulting builds to `linux/amd64` and
  gating `setup-qemu-action` behind a non-amd64 request ([ADR-0036](../adr/adr-0036-amd64-default-constrictor-build.md))
  is the single biggest, lowest-risk speedup — far ahead of caching action checkouts. (A caller that
  passes an explicit `platforms: "linux/amd64,linux/arm64"` defeats the gate, so the caller's
  `platforms` has to change too.)
- **There is no action "offline mode" to lean on.** `forgejo-runner` 12.10.2 exposes no way to skip
  re-fetching already-cached actions at any layer — `exec` has *stripped* upstream act's
  `--action-offline-mode`, and even a warm baked `~/.cache/act` `git fetch`es every job. So the
  action-clone wall is measure-first, not pre-bake-first
  ([ADR-0035](../adr/adr-0035-action-clone-wall.md)): ship the amd64 fix, re-time, and only then
  consider a scoped LAN mirror of the handful of build actions.

---

## Where this leaves us

The [status board](2026-06-12-bringing-the-forge-home.md) from the first post had the runner as
*"Live, unproven on a real job."* It can be amended: **proven.** It registers a real identity,
clears both privileged gates, keeps a warm runner ready, and runs `webgrip/infrastructure`'s jobs end
to end. The image-release path is unblocked the moment the repo finishes becoming authoritative —
which is no longer a someday-cutover but an in-progress one, started here.

Two things are still honest about being unfinished. The runner is still **privileged**; ADR-0008's
destination — a shared, rootless BuildKit reached as a Service — is unchanged, and step one (this
one) was always the prerequisite, not the goal. And the cutover has *begun*, not finished: one repo
de-mirrored, the rest still pull-mirrors, and the `homelab-cluster` repo — the GitOps source, the one
that describes the cluster, the one [gitea-mirror could never finish mirroring](2026-06-12-bringing-the-forge-home.md) —
deliberately last of all.

The day-to-day shape of it, written down for the next person, is the [Forgejo runner
runbook](../runbooks/forgejo-runner.md): how it scales, how the identity is minted, the two gates,
and the whole table of failures above with their fixes.

One last honest note on *watching* the thing now that it runs. The runner pods' logs **are** in Loki —
the Alloy pipeline carries `namespace`/`pod`/`container` labels, so `{namespace="forgejo",
pod=~"forgejo-runner.*"}` is a real LogQL query — though what you'll find there is mostly the `dind`
daemon's lifecycle; a *job's* pass/fail still lives in the Forgejo job log, not the pod's stdout, and
`forgejo-runner one-job` exits 0 after running its one job even when that job *failed*. What's missing
is *timing*: Forgejo's `/metrics` is `gitea_*` count gauges only (repos, releases, users…), with no
run-duration or job-status series, so a "where does CI time go" dashboard can't come from native
metrics — it needs a custom exporter against the Forgejo Actions API. That's the next receipt to
collect.

Because the tax the first post named — *the ordinary cost of owning the stack instead of renting it* —
doesn't get paid once. It gets paid one runtime surprise at a time. The receipts are the point.
