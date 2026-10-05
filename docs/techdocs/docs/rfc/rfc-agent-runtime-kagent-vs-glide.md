# RFC: kagent or Glide for the in-cluster agent runtime

> Status: **Draft** · Date: 2026-09-27 · Owner answers recorded 2026-09-27 (see
> [Owner decisions](#owner-decisions-2026-09-27)) · Question from the owner, before VIK-1229 is built ·
> Weighs [ADR-0063](../adr/adr-0063-kagent-machine-identity.md) against the alternatives,
> including "kagent inside Glide as its sandbox".
>
> **TL;DR.** Do not build the kagent 1.0 pilot now, and do not embed kagent in Glide. When the
> read-only ops assistant is picked up (after Kubernetes 1.37; VIK-1229 is paused), build it
> as a Glide reader Role that runs in a Kata or gVisor sandbox through
> kubernetes-sigs/agent-sandbox, and reach the cluster through the MCP gateway that already
> exists. That path runs on today's Kubernetes 1.36, needs no privileged pod and no Kyverno
> exception, and keeps spend on the per-Run LiteLLM keys Ploeg already mints, with the
> requesting person named on each key. kagent 1.0 needs
> a five-step upgrade chain before it can install, then a privileged DaemonSet and two
> exceptions, and it ships no authentication. Keep ADR-0063's identity work: the person-bound
> Kubernetes read (`kagent:<email>` style prefix, read-only binding) is runtime-neutral and
> Glide needs the same thing. Re-open kagent when 1.0 is GA, Substrate stops needing
> privilege, and the cluster is on 1.37 for its own reasons.

## The question

The owner asked on 2026-09-27 for a proper comparison before VIK-1229 turns into manifests,
including one idea of his own: use kagent *in* Glide as Glide's sandboxed environment. The
values the answer is judged by are the owner's standing ones: evidence over assumption, no
SaaS in the ops path, no policy exceptions, person-bound identity, spend control, GitOps that
heals itself, and low power and complexity for a homelab.

Two capabilities are in play, and they are easy to blur:

* **Ops Q&A.** A person asks "why is X failing" and an agent reads the cluster, metrics and
  logs and answers. This is what VIK-1229 wants: read-only, interactive, the person's identity.
* **Code-writing agents.** A Work Item becomes a pull request. That is Glide's job today
  (Ploeg dispatches, Unfold is the workbench), and kagent 1.0 reaches for it too with its
  Claude Code and Codex harnesses.

## What is true today (evidence)

Read on 2026-09-27 unless marked otherwise.

| Fact | Evidence |
| --- | --- |
| Cluster runs Kubernetes `v1.36.4`, Talos `v1.13.10` | `kubectl version`; `talos/talenv.yaml` |
| Cilium chart pinned at `1.18.6` | `kubernetes/apps/kube-system/cilium/app/ocirepository.yaml`; HelmRelease `cilium` reports `cilium@1.18.6` |
| RuntimeClass `kata` exists (handler `kata`, `overhead.podFixed` 160Mi / 250m, node selector `runtime.webgrip.io/kata`) | `kubectl get runtimeclass`; `kubernetes/apps/kube-system/runtime-classes/app/kata.runtimeclass.yaml` |
| All three workers carry `runtime.webgrip.io/kata=true` and the kata-containers `3.32.0` extension | `kubectl get nodes -L runtime.webgrip.io/kata`; node label `extensions.talos.dev/kata-containers=3.32.0` on the cAdvisor series |
| The kata smoke Job passes: guest kernel `6.18.35` against host `6.18.48-talos`; guest sees 1 vCPU and `MemTotal 2166032 kB` | `kubectl -n kube-system logs kata-smoke-fqvf8`, pod on `worker-2` |
| No gVisor extension, no agent-sandbox, kagent or Substrate CRDs are installed | `kubectl get crd` has no `agents.x-k8s.io`, `kagent`, or `ate.dev` group |
| Glide is already deployed: `ploeg` (chart `0.3.0-rc.6`) and `de-vloer` (`0.3.0-rc.14`) in namespace `ploeg` | HelmReleases `ploeg/ploeg`, `ploeg/de-vloer` |
| The LiteLLM MCP gateway serves `grafana`, `victorialogs`, `kubernetes`, `opencost` (access group `observability`) and `vikunja` (`board`), with `require_key_mcp_access_defined: true` | `kubernetes/apps/ai/litellm/app/litellm-config.configmap.yaml` |
| Ploeg already has an experimental agent-sandbox executor: a launcher creates one cold `SandboxClaim` (`extensions.agents.x-k8s.io/v1beta1`), the template takes `executor.sandbox.runtimeClassName` | Glide `apps/ploeg/pkg/sandboxlaunch/launcher.go`, `apps/ploeg/docs/contracts/executor.md` § "The agent-sandbox executor", chart value `executor.sandbox.runtimeClassName: ""` |
| Unfold ADR-0013 (accepted) already chose Sandbox CRDs with warm Kata pools for its Kubernetes provisioner; it is unqualified here because the controller is not installed | Glide `apps/unfold/docs/adrs/0013-sandbox-crd-placement-with-warm-kata-pools.md`, `apps/unfold/src/runtime/sandbox.ts` (defaults `runtimeClassName` to `kata`) |

### Measured: what the pieces cost at rest

`kubectl top`, 2026-09-27:

| Workload | Memory |
| --- | --- |
| Glide, everything resident (`ploeg`, `de-vloer`, two `ploeg-db` instances, exporter) | ≈ 253 MiB |
| MCP servers already running (`k8s-mcp` 30, `mcp-grafana` 16, `mcp-victorialogs` 101) | ≈ 147 MiB |
| LiteLLM (proxy 588, db 110, valkey 4) | ≈ 702 MiB |

### Measured: the Kata sandbox

* **Start-up.** The smoke pod's `startTime` is `07:36:38Z` and its container started and
  finished at `07:36:40Z`: about two seconds from scheduled pod to a finished command inside a
  guest kernel, image already cached on the node.
* **Overhead accounting.** The per-pod VM cost is what the RuntimeClass declares, 160Mi and
  250m, which the scheduler adds on top of the pod's requests. The comment on the
  RuntimeClass records ~130–160Mi measured for Cloud Hypervisor at install time.
* **What VictoriaMetrics does not show.** cAdvisor reports the VMM under a separate
  `/kata_overhead/<sandbox>` cgroup (the smoke pods' series carry `id="/kata_overhead/…"`), and
  every sample for the three smoke pods in the last 30 days reads `0`: the pod lives about two
  seconds, shorter than a scrape. So the overhead figure is still the install-time
  measurement, not a live one. A long-lived sandbox would give a real number; this RFC did not
  create one.

Power at rest follows memory and idle CPU. Using the estate heuristic of 1 continuous watt ≈
€3.00 per year, a resident stack of about 2 GiB that idles at a few millicores costs single
euros per year in electricity. The binding cost here is not the power bill. It is memory on a
worker pool that is already too tight to lose one node (with one worker out, CNPG primaries
sit Pending on memory; Talos 1.13.10 rollout, 2026-09-26), and the number of moving parts.

## Options

1. **kagent 1.0 as ADR-0063 designs it.** Substrate actors in gVisor, `runsc` from a pinned
   tarball in Garage, a privileged `atelet` DaemonSet and two Kyverno exceptions, the beta
   `certificates.k8s.io/v1beta1` API, Kubernetes 1.37, an alpha controller with no
   authentication behind gateway OIDC plus a NetworkPolicy.
2. **kagent 0.x** (`v0.10.2`). No Substrate. Runs on 1.36 today.
3. **kagent inside Glide as its sandbox.** Glide embeds some part of kagent.
4. **Glide on agent-sandbox with Kata**, optionally gVisor through the Talos extension, plus an
   ops assistant built from a Glide reader Role and the existing MCP gateway.
5. **Seams only.** Glide agents consume kagent-tools (or the existing `k8s-mcp`) through the
   MCP gateway; A2A between Glide and a future kagent under Glide's ADR-0007.

### Option 1: kagent 1.0 pilot (ADR-0063)

What it takes before the first agent answers:

* **Upgrade chain.** talhelper replacement (archived 2026-08-26, cannot render Talos 1.14),
  then Talos 1.14, then component bumps (Cilium 1.18.6 → 1.19 → 1.20, Longhorn, cert-manager,
  ESO, Envoy Gateway, KEDA, kube-state-metrics), then Kubernetes 1.37. The last step is itself
  blocked: Cilium 1.20 is e2e-tested on Kubernetes 1.33 to 1.36
  ([compatibility, v1.20](https://docs.cilium.io/en/v1.20/network/kubernetes/compatibility/)); only
  the 1.21 development docs list 1.37, and the newest 1.21 tag is `v1.21.0-pre.2`
  ([releases](https://github.com/cilium/cilium/releases)). Kubernetes 1.37 itself shipped on
  2026-08-26 ([release blog](https://kubernetes.io/blog/2026/08/26/kubernetes-v1-37-release/)).
  Substrate also warns that a 1.37 control plane needs kubelets on 1.36 or later
  ([substrate#1829](https://github.com/agent-substrate/substrate/pull/1829)). Every step is a node-by-node operation on a cluster whose
  N-1 capacity is already tight.
* **Privilege.** `atelet` runs `privileged: true` with hostPath `/dev`; every worker pod runs
  as root with thirteen added capabilities, seccomp and AppArmor `Unconfined`, and a hostPath
  (ADR-0063 (e), cited to `substrate v0.2.0-beta8`). That needs `pod-security-baseline-privileged`
  and `pod-security-baseline-host-path` exceptions plus four audit waivers, against the owner's
  "no policy exceptions", and it re-opens the class ADR-0053 closed for the agent plane
  ("no privileged container should exist in the agent plane at all").
* **Isolation.** gVisor, but not the gVisor a RuntimeClass gives. Substrate calls `runsc`
  itself inside a root runc worker pod, so the boundary between an actor and the
  node is gVisor's user-space kernel *inside* a root pod with `SYS_ADMIN`. The Talos gVisor
  extension cannot be used (ADR-0063, Substrate section).
* **API surface.** `certificates.k8s.io/v1beta1` on the API server for `ClusterTrustBundles`,
  a PodCertificateRequest signer running as the `default` ServiceAccount, CA and JWT pools
  from a provisioner Job.
* **Authentication.** None in the binary: `UnsecureAuthenticator` always, `X-User-Id` trusted
  as sent, actors report with `x-kagent-insecure-runtime-identity` until Substrate #1660.
  The gateway and a NetworkPolicy are the whole door.
* **Identity.** Option 1b of ADR-0063 is good design and gets the person into the Kubernetes
  audit as `kagent:<email>`. LiteLLM and MCP-gateway calls run under per-agent keys, without
  the person.
* **Spend.** Per-agent LiteLLM keys (USD 5 each, USD 10 team per 30 days) injected by
  Substrate's egress gateway. That is a budget per agent, not per run or per person.
* **Weight.** Controller, UI, kagent-tools, a Postgres for kagent, and for Substrate: a
  controller, a DaemonSet on each worker, a credential provider, an egress gateway, a
  certificate signer, a second Postgres and a snapshot bucket. Upstream's Substrate deploy guide also lists
  an Envoy router and a six-node valkey cluster, and sizes a kind lab at about 8 vCPU and 16 GB
  ([kagent blog](https://kagent.dev/blog/deploy-kagent-with-agent-substrate)). Per-component
  requests are not published (the kagent.dev docs pages returned HTTP 500 on 2026-09-27), so
  this RFC does not put a memory figure on it. At rest it is at least several times Glide's
  measured 253 MiB, on a pool that cannot spare much.
* **Maturity.** Four alphas in eight days (`v1.0.0-alpha1` 2026-09-18 to
  `alpha4` 2026-09-25, [releases](https://github.com/kagent-dev/kagent/releases)); alpha1
  removed the deployment-backed agent API outright. Substrate is pre-1.0 and says so: "We are
  not making any guarantees about backward compatibility"
  ([agent-substrate/substrate](https://github.com/agent-substrate/substrate)); upstream `v0.2.0`
  (2026-09-25) broke its API and wire protocol, and kagent ships its own fork
  ([kagent-dev/substrate](https://github.com/kagent-dev/substrate)). OSS kagent's authorizer
  allows everything ([kagent#1270](https://github.com/kagent-dev/kagent/issues/1270), open);
  OIDC login is a Solo Enterprise feature ([docs](https://docs.solo.io/kagent/latest/security/)).
  kagent is a CNCF Sandbox project since 2025-05-22, maintained by Solo.io.
* **GitOps.** Scheduled runs and agent instances live in kagent's Postgres, reachable only
  through its gRPC services; there is no `ScheduledRun` CRD, so they cannot be declared in Git
  ([kagent#2853](https://github.com/kagent-dev/kagent/issues/2853), open). The owner does not
  want scheduled runs, but instance state outside Git is still state Flux cannot heal.
* **MicroVM.** `alpha4` adds microVM sandbox support to the Harness
  ([release notes](https://github.com/kagent-dev/kagent/releases/tag/v1.0.0-alpha4)), through
  Substrate's own `ateom-microvm` with Cloud Hypervisor. That is Substrate running its own VMM,
  not a RuntimeClass, so it does not reuse the Talos Kata extension either; whether it needs
  the same privileges is unverified.
* **Capability.** Chat ops Q&A through a UI and `/mcp`. The 0.10 agent catalogue is not in
  1.0; `kagent-k8s` and `kagent-observability` have to be written as `Harness` ×
  `AgentTemplate` pairs. ScheduledRuns exist but the owner ruled out unattended runs.

### Option 2: kagent 0.x

`v0.10.2` (2026-09-23) is a maintenance release of the line alpha1 replaced. Its CRDs are
`Agent`, `ModelConfig` and `RemoteMCPServer`; each agent runs as its own Deployment, so an agent
is an ordinary unprivileged pod under the cluster's normal policies, with runc as its only
boundary. `v0.10.0` added a `SandboxAgent` CR backed by Substrate, which brings Substrate's
costs back if used ([v0.10.0 notes](https://github.com/kagent-dev/kagent/releases/tag/v0.10.0)).
`v0.10.2` wires the `trusted-proxy` authenticator its successor dropped (ADR-0063, step 1). Its
minimum Kubernetes version was not found published; nothing in it needs pod certificates.

The owner already decided against it on 2026-09-26 ("wait for kagent 1.0 on Kubernetes 1.37.
No 0.10 throwaway pilot", VIK-1229 comment 731): 1.0 is a clean break, so every CRD, agent and
identity decision made on 0.x would be rebuilt. This RFC does not reverse that; it records
that 0.x is the only kagent that runs here without an upgrade chain, and why that is not
enough.

### Option 3: kagent inside Glide as its sandbox

The idea deserves a concrete reading, because "embed kagent" can mean three different things.

| What Glide would embed | What it would do | What happens to Ploeg's model |
| --- | --- | --- |
| **(a) Agent Substrate as the runtime** under Ploeg's executor: Ploeg calls `CreateActor` instead of creating a `SandboxClaim` | Faster starts through snapshot/restore; the placeholder-credential egress gateway | Ploeg still owns lease, budget and the Run. But Substrate brings every cost of option 1 (privileged `atelet`, root workers, v1beta1 API, K8s 1.37) and its egress gateway injects one static key per hostname, which collides with Ploeg's per-Run LiteLLM keys ([ADR-0008](https://forgejo.webgrip.dev/webgrip/glide/src/branch/main/apps/ploeg/docs/adrs/0008-litellm-is-the-credential-and-metering-seam.md)): two runs against `litellm` cannot carry two different keys. Glide's landscape dossier already rules this out: "embed kagent or Agent Substrate as a dependency before v1" is on its "never" list (§10), and Substrate is "pre-1.0, breaking changes promised, heavy node install" (§6). |
| **(b) kagent Agents/Harness as the executor**: a Ploeg Run becomes a kagent agent instance | Reuse kagent's Claude Code and Codex harnesses and its UI | Two run-trackers. kagent keeps instances, sessions and history in its own Postgres; Ploeg keeps Shifts, Leases and Runs in its own. Who stops a run, who retries, whose budget is spent? kagent's budget is a static per-agent key; Ploeg's is authorized per Run and settled after ([ADR-0012](https://forgejo.webgrip.dev/webgrip/glide/src/branch/main/apps/ploeg/docs/adrs/0012-two-level-budgets-authorized-and-settled.md)), which ADR-0032 names as the one differentiator nobody else has. Embedding kagent here removes it. This is the shape Glide rejected for Paperclip and Multica ("two run-trackers", landscape §10; ADR-0009). |
| **(c) kagent-tools as MCP servers** that Glide agents call | A curated Kubernetes (and Helm, Cilium, Prometheus) tool set with a read-only mode and token pass-through | Nothing changes in Ploeg. This is a seam, not an embedding, and it is option 5. |

**What the owner would genuinely gain from (a) or (b):** a polished chat UI for ops questions
that Glide does not have; snapshot/restore starts that Kata cold starts do not match on paper
(Kata measured here at about two seconds, which already fits an interactive question); an
egress gateway that keeps credentials out of the sandbox, which Glide already reached a
different way (the worker holds credentials and proxies over loopback,
[Ploeg ADR-0034](https://forgejo.webgrip.dev/webgrip/glide/src/branch/main/apps/ploeg/docs/adrs/0034-the-harness-gets-placeholders-the-worker-keeps-credentials.md));
and harnesses maintained by someone else. Only the UI is a gain Glide cannot already claim, and
it is a front-end gap, not a runtime one.

**What it costs:** everything in option 1, plus a second source of truth for runs and a
credential model that fights Ploeg's. So: no.

### Option 4: Glide on agent-sandbox with Kata, and an ops Role

* **Runtime.** Install kubernetes-sigs/agent-sandbox `v1.0.4` (2026-09-24,
  [releases](https://github.com/kubernetes-sigs/agent-sandbox/releases)) (controller
  plus extensions) through Flux. Ploeg's sandbox executor and Unfold's provisioner both already
  speak `v1beta1`. Set `executor.sandbox.runtimeClassName: kata`.
* **Isolation.** A hardware-virtualised guest kernel per Run through the existing `kata`
  RuntimeClass, proven by the smoke Job. That is a stronger kernel boundary than Substrate's
  gVisor-inside-a-root-pod, and the pod stays unprivileged. gVisor through the Talos
  extension adds lighter reader Runs (a RuntimeClass handler `runsc`, no
  privileged pod); it is not installed yet and needs a new worker schematic (VIK-1249).
  The Talos gVisor extension (`20260831.0`, handlers `runsc` and `runsc-kvm`) needs
  `user.max_user_namespaces: "11255"`, which its own README says "disables KSPP best
  practices" ([siderolabs/extensions gvisor](https://github.com/siderolabs/extensions/tree/main/container-runtime/gvisor)).
  The owner chose both runtimes on 2026-09-27; decision D3 records what that sysctl does and
  that this cluster already sets it.
* **Networking caveat.** Cilium's eBPF socket load balancing breaks ClusterIP access from Kata
  and gVisor guests unless `socketLB.hostNamespaceOnly` is set
  ([cilium#15626](https://github.com/cilium/cilium/issues/15626), open). This cluster already
  sets `socketLB.hostNamespaceOnly: true` (`kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`),
  but the smoke Job only runs `uname`, so a Kata pod reaching a ClusterIP (LiteLLM, ploegd)
  is not yet proven. It is the first qualification check.
* **Privileges and exceptions.** None new. The worker pod is the one ADR-0053 already made
  daemonless and baseline; the agent-sandbox controller is an ordinary Deployment with
  cluster RBAC over its CRDs and pods. Upstream documents one controller
  Deployment, `agent-sandbox-controller`, and no DaemonSet
  ([kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox)). Its
  managed NetworkPolicy default allows public egress and blocks RFC 1918 and link-local;
  Ploeg's template keeps it `Unmanaged` so the cluster's own policies apply.
* **Prerequisites.** None beyond today: Kubernetes 1.36, Cilium 1.18.6.
* **Ops Q&A.** A Glide reader Role (a reader takes no Lease and never writes the tree) whose
  harness reaches the MCP gateway with its per-Run key, granted the `observability` access
  group or a narrower `glide-ops` group (grafana, victorialogs, kubernetes). A person asks in
  Unfold, gets an answer, and the Run's cost is settled against its Shift. Unfold's "session
  without a repository" (Unfold ADR-0016, PV-084) is not built yet; it is the one product gap
  on this path.
* **Identity.** Today the gateway's `kubernetes` server reads the cluster as its own
  ServiceAccount bound to `view`. That is the standing identity rfc-mcp-identity removes. The
  person-bound answer is the same work ADR-0063 already designed, moved one hop: the API server
  trusts the broker for an agent audience and maps it to a prefixed, read-only user; the
  person's token reaches the MCP server through the Ploeg worker's loopback proxy (ADR-0034),
  never through the harness. Unfold already signs people in with the broker (Unfold ADR-0016).
  None of this is built; it is not free, but it is not kagent-specific either.
* **Spend.** Per-Run LiteLLM keys with authorize-then-settle budgets, per Team and Shift,
  already in production for code-writing Runs. The person is known to Unfold; whether Ploeg
  writes the person into the key's metadata so the LiteLLM ledger names them is unverified.
  The owner requires it (D4).
* **Weight.** One more controller Deployment at rest; sandboxes exist only while a Run
  lives. Kata adds 160Mi and 250m per running sandbox. No second Postgres, no DaemonSet, no CA.
* **Maturity.** agent-sandbox is SIG Apps, `v1beta1` since 1.0 on 2026-08-28, and
  `v1.0.4` at the Glide survey of 2026-09-26. Ploeg's executor is marked experimental and warm
  pools are not supported yet (a warm pod would claim a Run before its `SandboxClaim`
  exists).
* **Capability.** Code-writing agents already; ops Q&A once the reader Role, the MCP grant and
  a repository-less session exist. No scheduled runs, which matches the owner's decision.

### Option 5: seams only

* **kagent-tools behind the MCP gateway.** kagent-tools `v0.3.0` can run standalone with
  `--read-only`, `rbac.readOnly: true`, `allowSecrets: false` and `TOKEN_PASSTHROUGH=true`
  (ADR-0063 table). It is a richer read-only Kubernetes tool set than `k8s-mcp`, and it already
  has the pass-through switch that rfc-mcp-identity needs `k8s-mcp` to gain. Registered as a
  server on the LiteLLM gateway, any agent (Claude Code on a laptop, a Glide Role, a future
  kagent) can use it. One caveat carries over from ADR-0063: on the LiteLLM hostname a key is
  injected as `Authorization`, so the person's bearer and the gateway key cannot both ride that
  header. The pass-through route has to be a direct, broker-verified route (rfc-mcp-identity
  shape), not through LiteLLM.
* **A2A.** Glide ADR-0007 keeps A2A to a north-facing facade on a watchlist, and kagent speaks
  A2A. If a kagent is ever installed, the honest seam is kagent calling Glide's facade to open a
  Work Item (the tracker stays authoritative), or Glide's agents calling a kagent agent as a
  tool. Neither is needed now.

## Comparison

| Criterion | 1. kagent 1.0 (ADR-0063) | 2. kagent 0.x | 3. kagent in Glide | 4. Glide + agent-sandbox + Kata | 5. Seams only |
| --- | --- | --- | --- | --- | --- |
| Kernel boundary per agent | gVisor, run by Substrate inside a root pod with 13 capabilities | runc (agent Deployments); Substrate gVisor only for `SandboxAgent` | As 1 (a) or as 1 (b) | Kata guest kernel (VM); optionally gVisor RuntimeClass | Whatever runs the agent |
| New privileged pods / Kyverno exceptions | `atelet` privileged; 2 exceptions + 4 audit waivers | None for plain agents; Substrate's for `SandboxAgent` | As 1 | None | None |
| Kubernetes / Cilium prerequisites | K8s 1.37, Talos 1.14, talhelper replacement, Cilium ≥ 1.20 (1.20 is tested on 1.33–1.36 only; 1.21 is at `v1.21.0-pre.2`), `certificates.k8s.io/v1beta1` | Runs on 1.36 | As 1 | None (1.36, Cilium 1.18.6) | None |
| Earliest start | After the whole upgrade chain; months | Now | After 1 | Now | Now |
| Person-bound Kubernetes read | Designed (1b), unverified live | trusted-proxy wired in 0.10.2; unverified | As 1 | Same design, one hop moved; unbuilt | Via kagent-tools pass-through on a direct route |
| Person on LiteLLM / MCP legs | No (per-agent keys) | No | No | Not yet (per-Run keys; person metadata unverified) | n/a |
| Spend control | Static per-agent key, 30-day budget | Per ModelConfig key | Collides with per-Run keys | Per-Run keys, authorize then settle | n/a |
| In-app authentication | None (alpha) | trusted-proxy (0.10.2) | As 1 | Unfold OIDC sign-in (ADR-0016) | n/a |
| Resident components | kagent controller, UI, tools, Postgres; Substrate API server, router, controller, cert controller, `atelet` on every worker, egress gateway, second Postgres, snapshot store; upstream's guide adds a 6-node valkey cluster | controller, UI, tools, Postgres | 1 plus Glide | +1 controller Deployment | +1 MCP server (optional) |
| Maturity | Alpha (`v1.0.0-alpha4`), Substrate beta | `v0.10.2` maintenance; line superseded by 1.0 | Pre-1.0 inside pre-1.0 | agent-sandbox 1.0.x `v1beta1`; Ploeg executor experimental | kagent-tools `v0.3.0` |
| Ops Q&A | Yes, with a UI | Yes, with a UI and a catalogue | Yes | After a reader Role + repo-less session | Through any client |
| Code-writing agents | Harnesses exist; no tracker, forge or spend | No | Conflicts with Ploeg | Yes, in production | n/a |
| Scheduled runs | Yes (unused by decision) | No | n/a | No (by decision) | n/a |
| Lock-in / exit cost | CRDs, Substrate, a second Postgres; 1.0 already broke 0.x | Rebuild at 1.0 | Two engines to unpick | `agents.x-k8s.io` is a SIG standard; Ploeg owns the rest | Low |
| Fit with Glide records | Beside, partially competing (landscape §6) | n/a | Violates landscape §10 "never", ADR-0009 pattern, ADR-0032 | Is ADR-0032 and Unfold ADR-0013 | ADR-0007 facade, MCP as tool seam |
| Fit with homelab records | Against ADR-0053's privileged-free agent plane | n/a | As 1 | Matches ADR-0053, ADR-0044 | Matches rfc-mcp-identity |

## Verdict

**Recommendation: option 4, with option 5's kagent-tools seam as its first increment, and
ADR-0063's identity design kept and made runtime-neutral.**

1. Install agent-sandbox through Flux and qualify Ploeg's sandbox executor with
   `runtimeClassName: kata`, then with a gVisor RuntimeClass once the worker schematic carries
   the extension (D3, VIK-1249). This is Glide's own recorded plan (ADR-0032, Unfold ADR-0013)
   and it costs no exception.
2. Build the ops assistant as a Glide reader Role with an MCP-gateway grant limited to
   grafana, victorialogs and a read-only Kubernetes server. It waits until after Kubernetes
   1.37 (D1).
3. Put the person on the Kubernetes path with ADR-0063 option 1b's shape (broker audience,
   `<prefix>:<email>`, roster-rendered read-only binding), reached through a broker-verified
   direct MCP route rather than LiteLLM. Evaluate kagent-tools in read-only pass-through mode
   as that route's server beside `k8s-mcp`.
4. Pause VIK-1229 (paused 2026-09-27, D1). Keep its research; it is the best-documented
   picture of kagent 1.0 we have.
5. Name the requesting person on every Run's LiteLLM key, so the spend ledger attributes cost
   to a person as well as to a Team and Shift (D4).

**Should Glide embed kagent as its sandbox? No.** The only part of kagent that is a sandbox is
Agent Substrate, and it arrives with a privileged node agent, root workers, a beta API and a
Kubernetes upgrade, while its one-key-per-hostname egress injection cannot carry Ploeg's
per-Run keys. Embedding kagent's agents instead gives Glide two run-trackers and throws away
authorize-then-settle spend, the one thing Glide's own survey found no other project has.
The Kata RuntimeClass the cluster already runs is a stronger boundary than Substrate's gVisor
and costs nothing new.

### What would reverse this (re-evaluation triggers)

Any one of these re-opens the comparison:

* kagent `v1.0.0` is tagged GA with in-app authentication (a verified OIDC or trusted-proxy
  mode in the shipped binary) and Substrate #1660 signed actor identities.
* Substrate runs workers without `privileged`, host paths or added capabilities, or accepts a
  `runtimeClassName` so the Talos gVisor extension (or Kata) can be used.
* Substrate moves `ClusterTrustBundles` to `certificates.k8s.io/v1`.
* The cluster reaches Kubernetes 1.37 for its own reasons (the Talos 1.14 program), so the
  upgrade chain is no longer charged to kagent.
* Substrate's egress gateway supports per-request or per-actor credentials, so a Ploeg per-Run
  key could ride it.
* Glide's agent-sandbox executor fails qualification on Kata (start-up, Cilium policy, memory)
  in a way that Substrate's snapshot model would fix, measured here.
* The owner decides unattended or scheduled ops runs are wanted after all; kagent's
  `ScheduledRuns` are then a real feature, not an unused one.

## Proposed changes (for the owner; not made by this RFC)

### Homelab

* ADR-0063: add a history line that the runtime choice is re-opened by this RFC; keep status
  proposed. Split the identity part (option 1b, token lifetime, Authentik 2026.8, the
  `email_verified` mapping fix) from the kagent runtime so it survives either verdict; the
  prefix would become an agent prefix rather than `kagent:`.
* VIK-1229: pause with a link to this RFC. VIK-1246 (upstream STS `client_id` PR) stays
  valuable to upstream but is no longer on our path. VIK-1247 (identity spike) is re-scoped to
  the MCP route and the Glide worker proxy instead of the kagent chain.
* New tickets, if accepted: install agent-sandbox via Flux; qualify Ploeg's sandbox executor
  on `kata`; a long-lived Kata sandbox measurement to replace the install-time 160Mi figure; a
  read-only Kubernetes MCP server with token pass-through on a broker-verified route
  (kagent-tools vs `k8s-mcp`); an MCP access group for the ops Role.

### Glide

Listed only; this RFC does not edit Glide.

* Ploeg ADR-0032: add that the homelab evaluated kagent-in-Glide on 2026-09-27 and rejected
  it for the same reasons, with this RFC as evidence.
* Landscape dossier §6: note that Substrate cannot use a RuntimeClass (so not the Talos gVisor
  or Kata extensions) and that its egress injection is one credential per hostname and header.
  The dossier also says kagent v0.10 builds on `agents.x-k8s.io`; the v0.10.0 release notes
  describe its `SandboxAgent` as backed by Substrate, and this research found no link between
  kagent and agent-sandbox. Worth re-checking at source before the dossier is cited again.
* Ploeg `docs/contracts/executor.md`: the note "qualify a RuntimeClass with the privileged
  DinD sidecar" predates homelab ADR-0053; with `dind: false` the qualification is the
  daemonless worker on `kata`.
* Backlog #58: mark it superseded by the existing `sandboxlaunch` executor if that is the
  intent, and add warm pools as the follow-up.
* A Role or Team for read-only ops questions, and Unfold's repository-less session (PV-084), as
  the product work behind the ops assistant.
* Put the requesting person on every per-Run LiteLLM key (D4): key metadata and LiteLLM user
  attribution, taken from the Unfold session, so the spend ledger names them.

## Owner decisions (2026-09-27)

The owner answered four of the five open questions on 2026-09-27. Question 4 (kagent-tools as a
standalone MCP server) is still open.

* **D1. The ops assistant can wait until after Kubernetes 1.37.** It is not needed before the
  cluster reaches 1.37 through the Talos 1.14 program. VIK-1229 (kagent pilot) is paused. When
  it is picked up, the Glide reader Role path of option 4 is the preferred route; kagent is
  weighed again then only if a re-evaluation trigger above has fired. Waiting removes option
  1's upgrade-chain cost, not its privilege and authentication costs, so the recommendation
  stands.
* **D2. An Unfold session counts as "the person asking".** A person signed in to Unfold behind the
  gateway OIDC login (ADR-0060) is the person for person-bound identity. A Run started from that
  session carries that person, so option 4 meets ADR-0063's no-unattended rule without a
  separate agent login.
* **D3. Runtime: Kata and gVisor.** Kata stays through the existing `kata` RuntimeClass; gVisor
  is added through the Talos `gvisor` system extension as a second RuntimeClass (handler
  `runsc`, or `runsc-kvm` on bare metal). The owner accepts the sysctl the extension needs.
  * *Which sysctl.* `user.max_user_namespaces: "11255"` under `machine.sysctls`. The extension
    README says gVisor "requires unprivileged user namespace creation, so Talos default setting
    should be overridden" and warns "This disables KSPP best practices setting"
    ([siderolabs/extensions gvisor README](https://github.com/siderolabs/extensions/blob/main/container-runtime/gvisor/README.md)).
  * *Its security effect.* KSPP recommends `user.max_user_namespaces = 0`: "Disable User
    Namespaces, as it opens up a large attack surface to unprivileged users"
    ([KSPP recommended settings](https://kspp.github.io/Recommended_Settings#sysctls)). A
    non-zero value lets any unprivileged process on the node create user namespaces, inside
    which it holds capabilities such as `CAP_SYS_ADMIN` and `CAP_NET_ADMIN` over namespaced
    kernel objects. That makes kernel code reachable (netfilter, mount and filesystem paths)
    that is otherwise root-only, which is the usual route of local privilege-escalation bugs.
    It grants no privilege outside the namespace by itself.
  * *Finding: this cluster already pays that cost.* `talos/patches/global/machine-sysctls.yaml`
    sets `user.max_user_namespaces: "11255"` on every node since the initial commit
    (`10bd396e`, 2025-12-08), applied through `talos/nodes.yaml`; reading
    `/proc/sys/user/max_user_namespaces` on worker-1 (`10.0.0.31`) with talosctl returns
    `11255` (2026-09-27). Adding gVisor changes no sysctl. The KSPP deviation already exists;
    this decision makes it load-bearing, so reverting it later would break gVisor.
  * *Schematic.* The workers run Image Factory schematic `d1200926df53…` (kata-containers
    `3.32.0`). gVisor needs a new schematic with `siderolabs/gvisor` beside kata, a
    node-by-node move of the three workers onto it, and a `RuntimeClass` that selects on a new
    `runtime.webgrip.io/gvisor` label, as the `kata` one does. Ticket: VIK-1249.
* **D4. The person appears on the LiteLLM spend ledger.** Per-Team and per-Shift attribution is
  not enough. Each Run's LiteLLM key carries the requesting person (key metadata and LiteLLM
  user attribution, from the Unfold session of D2), so spend reads per person as well as per
  Team and Shift.

## Open questions for the owner

Answered on 2026-09-27 except question 4; see [Owner decisions](#owner-decisions-2026-09-27).

1. Is ops Q&A worth having before Kubernetes 1.37, or is it fine to wait months for it? If it
   can wait, option 1 loses its main cost, but the privilege and authentication problems stay.
2. Does an Unfold session count as "the person asking" for the ops assistant, given Unfold signs
   people in through the broker? If yes, option 4 satisfies ADR-0063's no-unattended rule.
3. Kata only, or also install the Talos gVisor extension for reader Runs? Kata is proven here;
   gVisor would be a schematic change on three workers for a lighter footprint.
4. Accept kagent-tools as a standalone MCP server (read-only, pass-through) beside or instead
   of `k8s-mcp`?
5. Should the person appear on the LiteLLM spend ledger (key metadata from Unfold), or is
   per-Team and per-Shift attribution enough?

## References

* [ADR-0063](../adr/adr-0063-kagent-machine-identity.md) — kagent identity, Substrate and
  gVisor research, owner decisions rounds 1–3.
* [ADR-0053](../adr/adr-0053-daemonless-agent-plane.md) — no privileged container in the agent
  plane.
* [ADR-0044](../adr/adr-0044-metered-inference-plane-litellm.md) — LiteLLM keys and budgets.
* [ADR-0060](../adr/adr-0060-gateway-oidc-for-apps-without-a-login.md) — gateway OIDC.
* [RFC: The access plane](rfc-access-plane.md) D10 and
  [RFC: MCP endpoints carry the caller's identity](rfc-mcp-identity.md) M4/M5.
* [RFC: Dark factory](rfc-dark-factory.md).
* Glide: `apps/ploeg/docs/research/2026-09-26-agent-orchestration-landscape.md` (§2, §6, §9,
  §10), `apps/ploeg/docs/research/2026-07-28-a2a-fit.md`, Ploeg ADRs 0005, 0007, 0009, 0032,
  0034, Unfold ADRs 0013 and 0016, `apps/unfold/src/runtime/sandbox.ts`,
  `apps/ploeg/pkg/sandboxlaunch/launcher.go`.
* Vikunja: VIK-1229, VIK-1246, VIK-1247, VIK-1249.
* Upstream, read 2026-09-27: [kagent releases](https://github.com/kagent-dev/kagent/releases)
  (`v1.0.0-alpha1`…`alpha4`, `v0.10.0`…`v0.10.2`), [kagent#2853](https://github.com/kagent-dev/kagent/issues/2853),
  [kagent#1270](https://github.com/kagent-dev/kagent/issues/1270),
  [kagent-dev/tools releases](https://github.com/kagent-dev/tools/releases) (`v0.3.0`),
  [agent-substrate/substrate](https://github.com/agent-substrate/substrate) and
  [#1829](https://github.com/agent-substrate/substrate/pull/1829),
  [kubernetes-sigs/agent-sandbox releases](https://github.com/kubernetes-sigs/agent-sandbox/releases) (`v1.0.4`),
  [siderolabs/extensions](https://github.com/siderolabs/extensions) (gvisor `20260831.0`,
  kata-containers `3.32.0`), [Cilium 1.20 compatibility](https://docs.cilium.io/en/v1.20/network/kubernetes/compatibility/),
  [Kubernetes 1.37 pod certificates](https://kubernetes.io/blog/2026/08/28/kubernetes-v1-37-pod-certificates-and-cluster-trust-bundles/).
