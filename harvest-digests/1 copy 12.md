Thread Digest: Talos hardware docs, the layered-hardware RFC, and node-add (worker-1)
One-line summary: Captured live Talos node hardware specs into the repo docs, authored an elaborate "Layered Hardware Architecture" RFC, corrected an etcd/HA misconception, added a new node (worker-1) to all hardware docs, then committed+pushed.
Approx date / status: 2026-06-19 → 2026-06-26 — done (committed b5d6fb9, pushed to main).

Items
[PROCEDURE] Read Talos node hardware via read-only talosctl get COSI resources
Type: PROCEDURE
Verification: [VERIFIED]
What: Hardware specs come from read-only COSI resources, queryable for all nodes at once. meminfo is NOT a valid resource (use kubectl capacity instead). Authoritative running Talos version is talosctl version (Server Tag:), not just the kubectl osImage field.
Why it matters: Reproducible, safe (no machine-config touch), and the canonical way to inventory hardware on Talos (which has no shell/SSH).
Snippet:

TC=talos/clusterconfig/talosconfig
NODES=10.0.0.20,10.0.0.21,10.0.0.22,10.0.0.23,10.0.0.24
mise exec -- talosctl --talosconfig "$TC" -n "$NODES" get systeminformation  # chassis / board / SKU
mise exec -- talosctl --talosconfig "$TC" -n "$NODES" get processors         # CPU model, cores, threads
mise exec -- talosctl --talosconfig "$TC" -n "$NODES" get memorymodules      # per-DIMM size + vendor
mise exec -- talosctl --talosconfig "$TC" -n "$NODES" get disks              # keep transport=sata for physical
mise exec -- kubectl get nodes -o wide                                       # capacity / kernel / kubelet
mise exec -- talosctl --talosconfig "$TC" -n <ip> version                    # authoritative running Talos
Suggested home: existing-skill (talos) + doc (docs/techdocs/docs/general/talos-cluster.md "Re-capturing hardware specs")
[GOTCHA] talosctl get disks is dominated by Longhorn iSCSI virtual disks; only transport: sata is physical
Type: GOTCHA
Verification: [VERIFIED]
What: Every Longhorn replica attaches to its node as an iSCSI VIRTUAL-DISK (via the iscsi-tools extension), so get disks is mostly noise. Runtime /dev/sdX letters are unstable (shift as volumes attach/detach). Only transport: sata rows are real hardware. installDisk: in talconfig is an install-time selector only — never a runtime identifier.
Why it matters: Reading the raw disk list naively misreports hardware and tempts brittle automation keyed on sdX letters.
Snippet: ... get disks | grep -viE 'iscsi|loop'
Suggested home: existing-skill (talos) / longhorn skill
[FACT] Talos node hardware inventory (5 nodes) and version skew
Type: FACT
Verification: [VERIFIED]
What:
soyo-1/2/3 (10.0.0.20/.21/.22, control-plane+etcd, schedulable): Intel N150 4C/4T, 12 GiB (4×3 GiB Samsung LPDDR5 soldered), 512 GB SATA SSD (WUXIN G15, not NVMe — earlier docs were wrong). SMBIOS reports Default string. soyo-3 hostname flaky → address by IP.
fringe-workstation (10.0.0.23, worker): HP Z230, i7-4770 4C/8T, 16 GiB DDR3-1600 (8+4+4 Micron, 1 slot free), 256 GB Micron SSD + 1 TB Seagate HDD + DVD.
worker-1 (10.0.0.24, worker, added 2026-06-19): Gigabyte Z87X-D3H, i5-4670K 4C/4T (no HT), 24 GiB DDR3-1600 (2×8+2×4 Crucial Ballistix, all slots full — most RAM in cluster), 960 GB Netac SATA SSD, installDisk: /dev/sda, controlPlane: false.
Versions: soyo/fringe run Talos v1.13.2 / kernel 6.18.29 / containerd 2.2.3; worker-1 runs v1.13.3 / 6.18.33 / 2.2.4. talenv.yaml declares v1.13.3 → the 4 older nodes have a pending upgrade. kubelet v1.36.1 everywhere. Totals: 5 nodes, 24 vCPU / ~76 GiB.
Why it matters: Capacity/placement decisions; the v1.13.2-vs-declared-v1.13.3 skew is real (verified twice), not a doc error.
Snippet: none
Suggested home: doc (already in talos-cluster.md, README, .claude/skills/talos/SKILL.md)
[FACT] etcd quorum / control-plane HA — the numbers
Type: FACT
Verification: [ASSERTED] (textbook-correct; failover not exercised in-thread)
What: etcd uses Raft; a change needs a majority (quorum = ⌊N/2⌋+1). Failures tolerated = N − quorum. 1→0, 2→0, 3→1, 4→1, 5→2. Use odd counts only (even adds failure surface for no gain). 3 control-plane nodes is the HA minimum; dropping to 1 is strictly less resilient (any reboot/disk-fill = whole API down) and there is currently no automated etcd backup (roadmap #52), so a single-CP disk loss is unrecoverable.
Why it matters: Corrects the intuition "3 soyos feels fragile, go to 1." The fragility is correlated failure (3 identical, RAM-starved, shared-disk boxes fail together) + etcd's sensitivity to fsync latency when Longhorn saturates the shared SSD (→ leader-election flapping) — not the node count. Fix = isolate etcd (own disk), stop heavy workloads on CP nodes, add etcd backups; not fewer nodes.
Snippet: none
Suggested home: existing-skill (talos) or runbook (docs/techdocs/docs/runbooks/etcd-health.md)
[DECISION] "All storage on one node" trades correlated-failure for a SPOF; real fix is a 2nd independent worker
Type: DECISION
Verification: [ASSERTED]
What: Moving all Longhorn storage onto one node (fringe) stabilises etcd but makes that node a single point of failure for all stateful data (one reboot = all DBs down; one disk death = data loss). With 4 nodes + one disk/soyo you cannot have both etcd-isolation and cross-node storage redundancy. worker-1 is the "second independent worker" that lets Longhorn keep replicas on separate machines. Sequencing: backups first → unburden soyos toward workers → add a node → rebalance replicas.
Why it matters: Resilience needs replicas across ≥2 independent nodes; concentrating storage is a different (often worse) fragility, not a fix.
Snippet: none
Suggested home: doc (the RFC, rfc-layered-hardware-architecture.md)
[REFERENCE] RFC authoring + wiring conventions in docs/techdocs
Type: REFERENCE
Verification: [VERIFIED]
What: RFC file = docs/techdocs/docs/rfc/rfc-<slug>.md (kebab-case, no year). No YAML front-matter; open with # RFC: Title then a > Status: **Proposed.** blockquote TL;DR. Section order: Why → Scope/Decisions (table linking ADRs) → Architecture (mermaid) → Implementation (phased) → Risks → Success criteria → References. ADRs link back with > Status: … · Part of [RFC: …]. Wiring a new RFC requires three edits: (1) mkdocs.yml nav: RFCs block (alphabetical by slug); (2) mkdocs.yml redirect_maps ('architecture/rfc-<slug>.md': 'rfc/rfc-<slug>.md'); (3) a row in docs/techdocs/docs/adr/index.md "### RFCs" table — NOT rfc/index.md (which is just a title). Next ADR number is 0025 (last is 0024); decisions get an ADR number only when ratified — list pending ones as "candidate ADRs" unnumbered.
Why it matters: Matches house style and keeps the doc discoverable (nav + redirects + index).
Snippet: adr/index.md Conventions still say location docs/techdocs/docs/architecture/, but actual files live in adr/ + rfc/ with redirects (stale convention text).
Suggested home: new-skill (rfc-authoring) or doc
[GOTCHA] Mermaid in Backstage TechDocs: flat node-chains render; subgraph-chaining + commas-in-labels + & break it
Type: GOTCHA
Verification: [ASSERTED] (user reported original broken; fix matches known-good diagrams but wasn't rendered locally)
What: Mermaid is rendered via pymdownx.superfences custom_fences. A diagram that chained subgraph IDs (L0 --> L1 --> …) and used commas inside node labels broke. Known-good diagrams (e.g. rfc-harbor-registry.md) use: simple/unquoted labels, <br/> for line breaks, · separators, and node chains, not subgraph chains. Avoid & (it's mermaid's node-list operator) and commas in unquoted labels.
Why it matters: Saves a broken-render round-trip; gives a safe template.
Snippet:

flowchart TB
  L0[L0 · Power and environment<br/>UPS A/B · PDU · OOB · ECC]
  L1[L1 · Network fabric<br/>workload plane · dedicated storage plane]
  L0 --> L1
Suggested home: doc (a techdocs/mermaid note) or skillsmith/docs guidance
[GOTCHA] mkdocs is not installed locally — TechDocs builds in-cluster (Backstage)
Type: GOTCHA
Verification: [VERIFIED]
What: mise exec -- mkdocs build fails with mkdocs couldn't exec process: No such file or directory. There is no local mkdocs; TechDocs is built by Backstage in-cluster. So mkdocs build --strict is unavailable for local verification — fall back to a relative-link existence check.
Why it matters: Don't waste time trying to build docs locally; use the link check instead.
Snippet:

# from the doc's directory; verifies every relative markdown link target exists
grep -oE ']\([^)]+\)' "$f" | sed -E 's/^\]\(//; s/\)$//; s/#.*$//' | sort -u | while read -r t; do
  [ -z "$t" ] && continue; case "$t" in http*) continue;; esac
  [ -f "$t" ] && echo "OK $t" || echo "MISS $t"; done
Suggested home: CLAUDE.md or doc (techdocs contributing notes)
[REFERENCE] Repo markdown-lint expectations (IDE diagnostics)
Type: REFERENCE
Verification: [VERIFIED]
What: IDE markdownlint flags: MD049 emphasis must use underscores _x_ not *x* (note: existing RFCs use * — inconsistent, but the linter wants _); MD031 blank lines around fenced code blocks; MD007 2-space list indent; MD060 table separators |---|---| flagged as "compact" (this is repo-wide style — leave as-is). These are editor warnings, not confirmed CI-enforced.
Why it matters: Keeps new markdown lint-clean and consistent with neighbors; avoids "fixing" pre-existing repo-wide style.
Snippet: none
Suggested home: CLAUDE.md or doc
[REFERENCE] Commit/push workflow (verified end-to-end)
Type: REFERENCE
Verification: [VERIFIED]
What: Commit with git -c commit.gpgsign=false commit. A lefthook pre-commit runs format-yaml (also format-mise/zizmor/format-just, skipped when no matching staged files). Trunk-based: commit + push directly to main. Remote is GitHub (github.com/webgrip/homelab-cluster) despite the broader Forgejo migration. Co-author trailer: Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>. Docs-only changes don't need ./scripts/run-flux-local-test.sh (that's for manifests).
Why it matters: Reliable, hook-aware commit path; confirms which remote main pushes to.
Snippet: git push origin main → 332aad6..b5d6fb9 main -> main
Suggested home: CLAUDE.md (partially present)
[PREFERENCE] User profile: NL-based, fast-learning hardware beginner; EU sourcing; power-cost-weighted
Type: PREFERENCE
Verification: [VERIFIED] (stated by user; saved to memory user-nl-hardware-learner.md)
What: User is in the Netherlands, a hardware beginner who learns fast — explain jargon, teach, still aim high-end. Source within the EU (Tweakers Vraag & Aanbod, Marktplaats, Kleinanzeigen DE, FS.com EU warehouse, Alternate.nl/Azerty); avoid US channels (21% VAT + import). Power cost dominates: heuristic 1 continuous watt ≈ 8.76 kWh/yr ≈ ~€3/yr at ~€0.35/kWh → favor perf-per-watt / low-power builds; many NL homes lack a garage so quiet matters.
Why it matters: Shapes all hardware advice toward low-power, EU-sourced options.
Snippet: none
Suggested home: memory (already saved)
[PREFERENCE] Don't over-emphasize location/NL in deliverables — one line/comment is enough
Type: PREFERENCE
Verification: [VERIFIED]
What: When location/regional context is relevant, note it once (a single line or an HTML comment), not woven through every heading/table/section. User explicitly pushed back on NL being mentioned "everywhere."
Why it matters: Keeps docs general and uncluttered; avoids belaboring context.
Snippet: <!-- Cost figures assume NL electricity at ~€0.35/kWh; scale to your own rate. -->
Suggested home: memory (folded into user-nl-hardware-learner.md)
[PROCEDURE] Adding a Talos node is GitOps via talconfig (worker-1 example)
Type: PROCEDURE
Verification: [VERIFIED] (node present and Ready)
What: A node is added by an entry in talos/talconfig.yaml nodes: (hostname, ipAddress, installDisk, controlPlane: true|false, MAC deviceSelector) plus a generated talos/clusterconfig/kubernetes-<name>.yaml. worker-1 joined this way (controlPlane: false, installDisk: /dev/sda). The node's generate-config also touched talos/clusterconfig/.gitignore — that's a config artifact, kept separate from docs commits.
Why it matters: Confirms the add-node flow and that config artifacts shouldn't be bundled into docs commits.
Snippet: node IPs: soyo-1 .20, soyo-2 .21, soyo-3 .22, fringe .23, worker-1 .24; talosconfig at talos/clusterconfig/talosconfig
Suggested home: existing-skill (talos)
Open questions / unfinished
Talos v1.13.2 → v1.13.3 upgrade pending on soyo-1/2/3 + fringe (talenv declares 1.13.3; only worker-1 is on it). [OPEN]
No automated etcd backup yet (roadmap #52) — prerequisite before concentrating storage or single-CP risk. [OPEN]
Untracked HANDOFF-storage-and-node-strategy.md at repo root (origin unknown; intentionally not committed) and modified talos/clusterconfig/.gitignore (worker-1 artifact) left uncommitted — owner to decide. [OPEN]
Whether to actually rebalance Longhorn to use worker-1 as a second replica home (the resilience win) — not yet done. [OPEN]
worker-1 still has the USB Talos installer stick attached (sdb, 7.7 GB) — can be removed. [OPEN]
Explicit preferences/feedback I gave
I'm in the Netherlands; account for EU availability/sourcing and power cost.
I'm a hardware beginner who learns fast — explain jargon, teach, but still aim for the best.
Don't make a huge deal of the NL angle — a single comment line is enough, not everywhere.
Double-check claims against the live cluster before trusting them (e.g. the Talos version) — then commit + push the docs.
