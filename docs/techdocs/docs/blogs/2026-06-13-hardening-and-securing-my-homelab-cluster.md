# Hardening and Securing My Homelab Cluster

### How a `security` namespace quietly grew into a control plane — and what happened the day we finally read its own report card

*Published 2026‑06‑13*

---

## Prologue: the namespace that became a control plane

Most homelabs treat security as a verb you apply once: install a scanner, feel virtuous, move on. This cluster went a different way, almost by accident. The `security` namespace started as a place to park External Secrets, and then — one HelmRelease at a time — it became the busiest namespace in the cluster. Today it runs ten distinct workloads, and between them they cover the four jobs a real security program has to do: **decide what's allowed in, watch what actually happens, gather evidence about what's running, and prove where the artifacts came from.**

This post is two stories braided together. The first is a tour of that stack — what's in the `security` namespace and why each piece earns its keep. The second is what happened when we pointed all of it at the cluster and read the result: **roughly 191 policy violations**, spread across eight Kyverno policies, all of them in *audit* mode. Not failures — findings. The interesting part isn't the number. It's the discipline of turning a wall of findings into a plan, and the surprising number of ways a "just fix it" instinct can quietly take a cluster down.

If you want the architectural reference, it already exists: [Building a Practical Cloud-Native Security Platform](../general/security-platform.md) is the hub doc. This is the narrative companion — the *why it looks like this* and the *what we learned reading its own report card.*

---

## A tour of the `security` namespace

The stack maps cleanly onto how security people actually think, so that's how we'll walk it.

### Secrets: the thing everything else stands on

At the bottom sits **OpenBao** — the OSS, MPL‑2.0 fork of HashiCorp Vault — and the **External Secrets Operator** (ESO) that reads from it. The whole migration off SOPS, and the design constraint that there is *no live root token and no human ever runs a `bao` command*, is its own saga: [The Long Goodbye to SOPS](2026-06-12-the-long-goodbye-to-sops.md). The one property worth repeating here, because it shapes everything above it:

> **ESO writes real, cached Kubernetes Secrets.** A backend outage blocks *creating* or *rotating* a secret; it never blocks a running pod from *reading* one.

That guarantee is what lets us treat secrets as ordinary infrastructure rather than a fragile ceremony. Rotation becomes a value written to a vault, not a `sops --encrypt` ritual with a human in the critical path. The endgame — short‑lived, per‑workload database credentials that expire on their own — is sketched in [ADR‑0010](../adr/adr-0016-openbao-dynamic-postgres-credentials.md), with the rotation model it builds on in [ADR‑0009](../adr/adr-0015-secret-rotation-model.md).

### Admission: deciding what's allowed to land

**Kyverno** is the policy engine — three admission‑controller replicas, hard‑spread one per node, running a library of policies that fall into families: pod‑security baseline, workload hardening, advanced hardening, image supply‑chain, network exposure, RBAC least‑privilege, namespace tenancy, and a governance layer that polices the policies themselves. **Policy Reporter** turns the resulting `PolicyReport` CRDs into a UI and Prometheus metrics so the findings are *visible* rather than buried in `kubectl get polr -A`.

The deliberate choice here — and the one that the rest of this post hinges on — is that nearly every policy runs in **audit** mode, not enforce. Audit mode is not timidity. It is the only honest way to learn what a policy *means* in your specific cluster before you let it start saying "no" at the worst possible moment. The maturity model is written down in [the security platform doc](../general/security-platform.md#how-to-move-from-audit-to-enforcement-without-hurting-yourself) and formalised in [RFC: Security Hardening — Closing the Loops](../rfc/rfc-security-hardening.md).

### Runtime: watching what actually happens

Two eBPF tools, intentionally complementary rather than redundant. **Falco** is the high‑level detection engine with a mature rules ecosystem; **Tetragon** is the low‑level process and kernel‑event telemetry fabric, with redaction filters so tokens and passwords never hit the export stream. Both emit Prometheus metrics and Loki‑friendly JSON. If Falco tells you "someone spawned a shell in a container," Tetragon tells you the process tree, the binary, and the lineage that got them there.

### Supply chain: proving where artifacts came from

This is the deepest layer and the one most homelabs skip. **Trivy Operator** is the evidence engine — vulnerability scans, CycloneDX SBOM generation, config audit, RBAC assessment, compliance posture against CIS/NSA/PSS — all persisted as CRDs, not a one‑shot CLI run. **Cosign + OpenBao Transit** establishes *who built an image*: the in‑cluster Forgejo CI signs every first‑party image — to **both** Harbor (LAN) and GHCR — against a single ECDSA‑P256 key (`cosign-webgrip`) that lives in OpenBao's Transit engine and never leaves it, with per‑job authorization minted from Forgejo Actions OIDC. This is *key* signing, not keyless: there is no Fulcio certificate and no Rekor transparency‑log entry (we sign with `--tlog-upload=false`, precisely to avoid leaking digests and timestamps to a public log and to keep an internet dependency out of the release path). Keyless/Fulcio assumes a public CA chain that won't trust a private Authentik anyway; the keyed equivalent with a per‑workflow identity is the honest fit for a homelab. The only place keyless verification still applies is *third‑party* `ghcr.io/kyverno/*` images, whose policy genuinely points at a public Rekor URL. **GUAC** stitches provenance, SBOMs, and vulnerabilities into a queryable graph; **Dependency‑Track** runs continuous component‑risk analysis over every SBOM; **trust‑manager** distributes CA bundles in‑cluster. The full data flow — daily SBOM upload, OCI attestation collection, the DT policy engine — is documented in the [Supply Chain Intelligence Pipeline](../general/supply-chain-pipeline.md).

The single admission gate that *consumes* all this is **Kyverno's `verifyImages`** — and it is, like everything else here, in **audit** mode, not enforce. The cluster signs its own images and is wired to verify them, but the three verify policies still have to clear one latent bug before anyone flips them to enforce: a `--tlog-upload=false` signature has no Rekor entry, yet Kyverno's bundled cosign verifies the transparency log *by default*, so each policy needs an explicit `rekor: { ignoreTlog: true }` per `verifyImages` entry or it will reject a perfectly valid signed release. Audit mode is the only reason this hasn't bitten — which is exactly the point of audit mode. That fix is the named gate in front of any audit‑to‑enforce promotion for image verification.

The honest gap, stated plainly because pretending otherwise is how security theatre starts: the verification side is ready, but the chain is only as good as the weakest pipeline that still has to *produce* its attestations — the arc runner's own image being the standing example. [ADR‑0008](../adr/adr-0026-rootless-ci-image-builds.md) tracks the related work of getting the build side rootless and attesting.

And underneath all of it, two foundations that aren't in the `security` namespace but make it possible: transparent pod‑to‑pod **WireGuard encryption via Cilium** ([ADR‑0007](../adr/adr-0004-cilium-wireguard-encryption.md)), and **Talos** giving us an immutable, drift‑resistant node OS. Identity for every human‑facing app flows through **Authentik** ([docs](../general/authentik.md)).

That's the stack. Now the report card.

---

## The report card

Point ten security tools at a cluster that grew organically and you will not get a gold star. We got **~191 findings across eight audit policies**:

| Policy | Findings | What it wants |
| --- | --- | --- |
| `workload-hardening-audit` | ~79 | resource requests/limits, `runAsNonRoot`, `seccompProfile: RuntimeDefault`, no privilege escalation |
| `namespace-tenancy-audit` | ~50 | ownership labels, a ResourceQuota, a NetworkPolicy per app namespace |
| `image-supply-chain-audit` | ~49 | digest‑pinned images from approved registries, no `:latest` |
| `workload-advanced-hardening-audit` | ~48 | drop ALL capabilities, non‑default ServiceAccount, no explicit root user/group |
| `secrets-observability-ops-audit` | ~7 | PDBs and topology spread for replicas, no secret‑like ConfigMap keys |
| `flux-governance-enforce` | ~5 | Kustomizations from the approved source; prefer OCIRepository over HelmRepository |
| `require-pod-probes-audit` | ~3 | liveness/readiness/startup probes |
| `image-attestations-audit` | ~1 | CycloneDX SBOM + SLSA provenance on first‑party images |

The instinct when you see a number like 191 is to start hammering `securityContext` blocks into manifests until it goes down. That instinct is wrong in at least three different ways, and learning *why* is the actually‑educational part of this whole exercise.

---

## The taxonomy of a fix

Before touching a single manifest, we sorted every finding into one of three buckets. This taxonomy is the single most useful thing in this post.

1. **Fix what we control.** First‑party manifests and our own HelmRelease values. If we can set a `securityContext` or pin a digest, we should — silencing it any other way is cheating.
2. **Exception the genuinely immutable.** Operator‑managed pods, ephemeral runners, charts that hard‑code their own pod spec. You cannot `runAsNonRoot` an image that refuses to start as non‑root. These get a *documented* exception — a tracked, owned decision, not a mute button.
3. **Reclassify what was never in scope.** This is the bucket nobody expects, and it turned out to be the biggest quick win.

The reason the taxonomy matters: buckets 1 and 2 pull in opposite directions, and a lazy program does too much of one. Exception everything and you have a compliant‑looking cluster that isn't hardened. Fix everything — including images that genuinely can't be hardened — and you'll fork upstream charts forever and still never hit zero. The skill is putting each finding in the right bucket and being honest about it.

---

## Lesson 1: half the battle is deciding what's even a tenant

The `namespace-tenancy-audit` policy wants every *application* namespace to declare ownership labels, hold a ResourceQuota, and have a NetworkPolicy. Reasonable. But it was firing on `cilium-secrets`, `external-secrets`, `keda`, `kyverno`, and `default` — namespaces that are platform infrastructure, not tenants. Two of them (`cilium-secrets`, `external-secrets`) don't even have a `namespace.yaml` in the repo; their operators create them.

You can't make a NetworkPolicy "fix" a namespace that shouldn't be in scope. The right fix is to **correct the policy's idea of the world**, not to bend the world to a miscalibrated policy. So the platform namespaces joined the exclusion list the policy already maintained for `cert-manager`, `observability`, and friends, and the genuine app namespaces got honest labels:

```yaml
metadata:
  name: forgejo
  labels:
    webgrip.io/owner: platform
    webgrip.io/tier: app
    webgrip.io/exposure: external   # tracks the real gateway: external for forgejo, private for game servers, internal otherwise
```

Labels on a namespace restart nothing, so this whole class of ~17 findings cleared with zero rollout risk — and the reclassification quietly dropped a pile of *other* findings (keda's and kyverno's workloads) out of scope entirely, because they were never tenant workloads to begin with. Bucket 3 paid for itself before we'd hardened a single pod.

---

## Lesson 2: an exception is a promise, not an off-switch

The cluster has a `exception-governance` policy whose entire job is to keep the exception process honest. Every `PolicyException` **must** carry an `owner` label and a human‑readable description, and **must not** use wildcard resource names. That last rule is the one that keeps an exception from silently metastasising into "we don't check this anymore."

So when CloudNativePG's operator‑managed database pods (`authentik-db-1`, `harbor-db-1`, …) showed up failing `validate-resources` and `require-image-digest` — findings we genuinely cannot fix from our manifests, because the operator owns those pods' spec — the fix was to *extend the existing CNPG exception* with named entries and a tracking note, matching the precedent already set for four other databases.

The most uncomfortable, and most educational, exception was the arc runner. Its image is `ghcr.io/webgrip/github-runner` — **ours**. So `image-attestations-audit` is *correct* to demand an SBOM and SLSA provenance. We can't satisfy that from this repo, though; the attestation has to be emitted by the image's build pipeline in another repository. The honest move isn't to pretend the finding is wrong — it's to write the exception with a description that says, in so many words, *the real fix lives in the build pipeline; remove this once it publishes attestations.* An exception that names its own expiry condition is a TODO with teeth. An exception without one is technical debt wearing a hi‑vis vest.

And one genuine false positive, worth keeping as a reminder that policies are software too: the Prometheus operator renders alert rules into a ConfigMap, and rule expressions legitimately contain the substrings `token` and `secret`. The "no secret‑like ConfigMap keys" rule can't tell a PromQL expression from a leaked credential. That one earns an exception with a clear conscience.

---

## Lesson 3: autogen, and the difference between a Deployment and its Pods

Here is the subtlety that will bite anyone doing this for the first time. Kyverno has an **autogen** feature: write a pod‑level rule, and it automatically generates sibling rules (prefixed `autogen-`) that apply to the controllers — Deployments, StatefulSets, CronJobs — so the policy is enforced at admission time on the thing you actually `kubectl apply`.

But Kyverno *also* background‑scans the live `Pod` objects against the **base** rule. So a single logical problem — say, a Deployment whose pods run as root — shows up as **two** findings: one on the `Deployment` (the `autogen-` rule) and one on the `Pod` (the base rule). An exception that only matches `kind: Deployment` with `autogen-run-as-non-root` clears the first and leaves the second stubbornly lit. We found exactly this: existing exceptions that covered the controllers but left the pods showing red, which looks for all the world like the exception "isn't working."

The lesson is mechanical but important: **to fully silence a finding for a controller‑owned workload you often have to match both the controller (autogen rule) and the Pod (base rule)** — and since pod names are generated, that means matching by *label selector*, not name. Which is exactly the case the governance policy's "no wildcard names" rule pushes you toward anyway. The constraints, it turns out, were nudging us toward the correct design the whole time.

---

## Lesson 4: the fix that would have taken the cluster down

The single most dangerous finding looked like the most boring one: *"application namespaces should have at least one NetworkPolicy."*

The cluster ships a convenient helper — a Kyverno *generate* policy that, when you label a namespace `kyverno.io/default-network-policies: "true"`, automatically creates a `default-deny` NetworkPolicy and a DNS‑allow companion. The lazy fix is obvious: slap the label on sixteen namespaces, watch the finding evaporate, ship it.

The `default-deny` it generates covers **both ingress and egress**. With Cilium enforcing, flipping that on for an app namespace severs — instantly — every flow that app depends on: to its database, to Garage S3 for backups (the [WAL‑archiving path](../runbooks/harbor.md) that, when it stalls, fills disks), to the ingress gateways, to Authentik for OIDC, to the internet. A label that *looks* like a checkbox is actually a cluster‑wide outage with a 30‑second fuse.

> Closing a finding is not the same as solving the problem the finding points at. The finding says "this namespace has no network policy." The *problem* is "we have never designed this namespace's network boundary." You cannot generate your way out of a design you haven't done.

So NetworkPolicy is the one workstream that is deliberately **not** a bulk operation. It's staged: design each namespace's real egress needs, roll out one namespace, run connectivity tests (app health, DB, OIDC login, a backup to S3), and only then move to the next — starting with a low‑dependency app like a diagram editor and ending with the high‑fan‑out ones like Authentik and Harbor. Real zero‑trust segmentation is a project, not a label. (The cluster‑wide default‑deny ambition lives in the [security hardening RFC](../rfc/rfc-security-hardening.md) for the same reason.)

---

## Lesson 5: you cannot fix everything at once — *especially* in a homelab

There's a final constraint that has nothing to do with Kyverno and everything to do with the hardware under it. Almost every "fix what we control" change adds a `securityContext` or `resources` block to a workload, and **every one of those rolls the pod.** Push thirty of them in one commit and Flux reconciles thirty rollouts simultaneously, which on memory‑tight nodes starves the kubelet, times out the storage layer's liveness probes, and cascades into volumes faulting. We know this precisely because it has happened to this cluster, and the scars are written into how the remediation is sequenced: small batches, one or two apps per commit, let Flux settle, watch the storage layer, *then* the next batch. The hardening rollout is gated on the storage being fully healthy before it even begins.

This is the homelab tax that enterprise writeups never mention. In a cloud cluster you'd never notice thirty simultaneous rollouts. On three mini PCs sharing a disk, the order and spacing of your *security improvements* is itself a reliability concern. A remediation plan that ignores blast radius isn't a plan; it's the next incident.

---

## Lesson 6: the deadlock a "fix" caused

This one we earned in full. Harbor — the container registry, eight components — was one of the "fix what we control" jobs: its chart shipped no resource limits, so several `validate-resources` findings pointed at it. Adding limits rolled the pods. And two of Harbor's components, jobservice and registry, mount **ReadWriteOnce** Longhorn volumes.

A RollingUpdate wants to bring a *new* pod up before the *old* one is gone. But a ReadWriteOnce volume can only attach to one pod at a time, so Longhorn's Multi‑Attach guard refuses the new pod, which hangs in `ContainerCreating` forever. Delete the stuck old pod to break the tie and its ReplicaSet just recreates it and re‑grabs the volume. It's a genuine deadlock — for about ten minutes, until Longhorn force‑detaches the volume and the new pod finally attaches. Annoying, transient, self‑healing.

So we "fixed" it: set the Deployment strategy to `Recreate`, which terminates the old pod before starting the new one — exactly right for a ReadWriteOnce volume. Except the goharbor chart **always** renders a `rollingUpdate` block in the Deployment spec, and Kubernetes rejects `rollingUpdate` alongside `type: Recreate` as mutually exclusive. Every Flux upgrade now failed server‑side apply, rolled back, and retried — and kept failing, for a full day, until we noticed the HelmRelease wedged in `RetriesExceeded`. (The registry served traffic the entire time on the rolled‑back config; only the GitOps loop was stuck. Small mercy.)

> A 10‑minute self‑healing blip is strictly better than a 24‑hour stall. We traded the first for the second, in the name of a fix, and learned the difference the hard way.

We reverted to RollingUpdate and let the deadlock go back to self‑healing. Two morals fell out of it. First: **a manifest that validates is not a manifest that applies.** `rollingUpdate` + `Recreate` passes every linter and `kubeconform` check we have; the API server rejects it at apply time. The only validation that counts is against a real cluster. Second: **before you "fix" an intermittent annoyance, price out the failure mode of the fix.** The deadlock cost ten minutes and healed itself. The fix cost a day and didn't.

---

## Audit to enforce: the actual point

None of this is about reaching zero. Zero is a vanity metric; a cluster with zero findings and a hundred blanket exceptions is less secure than one with fifty honest, owned, expiring exceptions and a clear burndown. The real objective is to move policies from **audit** to **enforce** — to let the cluster start saying "no" to the next root container, the next un‑pinned image, the next wildcard Role — and you can only do that safely once the existing drift is burned down and the exception process is mature enough that enforcement won't page you at 3am for something legitimate.

So the order of operations, generalised from this whole exercise:

1. **Reclassify** what was never in scope (free, instant, no rollout).
2. **Exception** the genuinely immutable — with owners and expiry conditions (free, instant, no rollout).
3. **Fix** what you control — in small, spaced batches, watching blast radius.
4. **Design** the boundaries you'd been hand‑waving (network policy, quotas) and roll them out one namespace at a time, tested.
5. **Then, and only then, enforce** the highest‑confidence controls — digest pinning, approved registries, obvious `cluster-admin` misuse — and leave the noisy ones in audit until their exception process has earned trust. Image verification carries its own pre‑condition on top of this: the three `verifyImages` policies must first gain `rekor.ignoreTlog: true` and verify a real signed release green, or enforcing them would reject the cluster's own correctly‑signed images.

Steps 1 and 2 we did in an afternoon, with zero risk, and they cleared a startling fraction of the wall. Steps 3 through 5 are the patient part — the part that, done wrong, is indistinguishable from an outage.

It's worth noting that a couple of the strongest controls were never findings to begin with, because they were enforced from day one. **RWX (`ReadWriteMany`) PVCs are denied cluster‑wide at admission** — a Kyverno policy that refuses the whole class outright, which is why "just share a volume across nodes" never makes it into a design here. And underneath everything, **transparent pod‑to‑pod WireGuard encryption via Cilium** is on for the entire cluster, not a per‑namespace opt‑in. Those didn't show up on the report card precisely because they were already saying "no."

---

## Postscript: walking the boundary, namespace by namespace

*(updated 2026‑06‑14)*

Lesson 4 promised that the NetworkPolicy work would be staged — one namespace at a time, tested, never a bulk label flip. Here is what that actually looked like, because the doing taught things the planning didn't.

Nine namespaces now run under default‑deny, each one verified before the next. Three reusable shapes emerged, and naming them is most of the battle:

1. **Static** — a thing that only serves HTTP (a diagram editor). Ingress from the gateway, DNS out, nothing else. Trivial, and the perfect first namespace to prove the machinery end to end.
2. **CNPG‑internal** — an app plus its CloudNativePG database, no internet. Add intra‑namespace egress (app → db) and egress to the LAN for the one thing the database can't live without.
3. **Internet + CNPG** — the same, but the app genuinely needs the open internet (an RSS reader fetching feeds, a workflow engine calling webhooks, a search proxy querying engines). Egress opens to `0.0.0.0/0` *except* the cluster's own pod and service ranges, so the app can reach the world but not pivot laterally to other namespaces.

The gotcha Lesson 4 only gestured at, made concrete: **every namespace with a database must allow egress to Garage S3 and the Kubernetes API, or WAL archiving silently dies** — and a database that can't archive its write‑ahead log eventually fills its disk and takes itself down. That exact outage has happened to this cluster before. So the proof that a database namespace's policy is correct isn't "the app still loads." It's `ContinuousArchiving=True`, checked *after* the policy is enforced, on every single one.

Cilium taught two things the YAML didn't predict. Gateway‑to‑backend traffic arrives **masqueraded as a node IP**, so a tight "allow the network namespace" ingress rule isn't enough on its own — you need the LAN address blocks too. (The cluster's pre‑existing searxng policy already knew this; we copied its shape rather than rediscover it.) But in the other direction, reassuringly, Cilium's socket‑level load balancing rewrites a Service's cluster IP to the backend pod *before* the egress policy is evaluated — which is why a plain "allow intra‑namespace" rule is enough for an app to reach its database through the database's Service. We confirmed that empirically on the first database app and trusted it thereafter.

Then the two crown jewels made us slow down. **authentik is the single sign‑on front door**: get its egress wrong and you don't break one app, you lock yourself out of all of them at once. We went hunting for its Redis dependency to allowlist it — and couldn't find one. No redis pod, no redis Service, nothing in the environment, no redis connection in `/proc/net/tcp` from either the server or the worker. Just postgres. Rather than gamble a tight allowlist against an SSO outage, we did the deliberately conservative thing: allow the whole in‑cluster service range (so whatever authentik talks to stays reachable), keep blocking the internet and direct cross‑namespace pod traffic, and verify against the one endpoint that cannot lie — `/-/health/ready/`, which authentik returns `200` for *only* when its database and its cache are both reachable. It returned `200`. Harbor, the registry, got the same conservative posture for the same reason: a wrong egress rule on the thing that stores all your images is not a learning experience anyone wants.

One namespace we deliberately left alone: **forgejo**, whose CI runner pulls and clones from arbitrary registries and git hosts, and may reach the in‑cluster registry by its cluster IP. A build runner is the single workload whose egress you genuinely cannot predict from a manifest — so it waits for a session where we can trigger a real CI job and watch what it actually reaches, rather than guess and find out at the worst time. Knowing which namespace *not* to automate is part of the discipline too.

---

## Scars worth keeping

- **A finding is a question, not a command.** "No NetworkPolicy" doesn't mean "add a NetworkPolicy"; it means "you never designed this boundary." Read what the instrument is actually telling you before you yank the lever — the same lesson the [SOPS migration](2026-06-12-the-long-goodbye-to-sops.md) kept teaching about backups that weren't broken and OOMs that weren't OOMs.
- **Reclassification beats remediation when the scope was wrong.** The cheapest fix for a platform namespace failing a tenancy policy is to stop calling it a tenant.
- **An exception must name its own death.** "Remove this once CI publishes attestations" is a promise. An exception with no expiry condition is permanent drift with good intentions.
- **Autogen means two findings per problem.** Clear the controller *and* the pod, or it'll look like your exception is broken when it's only half‑applied.
- **Your security improvements have a blast radius too.** On shared‑disk homelab nodes, the spacing of hardening commits is a reliability control, not a nicety.
- **A manifest that validates is not a manifest that applies.** `rollingUpdate` next to `type: Recreate` passes every schema check and is rejected by the API server. Validate against a cluster, not a linter.
- **Price the failure mode of the fix.** A ten‑minute self‑healing deadlock beat the day‑long stall we caused trying to "fix" it. Sometimes the right move is to let the transient thing be transient.
- **The proof is the dependent signal, not the front door.** "The app loads" doesn't mean its database is archiving; `ContinuousArchiving=True` does. "The login page renders" doesn't mean SSO works; `/-/health/ready/` returning `200` does. When you change a boundary, verify the thing the boundary could have broken — not the thing that's easy to click.

The `security` namespace started as somewhere to put External Secrets. It became a control plane with opinions — and the day it finally told us, in 191 numbered pieces, exactly what it thought of the rest of the cluster, the work wasn't to argue with it. It was to read carefully, sort honestly, and fix patiently. Audit mode was never the cluster being polite. It was the cluster handing us a map, and trusting us to walk it in the right order.

We've now walked most of it. The findings are addressed at the source, the database namespaces are fenced without losing their backups, the front door still opens for the people who belong and no one else, and the one workload we couldn't safely guess about is waiting honestly for the test it needs. What's left is the last, most satisfying step — turning the highest‑confidence audits to **enforce**, so the cluster stops merely *noticing* the next root container and starts refusing it at the door.

*— and the controls, slowly, are learning to say no.*
