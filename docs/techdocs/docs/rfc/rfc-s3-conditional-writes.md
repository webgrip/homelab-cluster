# RFC: S3 conditional writes, Garage and the alternatives

> Status: **Proposed** · Date: 2026-09-28 · Ticket: VIK-1259 · Related:
> [object storage — Garage](rfc-object-storage-garage.md) ·
> [Omnigraph runbook](../runbooks/omnigraph.md#how-it-runs)

> **TL;DR.** Garage will not get S3 conditional writes. Its own documentation lists them as
> "structurally impossible to implement in Garage due to the lack of a consensus algorithm, which
> is one of Garage's core design choices which we cannot reconsider", and the maintainers have
> refused outside patches for core features. So waiting is not a plan. We also do not need to
> leave Garage: nothing else on it needs conditional writes, and Omnigraph is fine on its Longhorn
> volume. **Recommendation: keep Omnigraph on Longhorn and Garage for everything else. Add a
> small second S3 only when a workload actually needs conditional writes on object storage.**
> versitygw (posix backend) is the first pick for that and SeaweedFS the second. Both passed the
> same test Garage failed, including 50-writer races.

## Why this came up

Omnigraph stores Lance datasets and a state ledger. On object storage, both its commit path and
its ledger compare-and-swap depend on two S3 preconditions:

- `If-None-Match: *` on `PutObject`: create the object only if the key does not exist yet.
- `If-Match: <etag>` on `PutObject`: overwrite only if the object is still the version the writer
  read (compare-and-swap).

If the store ignores these headers, two commits can overwrite each other and both writers get a
success. That is silent data loss. Omnigraph runs on `file://` storage on a Longhorn RWO volume
today ([runbook](../runbooks/omnigraph.md#how-it-runs)), so we have no live problem. The question
from the owner was whether Garage will ever support this, or whether we should move.

## The Garage test (2026-09-28)

The test ran against the exact cluster image,
`dxflrs/garage:v2.4.1@sha256:9c96caa2612d3411acc5b0e6701fb238dbfba33e533a6d7d3d811a4b12d0d020`,
in a throwaway local container: single node, `replication_factor = 1`, LMDB, as in
`kubernetes/apps/garage/garage/app/garage.toml`. The cluster was not touched. The client was
boto3 1.43, path-style, with retries off.

| Step | Expected | Garage v2.4.1 |
| --- | --- | --- |
| (a) `IfNoneMatch='*'` on a new key | 200 | 200 |
| (b) `IfNoneMatch='*'` on the existing key | 412 | **200, object overwritten** (body `v2`, not `v1`) |
| (c) `IfMatch` with a wrong ETag | 412 | **200, object overwritten** |
| (d) `IfMatch` with the current ETag | 200 | 200 |
| (e) 20 parallel `IfNoneMatch='*'` writers, one new key | exactly one 200 | **20 × 200** |
| Stress: 10 rounds × 50 parallel creators, then 50 parallel CAS writers | one winner per round | **50 winners every round, both phases** |

Garage returns no error and no warning. It ignores the headers completely. The
[S3 compatibility page](https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/)
marks `PutObject` as "✅ Implemented" with no caveat, so the gap is only visible in the known-issues
page (below) or by testing. The off-site Garage runs v2.1.0 and has the same code path. An
independent project hit the same wall on v2.3.0 four days earlier
([Studio81Labs/taven#251](https://github.com/Studio81Labs/taven/issues/251), 2026-09-24): they
halted two PRs and opened a backend decision.

## What the Garage project has said

Garage's issue tracker is at `git.deuxfleurs.fr`. Its web UI sits behind an Anubis bot wall, but
the Forgejo API (`/api/v1/repos/Deuxfleurs/garage/issues`) answers, and everything below was read
there.

| Where | When | What |
| --- | --- | --- |
| [#1052 "support conditional writes"](https://git.deuxfleurs.fr/Deuxfleurs/garage/issues/1052) | opened 2025-05-28, **still open**, labels `action/discussion-needed`, `scope/s3-api`, **no milestone** | Maintainer **lx** (Alex Auvolat), 2025-05-29: *"adding this to Garage is not possible with our weak-consistency replication model, it would require a full rearchitecturing to use a strong consensus algorithm, which would make garage much slower. Maybe we can find a way to add this that doesn't need to switch everything to a consensus algorithm but that would be hard to do."* |
| #1052, community | 2025-07-11, 2026-06-27 | A user proposes quorum-applied CAS on the CRDT. Another (**dmsprotoeng**) implements a per-key lock map on a v2.3.0 fork ([commit 41d9e2d](https://github.com/deuxfleurs-org/garage/commit/41d9e2de963beaff49baa090183b1caf2648a225)) where *"sometimes no one will be able to write — the locks will collide and 0 will succeed"*. It was never submitted as an upstream PR and no maintainer replied. |
| [#1326](https://git.deuxfleurs.fr/Deuxfleurs/garage/issues/1326) | 2026-02-07 | A re-report of exactly our finding, closed within two minutes as a duplicate of #1052. |
| [Known issues: "No conditional writes / locking / WORM support"](https://garagehq.deuxfleurs.fr/documentation/reference-manual/known-issues/) | written by lx, commits `56cb89d` 2026-03-10 and `dfb20ba` 2026-04-15 | *"This is structurally impossible to implement in Garage due to the lack of a consensus algorithm, which is one of Garage's core design choices which we cannot reconsider. […] many practical use-cases for if-none-match cannot be supported (e.g. using it to implement mutual exclusion between concurrent writers)."* |
| [PR #1336 versioning & locking](https://git.deuxfleurs.fr/Deuxfleurs/garage/pulls/1336) | closed unmerged 2026-05-05 | lx: the team will design versioning itself, *"hopefully we will have something to show in less than a year"*. On core features: *"it is not currently something we envision doing with external contributors."* |
| [PR #1470 object lock](https://git.deuxfleurs.fr/Deuxfleurs/garage/pulls/1470), [PR #1479](https://git.deuxfleurs.fr/Deuxfleurs/garage/pulls/1479) | closed 2026-06-17 and 2026-09-15 | Refused: object lock will only arrive with versioning, which is "under way". |
| [#166 versioning](https://git.deuxfleurs.fr/Deuxfleurs/garage/issues/166), [#1127 WORM](https://git.deuxfleurs.fr/Deuxfleurs/garage/issues/1127) | open; #166 milestone `Speculative` | Versioning is the planned next big feature. Neither issue promises conditional writes. |
| Milestones `v2.5`, `v3.0` | as of 2026-09-28 | Contain nothing about conditional writes, preconditions or consensus. |
| Releases | v2.0.0 (2025-06-14) to v2.4.1 (2026-09-08) | No changelog entry touches conditional `PutObject`. The only precondition work is on `GetObject`/`HeadObject` (v1.1 #967, v2.2.0 #1193). |

Matrix and forum history is not indexed and was not searchable. The maintainers' public position
is the documented one above.

## Assessment: will it come?

*This section is judgement, not fact.*

- **Through 2027: almost certainly not.** The maintainers wrote that the gap is structural and the
  design choice behind it is one "we cannot reconsider". The roadmap they have committed to
  (versioning, "less than a year" from May 2026) does not include it.
- **Unsafe partial support, perhaps.** The known-issues text describes a "semi-working, unsafe"
  WORM/lock that only holds after the first write completes. That is exactly the case Omnigraph
  cannot use: two commits arriving at the same time are the case it needs protection from.
- **Contributing upstream will not work.** The maintainers have closed three outside PRs on
  neighbouring features in 2026 and said core features stay in-house. A single-node-only CAS
  (safe when `replication_factor = 1`, which is our in-cluster setup) is the only design that
  could be both correct and small. It would still be a Garage-specific mode against a stated
  design principle, and our off-site Garage would not benefit if it ever gains nodes.

## Is there a way around it in Lance or Omnigraph?

- **Lance** has three commit handlers. `ConditionalPutCommitHandler` has been the default on S3
  since [lance#3483](https://github.com/lance-format/lance/pull/3483) (merged 2025-03-05) and
  needs `If-None-Match`. The older rename handler needs copy-if-not-exists, which Garage also
  lacks. The external-manifest handler (`s3+ddb://`) moves the commit lock to DynamoDB.
- **arrow-rs `object_store`** defaults `S3ConditionalPut` to `ETagMatch`
  ([docs](https://docs.rs/object_store/latest/object_store/aws/enum.S3ConditionalPut.html)). It
  names R2 and MinIO as supported stores. `Disabled` turns the safety off; it does not replace it.
- **Omnigraph v0.11 exposes none of these.** Its storage adapter accepts only the `s3://` scheme
  (`parse_s3_uri` rejects anything else) and hardcodes `supports_conditional_update: true` for
  S3. Its ledger CAS calls `If-Match`/`If-None-Match` directly, outside Lance. Its Lance
  dependency is built with the `aws` and `azure` features, not `dynamodb`. So even a
  self-hostable DynamoDB API (ScyllaDB Alternator, or DynamoDB Local, which is not for
  production) would not help without an upstream change. Omnigraph's own docs recommend RustFS
  or MinIO on-prem, and its S3 CI runs against RustFS.
- **Omnigraph's single-writer topology is not a fence.** Its docs say "one mutation-capable
  process per graph remains the supported topology". One pod with `strategy: Recreate` lowers the
  risk, but a rolling overlap or the maintenance CronJob racing the server would still expose it.
  The code assumes the store enforces CAS.

## Alternatives

We tested all candidates on 2026-09-28 in throwaway local Docker containers with the same script
as Garage: steps (a) to (e), then the stress run (10 rounds × 50 parallel creators and 50
parallel CAS writers per round). Each ran as a single node with default settings. Containers and
volumes were removed afterwards.

| Store (image tested) | (a) | (b) | (c) | (d) | (e) 20 racers | Stress 50×10 | RSS after test¹ | Licence | Health (2026-09-28) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Garage** `dxflrs/garage:v2.4.1@sha256:9c96caa2…` | 200 | **200** | **200** | 200 | **20 × 200** | **FAIL** (50 winners) | 8 MiB | AGPL-3.0 | Active; releases every few months |
| **versitygw** `versity/versitygw:v1.8.0@sha256:30292fc2…` (posix backend) | 200 | 412 | 412 | 200 | 1 × 200 | **PASS** | 43 MiB | Apache-2.0 | Active: v1.8.0 2026-09-04, monthly releases. Recent fixes made conditional publish atomic per key ([#2288](https://github.com/versity/versitygw/pull/2288), [#2321](https://github.com/versity/versitygw/pull/2321), [#2359](https://github.com/versity/versitygw/pull/2359)). The lock is node-local ([#2351](https://github.com/versity/versitygw/issues/2351)), so it is safe on one pod with one volume |
| **SeaweedFS** `chrislusf/seaweedfs:4.47@sha256:ce9e796f…` | 200 | 412 | 412 | 200 | 1 × 200 | **PASS** | 179 MiB² | Apache-2.0 | Very active (4.47 2026-09-14, weekly). Conditional writes are serialised per object on an owner filer ([design post](https://www.seaweedfs.com/blog/conditional-writes/), 2026-07-16). Known edge cases with versioning and object lock ([#8073](https://github.com/seaweedfs/seaweedfs/issues/8073)), and Docker Registry blob finalisation ([#8908](https://github.com/seaweedfs/seaweedfs/issues/8908), open) |
| **RustFS** `rustfs/rustfs:1.0.0@sha256:8cc98017…` | 200 | 412 | 412 | 200 | 1 × 200 | **PASS** | 206 MiB | Apache-2.0 | Very active, but 1.0.0 only shipped 2026-09-16. Conditional-PUT races were fixed in the last month ([#6801](https://github.com/rustfs/rustfs/pull/6801), [#6798](https://github.com/rustfs/rustfs/pull/6798)). Open lock-server and quorum bugs ([#7966](https://github.com/rustfs/rustfs/issues/7966), [#8138](https://github.com/rustfs/rustfs/issues/8138)). It is what Omnigraph CI uses |
| **MinIO, community fork** `pgsty/minio:RELEASE.2026-08-04T00-00-00Z@sha256:b6bfe723…` | 200 | 412 | 412 | 200 | 1 × 200 | **PASS** | 171 MiB | AGPL-3.0 | Upstream `minio/minio` stopped binaries in 2025-10, went to maintenance mode 2025-12, and was **archived 2026-04-25** ([#21714](https://github.com/minio/minio/issues/21714)). The pgsty fork builds and releases, but it is one downstream packager. Not a base to build on |
| Ceph RGW | not tested | | | | | | GiBs (MON+OSD+RGW) | LGPL | Claims support, with recent backport fixes ([ceph#72049](https://github.com/ceph/ceph/pull/72049)). Far too heavy for a quiet low-power homelab |
| Apache Ozone | not tested | | | | | | JVM, multi-service | Apache-2.0 | Claims support ([blog](https://ozone.apache.org/blog/2026/07/08/ozone-s3-conditional-request/), 2026-07-08). Too heavy for this estate |

¹ Container RSS right after the stress run, single node, host with plenty of RAM. This is an
order of magnitude, not a sizing figure. None of these would need new hardware at this scale, so
the power cost (≈ €3 per continuous watt per year) does not decide between them.
² SeaweedFS `server` mode runs master, volume, filer and S3 in one process.

The Garage row is also the test's own failure case. The same script reports FAIL on the store
known not to enforce preconditions and PASS on four that do, so the probe tells a real result
apart from a broken script.

## Options

| Option | What it means | Cost | Verdict |
| --- | --- | --- | --- |
| **A. Stay** | Omnigraph on Longhorn `file://`; Garage keeps CNPG WAL/backups, Longhorn backups, Harbor, Forgejo LFS, GUAC and TechDocs | None | **Do this now** |
| **B. Second S3 for conditional-write workloads only** | A small in-cluster versitygw (posix, on a Longhorn PVC) or SeaweedFS, used only by workloads that need preconditions | One more small service, bucket keys via ESO | **Do this when a trigger fires** |
| C. Migrate off Garage | Move every consumer to SeaweedFS/RustFS | Weeks of migration; fresh risk on the backup path (e.g. SeaweedFS #8908 for registries); gains nothing for today's consumers | No |
| D. Contribute upstream | Implement CAS in Garage | Against a documented design principle; maintainers keep core features in-house | No |

**Why not migrate everything.** None of Garage's consumers needs conditional writes. barman-cloud,
Longhorn backups, the Harbor registry, Forgejo LFS, GUAC and TechDocs all write unique keys or
tolerate last-writer-wins. Garage also costs 8 MiB of RAM. Replacing the store behind all
backups to fix a problem only one app has, and that app has already worked around, would be
the wrong trade.

**Why versitygw first for option B.** It is the smallest (68 MB image, 43 MiB RSS) and
Apache-2.0. It stores objects as plain files on a volume, so a Longhorn PVC with the existing
`gitops-backup` job covers it and it needs no new backup story. Its conditional-write path had
several hardening releases in 2026-08/09, so its maintainers take the property seriously. Its
lock is node-local. That fits one pod on an RWO volume and rules out scaling it out. If a
workload later needs multi-node S3 with conditional writes, SeaweedFS is next. RustFS passes too,
but gets another look after a few 1.0.x releases: it is two weeks old.

## Triggers to revisit

- A workload needs conditional writes **on object storage**. Examples: Omnigraph moving to its
  preferred "bucket, no volume" shape or running more than one process, or a new Lance, Iceberg,
  Delta or SlateDB user. Take option B.
- Omnigraph adds a pluggable commit or lock service. Re-check whether plain Garage becomes usable.
- Garage closes #1052 or changes the known-issues entry. Re-run the same probe against the new
  release. Nothing counts until the probe passes.

## Re-running the probe

Use a throwaway container, never the cluster. Create a bucket and a key, then:

1. `put_object(IfNoneMatch='*')` on a new key: expect 200.
2. The same on the existing key: expect 412, and the body must be unchanged.
3. `put_object(IfMatch='"0000…"')`: expect 412.
4. `put_object(IfMatch=<current ETag>)`: expect 200.
5. 20 parallel `IfNoneMatch='*'` writers on one new key: expect exactly one 200.
6. Stress: 10 rounds of 50 parallel creators, then 50 parallel CAS writers against the ETag the
   winner produced: expect exactly one 200 per phase per round.

Use path-style addressing and turn client retries off. A retried 412 hides the result.
