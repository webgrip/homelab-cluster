Thread Digest: Rightsizing Forgejo CI runners for speed
One-line summary: Used Grafana/Prometheus to diagnose why Forgejo CI runners feel slow, rightsized their pod resources + KEDA scaling, and backed out a base-image caching mechanism that collided with a concurrently-landed Accepted RFC.
Approx date / status: 2026-06-25 — done (resource rightsize shipped as commit 04c6151; caching half deferred to the RFC track).

Items
[FACT] Forgejo runner is a KEDA ScaledJob with a 3-container ephemeral pod
Type: FACT
Verification: [VERIFIED] (read manifests + live pods_top)
What: The runner lives at kubernetes/apps/forgejo/forgejo-runner/ (namespace forgejo), deployed as a keda.sh/v1alpha1 ScaledJob (no HelmRelease). Each ephemeral pod = init runner-bin (copies the forgejo-runner static binary from code.forgejo.org/forgejo/runner:12.10.2 into a shared emptyDir) + native-sidecar init dind (docker:29.5.3-dind, privileged) + main runner (ghcr.io/webgrip/github-runner, toolchain w/ docker CLI+buildx, git, php, dotnet). Steps run host-mode inside the main runner container (config label docker:host); it reaches the dind daemon at DOCKER_HOST=tcp://localhost:2376 over the shared pod netns. capacity: 1 job/pod; all volumes emptyDir (nothing persists between jobs). This is "Topology A, host-mode" per ADR-0008.
Why it matters: Orients any future change to the runner; explains why every job is a cold start.
Snippet: kubernetes/apps/forgejo/forgejo-runner/app/scaledjob.yaml, configmap.yaml, ks.yaml, kustomization.yaml
Suggested home: existing-skill (or the docs/techdocs/docs/runbooks/forgejo-runner.md runbook)
[FACT] Worker-pool node shape: fringe-workstation 8c/15Gi + worker-1 4c; soyo-1/2/3 are control-plane
Type: FACT
Verification: [VERIFIED] (kube_node_status_allocatable{resource="cpu"} query)
What: Allocatable CPU per node: fringe-workstation=7.95 cores (~15.96 GB mem), worker-1=3.95, soyo-1/soyo-2/soyo-3=3.95 each. The runner's nodeSelector node.webgrip.io/pool: worker selects fringe-workstation + worker-1; soyo nodes are control-plane/etcd (not worker pool). In practice runner pods land on fringe-workstation (the high-CPU node), which was only ~1.5 cores used (big headroom).
Why it matters: Bounds how aggressive resource requests can be vs. concurrency; fringe is the only 8-core node.
Snippet: kube_node_status_allocatable{resource="cpu"} against datasource UID prometheus
Suggested home: memory (or workload-placement skill)
[GOTCHA] The dedicated=fringe:NoSchedule taint was retired 2026-06-19; runners now use pool=worker
Type: GOTCHA
Verification: [VERIFIED] (manifest shows nodeSelector node.webgrip.io/pool: worker; toleration still present but dormant)
What: The runner ScaledJob still carries a tolerations: dedicated=fringe NoSchedule block, but that taint was removed 2026-06-19 (talos/patches/worker/fringe-dedicated.yaml). Placement is now via nodeSelector node.webgrip.io/pool: worker. Docs/runbook that say "pinned to the fringe nodegroup" are stale.
Why it matters: Prevents confusion that the toleration is load-bearing; it is dead weight kept "for safety."
Snippet: none
Suggested home: doc (runbook — corrected this thread)
[FACT] Runners have NO CPU limit, so they are never CPU-throttled — they burst to ~1 core
Type: FACT
Verification: [VERIFIED] (live pods_top showed runner=973m during a job; 7d 3-min-avg p95 runner ~0.24 / dind ~0.70 core)
What: Neither runner nor dind sets a CPU limit (only memory limits). A live job had runner=973m and dind=313m. So the constraint on speed is not a CPU quota — it's tiny CPU requests (was 100m each) under contention, not throttling. Generous-burst posture = keep CPU limitless so a lone job uses the whole idle node.
Why it matters: Stops anyone from "fixing speed" by raising a nonexistent CPU limit; the real levers are requests + cold start.
Snippet: none
Suggested home: memory
[DECISION] Resource + scaling rightsize values (shipped in 04c6151)
Type: DECISION
Verification: [VERIFIED] (validated via ./scripts/run-flux-local-test.sh, committed + pushed)
What: Changes to scaledjob.yaml, justified by 7-day Prometheus data:
dind mem limit 4Gi → 1536Mi (peak ~649Mi = 16%; the oversized limit was inflating node memory pressure and was the real cause of a 2nd warm runner going Pending: Insufficient memory).
runner mem request 256Mi → 512Mi, limit 1Gi → 1280Mi (peak ~796Mi/1Gi = 78%, tight, zero OOM).
both CPU requests 100m → 250m (no CPU limit kept).
pollingInterval 30 → 15; minReplicaCount 1 → 2 (warm pool; capacity freed by the dind-limit cut).
maxReplicaCount kept at 6 (peak observed concurrency was only 3 of 6 over 7 days).
Why it matters: Reusable template for "rightsize a workload from metrics, not guesses"; documents the per-pod reservation (~500m CPU / ~1.0Gi).
Snippet: kubernetes/apps/forgejo/forgejo-runner/app/scaledjob.yaml
Suggested home: doc (runbook) + memory
[GOTCHA] The 2nd-warm-runner "Insufficient memory" was caused by dind's 4Gi mem LIMIT, not its request
Type: GOTCHA
Verification: [ASSERTED] (reasoned from metrics: dind request was 512Mi, peak use ~649Mi; node had headroom)
What: A stale comment said minReplicaCount was dropped 2→1 because the single fringe node lacked memory for a 2nd warm runner. Scheduling uses requests (768Mi/pod), which fit easily on a 16GB node — so the oversized 4Gi limit (plus node RAM pressure) was the actual driver. Cutting the limit to 1.5Gi unblocked warm pool = 2.
Why it matters: Distinguishes request-vs-limit effects on scheduling; over-provisioned limits can block scale-out indirectly.
Snippet: none
Suggested home: memory
[GOTCHA] Mirroring CI base-image pulls through Harbor belongs in the buildx builder config, NOT a dind ConfigMap
Type: GOTCHA
Verification: [ASSERTED] (design analysis; the dind-ConfigMap approach was built then backed out unshipped)
What: The instinct to route docker build base-image (FROM) pulls through the in-cluster Harbor pull-through cache by mounting /etc/docker/daemon.json + /etc/buildkit/buildkitd.toml into the dind sidecar is the wrong layer:
daemon.json registry-mirrors only mirrors Docker Hub (Docker limitation; ghcr/quay impossible), and only affects the classic/embedded docker driver.
buildkitd.toml is read by a standalone buildkitd — i.e. only by a docker buildx builder created with the docker-container driver, whose --config path is resolved from the runner container's filesystem (where the buildx CLI runs), not the dind container's. So a ConfigMap mounted into dind is consumed by nothing on the default path.
The CI build path uses the docker-container driver (required for the Harbor registry layer cache --cache-to/--cache-from type=registry), whose buildkitd resolves base images in a separate container. Therefore per-registry base-image mirrors must live in that builder's buildkitd config, configured in webgrip/workflows where the builder is created — not in a homelab manifest.
Why it matters: Prevents re-attempting the dind-ConfigMap dead-end; identifies the correct layer (workflows repo).
Snippet: docker buildx create --name harbor --driver docker-container --config <path-in-runner-container> --use
Suggested home: memory (already written: forgejo-runner-base-image-mirror-layer.md)
[FACT] Harbor is reachable in-cluster over plain HTTP at harbor.harbor.svc.cluster.local:80
Type: FACT
Verification: [VERIFIED] (Service/harbor ClusterIP 10.43.143.175, port 80, nginx front-end)
What: The harbor Service (nginx front-end, component=nginx) serves /v2/ and /api/ on port 80 cluster-internally. The forgejo namespace is not zero-trust, so forgejo→harbor:80 is already open. Using this name sidesteps TLS trust, external DNS, and ${SECRET_DOMAIN} substitution entirely. (External form is https://harbor.${SECRET_DOMAIN}, served by a publicly-trusted Let's Encrypt wildcard.)
Why it matters: Cleanest in-cluster target for any Harbor API/registry call from a workload.
Snippet: harbor.harbor.svc.cluster.local:80
Suggested home: memory (or harbor runbook/skill)
[FACT] Harbor pull-through proxy-cache projects already exist (ADR-0017/0018)
Type: FACT
Verification: [VERIFIED] (read harbor-proxy-config.configmap.yaml)
What: Harbor has proxy-cache projects provisioned for upstreams: dockerhub→docker.io, ghcr→ghcr.io, quay→quay.io, gcrmirror→mirror.gcr.io, k8s→registry.k8s.io, forgejo→code.forgejo.org. The Talos nodes mirror these via machine.registries (talos/patches/global/machine-registries.yaml) using https://harbor.${secretDomain}/v2/<project> + overridePath: true. This only accelerates the kubelet pulling pod images — the dind daemon (a separate Docker engine) does not use the node mirror for build-time pulls.
Why it matters: Reusable cache infra; clarifies the node-mirror-vs-dind-engine boundary.
Snippet: kubernetes/apps/harbor/harbor/app/harbor-proxy-config.configmap.yaml; talos/patches/global/machine-registries.yaml
Suggested home: doc (harbor runbook) + memory
[GOTCHA] forgejo-runner ks.yaml has NO postBuild.substituteFrom — ${SECRET_DOMAIN} will not expand there
Type: GOTCHA
Verification: [VERIFIED] (read ks.yaml)
What: kubernetes/apps/forgejo/forgejo-runner/ks.yaml has no postBuild.substituteFrom block, so Flux variable substitution (e.g. ${SECRET_DOMAIN}) does not apply to manifests under forgejo-runner/app/. Any reference needing the domain would require adding postBuild.substituteFrom: cluster-secrets to the ks.yaml; otherwise use cluster-internal service names.
Why it matters: A ${SECRET_DOMAIN} placed in these manifests would render literally/blank — silent breakage flux-local won't necessarily flag.
Snippet: kubernetes/apps/forgejo/forgejo-runner/ks.yaml
Suggested home: memory
[FACT] Forgejo runner built-in actions/cache is useless with one-job ephemeral pods
Type: FACT
Verification: [ASSERTED]
What: Setting cache.enabled: true in the runner config does nothing useful here: the forgejo-runner cache server runs in-pod and dies when the one-job pod exits, so nothing persists across jobs. It would only help with an external backend (e.g. Garage S3 at 10.0.0.110:3900). Left off; deferred.
Why it matters: Avoids a no-op config change; points at the external-backend prerequisite.
Snippet: cache.enabled: false (in configmap.yaml)
Suggested home: doc (runbook)
[DECISION] Caching/speed work is owned by Accepted RFC-ci-pipeline-performance + ADR-0035/0036 (webgrip/workflows + infrastructure)
Type: DECISION
Verification: [VERIFIED] (RFC + ADRs present in tree, status Accepted, owner Ryan, dated 2026-06-25)
What: A parallel effort diagnoses CI cold-start as (1) the action-clone wall (every action git-cloned fresh from data.forgejo.org/github.com each job, ~6 serial clones) and (2) emulated arm64 under QEMU (cluster is amd64-only). The Harbor registry layer cache (cache-from/cache-to type=registry,...:cache,mode=max,compression=zstd) already ships in the docker-build-push-registry composite. Fixes: ADR-0035 pre-bakes the docker-build action set into the github-runner image + runner offline mode (no RWX — Longhorn RWX/disallow-rwx-pvcs policy forbids it; per-node hostPath held in reserve); ADR-0036 defaults builds to linux/amd64 and gates docker/setup-qemu-action behind if: ${{ inputs.platforms != 'linux/amd64' }}, migrated constrictor-style via new -fast composite/workflow in webgrip/workflows. Pod-resource rightsizing is orthogonal and shipped separately.
Why it matters: Defines ownership boundaries; don't duplicate the layer-cache or re-solve cold start in the homelab repo.
Snippet: docs/techdocs/docs/rfc/rfc-ci-pipeline-performance.md; docs/techdocs/docs/adr/adr-0035-*.md; docs/techdocs/docs/adr/adr-0036-amd64-default-constrictor-build.md
Suggested home: memory (already pointed at)
[PROCEDURE] Query per-job resource peaks without a Prometheus series explosion
Type: PROCEDURE
Verification: [VERIFIED] (the aggregated forms returned scalars; the un-aggregated forms blew past the token limit)
What: Ephemeral pods create one series per pod, so a 7-day subquery over forgejo-runner.* returns tens of thousands of points and overflows the MCP result. Always collapse with an outer aggregator. Use quantile(...)/max(...) over a max_over_time(rate(...)[7d:3m]) subquery to get the distribution of per-job peaks as single numbers. Note a 3-min rate window smooths out sub-minute CPU bursts (it reported ~0.35 core peak while live pods_top showed 973m).
Why it matters: Reusable recipe for profiling ephemeral/Job-style workloads via the Grafana MCP.
Snippet:

# per-job peak CPU distribution (single scalars):
quantile(0.95, max_over_time(rate(container_cpu_usage_seconds_total{namespace="forgejo",pod=~"forgejo-runner.*",container="runner"}[3m])[7d:3m]))
max(max_over_time(rate(container_cpu_usage_seconds_total{namespace="forgejo",pod=~"forgejo-runner.*",container="dind"}[3m])[7d:3m]))
# peak memory (MiB), peak concurrency, throughput, OOMs:
max(max_over_time(container_memory_working_set_bytes{namespace="forgejo",pod=~"forgejo-runner.*",container="runner"}[7d])) / 1024 / 1024
max_over_time(count(container_memory_working_set_bytes{namespace="forgejo",pod=~"forgejo-runner.*",container="runner"})[7d:1m])
count(count by (pod)(max_over_time(container_start_time_seconds{namespace="forgejo",pod=~"forgejo-runner.*",container="runner"}[7d])))
sum(increase(container_oom_events_total{namespace="forgejo"}[7d])) or vector(0)
Suggested home: new-skill (or grafana-dashboard/cluster-health skill)
[REFERENCE] Grafana MCP datasource UIDs and the read-only kubernetes MCP limits
Type: REFERENCE
Verification: [VERIFIED]
What: Datasource UIDs are literally prometheus (default) and loki. The Grafana MCP query_prometheus requires datasourceUid; discover via list_datasources. The in-cluster kubernetes MCP runs as system:serviceaccount:observability:k8s-mcp-kubernetes-mcp-server with a view-scoped role: nodes_top/listing nodes is forbidden ("cannot list resource nodes at cluster scope") — query node data via Prometheus (kube_node_status_allocatable, container_cpu_usage_seconds_total{node=...}) instead. pods_top -n <ns> works.
Why it matters: Saves a failed call; node-level facts must come from Prometheus, not the k8s MCP.
Snippet: datasourceUid prometheus / loki
Suggested home: memory (or cluster-health skill)
[GOTCHA] Forgejo runner logs are NOT in Loki (OTel pipeline only)
Type: GOTCHA
Verification: [VERIFIED] (Loki pod label only listed loki-canary pods; {service_namespace="forgejo"} returned nothing)
What: Loki here uses OTel-style labels (service_name, service_namespace, deployment_environment, event_name, exporter, job, stream), not namespace/pod/container. Runner job logs don't appear in Loki, so "where does the job time go" must be read from Prometheus signals (CPU/mem/network) or the Forgejo Actions UI, not LogQL.
Why it matters: Avoids wasted LogQL attempts; sets expectations for CI-timing forensics.
Snippet: Loki label names: deployment_environment, event_name, exporter, job, pod, service_name, service_namespace, stream
Suggested home: memory
[GOTCHA] Concurrent agent landed files mid-session; git add -A swept them — stage explicit paths
Type: GOTCHA
Verification: [VERIFIED] (working tree was clean at session start; ADRs/RFC/mkdocs appeared and one ADR was renamed during the session)
What: A parallel agent created/edited rfc-ci-pipeline-performance.md, adr-0035-*.md, adr-0036-*.md, docs/techdocs/docs/adr/index.md, docs/techdocs/mkdocs.yml during this session (even renaming an ADR live). A reflexive git add -A staged all of them. Recovery: git reset -q HEAD . then git add <explicit paths> for only your own files, leaving the concurrent work untouched/uncommitted. Reinforces the existing rule: git fetch + check git rev-list --count HEAD..origin/main before pushing.
Why it matters: Prevents committing/clobbering another in-flight workstream on shared main.
Snippetःं

git reset -q HEAD .
git add kubernetes/apps/forgejo/forgejo-runner/app/scaledjob.yaml docs/techdocs/docs/runbooks/forgejo-runner.md
git fetch -q origin main && git rev-list --count HEAD..origin/main
Suggested home: memory (extends concurrent-agents-main-collisions.md) + CLAUDE.md
[REFERENCE] Repo commit/validate conventions used this thread
Type: REFERENCE
Verification: [VERIFIED] (ran; format-yaml lefthook hook executed; trunk-based push to main succeeded)
What: Validate manifests with ./scripts/run-flux-local-test.sh (builds all ~72 kustomizations; ~3–4 min). Commit with gpgsign disabled: git -c commit.gpgsign=false commit. A format-yaml lefthook pre-commit hook runs (re-git add -A + recommit if it reformats). Work trunk-based directly on main (unprotected); no feature branches/PRs. Markdown lint (MD031) wants blank lines around fenced code blocks, including inside > blockquotes.
Why it matters: Reusable commit/validation flow for this repo.
Snippet: ./scripts/run-flux-local-test.sh ; git -c commit.gpgsign=false commit
Suggested home: CLAUDE.md (already partly there)
Open questions / unfinished
[OPEN] Whether to implement per-registry base-image mirroring in the webgrip/workflows docker-container buildkitd config (offered to draft it; not started).
[OPEN] Live confirmation of the rightsizing effect (2 warm pods present, new requests applied, build wall-clock delta) was described as a verification step but not executed in-thread.
[OPEN] Forgejo actions/cache on an external Garage S3 backend remains a deferred phase-2.
Explicit preferences/feedback I gave
Wanted the runners "quite capable / fast," and chose the generous-burst posture: modest guaranteed CPU floors, no CPU cap, let a lone job burst into the idle node; trim over-provisioned reservations rather than reserve big guaranteed cores.
Approved scope "Full speedup" (resources + caching + docs), but the caching half was then deferred by me after discovering the colliding Accepted RFC — surfaced the collision and shipped only the uncontested, independent part.
