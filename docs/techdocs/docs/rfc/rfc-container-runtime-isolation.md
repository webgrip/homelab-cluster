# RFC: Container runtime isolation — a kernel boundary for the code we do not write

> Status: **Draft** · Date: 2026-07-31 · Owner: Ryan
>
> Complements — does **not** relitigate — [ADR-0026](../adr/adr-0026-rootless-ci-image-builds.md)
> (rootless CI image builds). ADR-0026 removes *privilege* from the build engine. This RFC is about
> the *boundary* around everything the runner executes, which rootless BuildKit does not change.
>
> Sibling of [RFC: Security Hardening](rfc-security-hardening.md) and
> [RFC: Runtime detection & response](rfc-runtime-detection-response.md).

## Context

ADR-0026 lists "Keep DinD, sandbox the node (gVisor / Kata runtime class)" among its considered
options and rejects it in two lines: *"Good, because strong isolation. Bad, because a new runtime to
operate and slower builds."* That verdict is correct **for the question ADR-0026 was asking**, which
was how to build images without `privileged: true`. Rootless BuildKit answers that better than a
sandbox does.

But it leaves a different question unanswered, and this RFC exists to ask it separately:

> **Once the build engine is rootless, what still contains the arbitrary code that CI runs?**

The answer today is: Linux namespaces and cgroups, on a shared kernel. A Forgejo runner job
executes whatever is in the repository it checked out — test suites, `postinstall` scripts,
`Makefile` targets, an AI agent in `agent-runner` with a shell. It does so while holding, per job:

- a Harbor robot credential with push rights to `webgrip/*`;
- a Forgejo OIDC token exchangeable at OpenBao for **cosign signing capability**
  (`webgrip/infrastructure` ADR-0004);
- LAN reachability to Harbor, OpenBao, Dependency-Track and the Kubernetes API surface the pod can see.

That is the highest-value credential set in the estate, held by the one workload that runs code we
did not write. A container escape there is not a node compromise — it is a **supply-chain signing
compromise**, and because signing happens through OpenBao Transit (the key is non-extractable), the
attacker does not need the key. They need thirty seconds inside the job that is allowed to ask for
signatures.

Two further facts sharpen this:

1. **`ci-runner` is the worst image we publish** — 8 critical / 136 high (measured 2026-07-31,
   `webgrip/infrastructure` ADR-0005). It is also the most privileged. Those are the same image.
2. **Eight container escapes were disclosed in 2024–25** (Leaky Vessels, NVIDIAScape, the runc race
   conditions). Each was a bug in the layer we currently rely on as the boundary.

The shared-kernel container boundary is a software convention enforced by ~40M lines of C exposing
450+ syscalls. It was designed for resource isolation between cooperating workloads, and it is very
good at that. It was not designed to be a security boundary against hostile code, and every few
months it demonstrates this.

## Goals

- Give the CI runner a boundary that survives a kernel-level container escape.
- Keep OCI images and Kubernetes semantics — no rebuild of how images are produced or deployed.
- Opt in **per workload**, so the blast radius of the change is one `RuntimeClass` on one ScaledJob.
- Cost no more than single-digit percent CPU on the affected workloads.

## Non-goals

- Replacing rootless BuildKit. ADR-0026 stands; this is orthogonal and additive.
- Sandboxing the whole cluster. Most workloads here are first-party and do not need it.
- Confidential computing (memory encryption against the host operator). Different threat model,
  not ours.

## The landscape, briefly

These are not competing products at one layer, which is what makes the comparison confusing.

**Layer 1 — OCI runtimes** (what containerd exec's):

| Runtime | Model | Boundary |
| --- | --- | --- |
| `runc` | namespaces + cgroups | shared host kernel |
| `crun`, `youki` | same model, C / Rust | shared host kernel — **faster, not safer** |
| `runsc` (gVisor) | userspace kernel intercepting syscalls | ~274 reimplemented syscalls |
| `kata-runtime` | a real VM per pod | hardware (VT-x / AMD-V) |

**Layer 2 — the mechanisms:**

- **gVisor** puts a Go-written kernel between the workload and the host. The host kernel sees a
  small, tightly-constrained syscall set instead of the full 450+. ~50 ms start, **no hardware
  virtualisation required**. Cost: it implements only ~274 syscalls, so unusual workloads hit
  unimplemented features, and syscall- or IO-heavy work pays a real tax. Google Cloud Run moved its
  second generation *off* gVisor to microVMs because customers kept hitting missing kernel
  features — a directly relevant signal, since CI does unusual things (mount, ptrace, nested
  containers).
- **Kata Containers** boots a genuine lightweight VM per pod, with its own guest kernel, and runs
  the OCI image inside it. Kubernetes semantics unchanged. **Requires KVM.**
- **Firecracker** is a VMM, not a Kubernetes runtime — reached *through* Kata. ~125 ms boot, <5 MiB
  overhead, single-digit % CPU. Its security comes from what it omits: no PCI, minimal device model,
  no GPU passthrough, no nested virtualisation.
- **Cloud Hypervisor** is the richer VMM — VFIO passthrough, hotplug, nested virt — at the cost of a
  larger surface. Also a Kata backend.

**Layer 3 — outliers.** WASM (Spin, WasmEdge) is a different execution model: excellent for
plugins and functions, useless for anything that forks processes or spawns Chromium. Unikernels
remain niche. Neither is a candidate here.

## Feasibility on Talos

Talos ships all of this as first-party system extensions, which removes the "a new runtime to
operate" objection substantially — there is no package to install on a host, only a boot asset to
rebuild:

| Extension | Image | Version | Tier |
| --- | --- | --- | --- |
| gVisor | `ghcr.io/siderolabs/gvisor` | 20260714.0 | **core** |
| Kata Containers | `ghcr.io/siderolabs/kata-containers` | 3.32.0 | extra |
| Kata + AMD SEV-SNP | `ghcr.io/siderolabs/kata-containers-snp` | 3.32.0 | extra |
| Spin (WASM) | `ghcr.io/siderolabs/spin` | v0.25.1 | extra |
| WasmEdge | `ghcr.io/siderolabs/wasmedge` | v0.6.1 | extra |
| youki | `ghcr.io/siderolabs/youki` | 0.6.0 | contrib |

Extensions are baked into the boot asset via an Image Factory schematic — a node upgrade and
reboot, not a `kubectl apply`. Once installed, containerd gains the runtime handler and workloads
select it with a `RuntimeClass`. runc, gVisor and Kata can coexist on one cluster, chosen per pod.

**Node constraints for this cluster** (`talosctl get members`, 2026-07-31 — Talos v1.13.4):

- `fringe-workstation` (10.0.0.23) is bare metal — an i7-4770 (Haswell) with VT-x and EPT, so KVM is
  available and Kata is technically possible. **But** it is already the known contention point: it
  co-locates Harbor, Harbor's Postgres, the Envoy data plane and the dind DaemonSet on 8 threads and
  16 GiB, and it is the documented cause of the "Harbor outages" in runs 136/137/158. It is the
  wrong first host for a new runtime.
- `soyo-1/2/3` are control-plane (4 vCPU / ~12 GiB each); not candidates.
- `worker-1` (10.0.0.24) is the realistic target: 4 vCPU but **24 GiB RAM — the most memory in the
  cluster**, and labelled `node.webgrip.io/ram=high`. Memory headroom is what Kata wants (a guest
  kernel per pod), so the shape fits. Its virtualisation support must be confirmed before Kata is
  scheduled there — if it is a VM, nested virt must be explicitly enabled on the hypervisor. The
  node labels do not record this, which is itself worth fixing.
- **gVisor needs none of this.** It requires no hardware virtualisation and therefore no nested-virt
  question, on any node.

## Proposal

A three-wave rollout, each wave independently valuable and independently revertible.

**Wave 1 — gVisor on the low-risk runners (cheap, reversible).**
Add the `gvisor` extension (core tier) to the worker schematic. Create a `RuntimeClass` named
`gvisor`. Apply it to the runner ScaledJobs that do *not* need nested containers — the
`semantic-release` family, `techdocs`/`mkdocs`, `helm-deploy`. These are syscall-light, so the gVisor
tax is small, and they are the jobs where a failure is a re-run rather than an incident. Success
criterion: jobs pass at comparable wall-clock; no unimplemented-syscall failures over two weeks.

**Wave 2 — measure the hard cases.**
Attempt `agent-runner` and `php-ci-runner` under gVisor. `agent-runner` is the interesting one: it
runs an AI agent with shell access, which is the closest thing here to genuinely untrusted code, and
also the most likely to trip an unimplemented syscall. The output of this wave is data, not a
rollout — it tells us whether gVisor is sufficient or whether the runner tier needs Kata.

**Wave 3 — Kata for the runner tier, if Wave 2 says so.**
Add the `kata-containers` extension to `worker-1` only, once its virtualisation support is
confirmed. Move `ci-runner`-based ScaledJobs to a `kata` RuntimeClass. This is the wave that
actually addresses the 8-critical image holding signing capability. Explicitly **not** on
`fringe-workstation` until its contention is resolved.

Sequencing note: Wave 1 can start immediately and does not depend on ADR-0026 landing. Wave 3 should
follow ADR-0026's Topology C, because a rootless build engine plus a VM boundary is a much smaller
change than trying to run privileged DinD inside Kata.

## Open questions

1. Is `worker-1` bare metal or virtualised? Determines whether Wave 3 needs nested virt enabled
   upstream, or is blocked entirely.
2. Does Forgejo's ScaledJob shape survive gVisor? The runner mounts an `emptyDir` and execs heavily;
   both are fine in principle, but "in principle" is what Wave 1 exists to test.
3. What is the actual measured cost? The literature says single-digit percent for microVMs and
   "workload-dependent" for gVisor. Our builds are IO-heavy, which is gVisor's worst case. Wave 1
   must produce a real number before Wave 2 is planned.
4. Does Kata interact badly with the Harbor registry cache or the `:cache` ref flow
   (`webgrip/infrastructure` ADR-0036)?
5. Should `RuntimeClass` selection be enforced by Kyverno — i.e. a policy that *requires*
   `runtimeClassName: gvisor` in the CI namespace, so a new ScaledJob cannot silently land on runc?
   This is probably the durable end state and should become an ADR once Wave 1 proves out.

## Decision record to follow

This RFC deliberately produces **no ADR yet**. There is nothing to ratify until Wave 1 has run and
question 3 has a number attached. When it does, the expected outputs are:

- an ADR recording the `RuntimeClass` topology and which workload tier gets which boundary;
- an amendment to [ADR-0026](../adr/adr-0026-rootless-ci-image-builds.md) noting that sandboxing was
  reconsidered on its own terms and adopted as a complement, not as the alternative it was rejected
  as.

## Links

- [ADR-0026 — Rootless CI image builds](../adr/adr-0026-rootless-ci-image-builds.md)
- [ADR-0001 — Node taxonomy](../adr/adr-0001-node-taxonomy.md)
- [RFC: Security hardening](rfc-security-hardening.md)
- [RFC: Runtime detection & response](rfc-runtime-detection-response.md)
- [Talos system extensions](https://github.com/siderolabs/extensions)
- `webgrip/infrastructure` ADR-0004 (signing anchor), ADR-0005 (CVE budgets)
