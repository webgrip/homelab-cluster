---
status: proposed
date: 2026-10-04
---

# CI never holds a write credential: reads are minted per run over OIDC, writes are reconciled from the cluster

Technical Story: owner request (2026-09-17), raised by
[twente.dev run 413](https://forgejo.webgrip.dev/webgrip/twente.dev/actions/runs/413). The DNS
lane had been red since the day it landed because a bridge row was never seeded, and the fix
surfaced the larger question: the credential it was waiting for is a DNS:Edit token spanning two
sites, delivered to every job in one repository. This record refines
[ADR-0055](adr-0055-one-secrets-model-six-levels.md), which named L4 as the direction and named
the trigger; the trigger has now fired.

## Context and Problem Statement

DNSControl moved the `twente.dev` zone out of `webgrip/cloudflare` and into the site repository
([twente.dev ADR 0018](https://forgejo.webgrip.dev/webgrip/twente.dev/src/branch/main/docs/adrs/0018-account-and-zone-resources-in-opentofu.md)),
so a site now previews and pushes its own DNS from CI. `webgrip.nl` is queued to follow, and
every further zone after it.

The credential that makes this work is specified as one Cloudflare token, `forgejo-ci-dns`,
carrying Zone:Read and DNS:Edit on `twente.dev` **and** `webgrip.nl`, delivered to the
`twente.dev` repository as a Forgejo Actions secret by the bridge
([`forgejo-actions-secrets.cronjob.yaml`](../../../../kubernetes/apps/forgejo/forgejo-actions-secrets/app/forgejo-actions-secrets.cronjob.yaml)).
Three properties of that arrangement are wrong, and they get worse with each zone added:

* **It spans sites.** Any workflow in the `twente.dev` repository can rewrite `webgrip.nl`'s DNS.
  The repository is the delivery boundary, so the blast radius of a careless commit in one site
  is every zone the token covers.
* **It cannot be scoped to the job that needs it.** `on_dns_change.yml` previews on
  `development` and pushes on `main`. Preview needs only Zone:Read and DNS:Read; push needs
  DNS:Edit. The bridge hands one secret to both, so a `development` run holds a credential that
  can rewrite production DNS. ADR-0055 names exactly this — "a secret needs per-job scoping the
  bridge cannot give" — as the trigger to adopt L4.
* **Every new zone is a manual act in three systems.** A token created by hand in the Cloudflare
  dashboard, a `bao kv put`, an ExternalSecret and an env block in the bridge CronJob, and a
  fan-out variable. The bridge stands at roughly 21 rows against ADR-0055's thirty-row ceiling,
  and DNS is the row that multiplies.

There is a fourth problem that the bridge causes by design and that this incident demonstrated:
it fails soft. An unseeded vault path logs `not present yet; skipping`, the ExternalSecret sits
`SecretSyncedError`, nothing alerts, and the failure surfaces eleven days later as an unrelated
red CI job.

The cluster already holds the pieces to do better. `auth/forgejo` is a live JWT auth method with
roles bound on `repository`, `event_name` and `ref`
([`bootstrap/config.sh`](../../../../kubernetes/apps/security/openbao/bootstrap/config.sh)),
proven by the `cosign-signer` role. What is missing is one reusable action.

## Decision Drivers

* A credential's blast radius should stop at one site, and a write credential should not exist
  in a system whose job is to read.
* GitOps-first: desired state in Git, reconciled — not applied imperatively by a job holding a
  key.
* The Nth zone must cost a line of configuration, not a visit to a vendor dashboard.
* Failures must be loud. A missing credential should stop something visible, not skip quietly.
* Nothing here may depend on a runner outside the cluster.

## Considered Options

* **Reads minted per run over OIDC (L4), writes reconciled by the cluster, one token per zone
  per operation**
* Keep the bridge (L3), one token per zone, extend the roller to rotate them
* Keep the bridge, one shared multi-zone token (the status quo as specified)
* Retire the bridge wholesale and move every CI secret to OIDC at once
* Recentralise: all zones return to `webgrip/cloudflare` under one token

## Decision Outcome

Chosen option: **reads over OIDC, writes from the cluster, one token per zone per operation**,
because it is the only option that removes the write credential from the forge entirely rather
than delivering it more carefully, and because the per-job scoping it needs is already available
on `auth/forgejo` and available nowhere else in the estate.

The decision splits DNS along the read/write line:

* **Preview stays in CI, on a read.** `on_dns_change.yml` exchanges its Forgejo Actions OIDC
  token at `auth/forgejo/login` for a 10-minute OpenBao token and reads its zone's read-only
  Cloudflare credential. The exchange is a reusable action in
  [`webgrip/workflows`](https://forgejo.webgrip.dev/webgrip/workflows) — the piece
  [the L4 runbook](../runbooks/secrets-level-4-short-lived.md) is already written against and
  waiting for. It is built once and serves every future L4 case, not only DNS.
* **Push leaves CI.** Applying a zone becomes an in-cluster reconciler that reads the repository
  and runs `dnscontrol push`, with the DNS:Edit token delivered by ExternalSecret into the
  cluster where it already lives. No DNS:Edit credential is published to Forgejo, for any
  repository, ever. This is how every other desired state in this estate is applied.
* **Tokens are per zone and per operation.** `dns-ro-<zone>` (Zone:Read, DNS:Read) and
  `dns-rw-<zone>` (adds DNS:Edit), each scoped to exactly one zone, at
  `secret/cloudflare/dns/<zone>`. An OpenBao policy grants a repository read on its own zone's
  read path and on nothing else; the write path is readable only by the reconciler's identity.
* **Tokens are minted, not typed.** The manager token at `secret/cloudflare/token-manager`
  already carries Account API Tokens:Edit, the permission Cloudflare requires to create a token.
  A minting Job creates the pair for a zone, verifies each against
  `/tokens/verify`, and writes value and id back through a PushSecret. Until that Job exists,
  [`cloudflare-token-roller.cronjob.yaml`](../../../../kubernetes/apps/forgejo/forgejo-actions-secrets/app/cloudflare-token-roller.cronjob.yaml)
  is extended from a single `CLOUDFLARE_DEPLOY_TOKEN_ID` to a list, so hand-made tokens still
  rotate monthly.

Sequencing, so that nothing waits on the thing after it: seed the token as specified today and
let the lane go green on the bridge; build the fetch action; move preview onto it and narrow the
token to read-only; then build the reconciler and drop the write token out of the forge. The
bridge row for `CLOUDFLARE_DNS_TOKEN` is deleted at the end, not the beginning.

Adding a zone, once this is in place: a policy and a role in `config.sh`, and the minting Job
picks up the rest.

### Consequences

* Good, because the write credential no longer exists in Forgejo, so no workflow — present or
  future, in any repository — can reach it, however it is written.
* Good, because a token's reach stops at one zone, and a compromised site CI cannot touch a
  sibling site's DNS.
* Good, because `bound_claims` on `ref` and `event_name` makes the preview credential
  structurally unavailable to a push and the write path unavailable to CI; the bridge can express
  neither.
* Good, because each read is a distinct, audited, 10-minute lease against an identity, instead of
  a value at rest in Forgejo's database with a rotation lag of up to two hours.
* Good, because it retires bridge rows rather than adding one per zone, moving away from
  ADR-0055's thirty-row ceiling instead of toward it.
* Bad, because the vault becomes a run-time dependency of CI: an OpenBao outage stops DNS
  previews. This is acceptable only for in-cluster runners, and the estate must not move a
  GitHub-hosted lane onto this path.
* Bad, because a push no longer reports into the pull request that caused it. The preview stays
  in the PR and applies are rare, so the loss is a delay in feedback, not a loss of review.
* Bad, because it adds a reconciler to operate and alert on, and its failure mode — silent
  non-application — needs the same drift job that guards the current design.
* Bad, because per-zone tokens multiply the objects Cloudflare holds; without the minting Job
  this trades one kind of toil for more of it, which is why minting is part of the decision and
  not a follow-up.

### Confirmation

1. `bao read auth/forgejo/role/ci-twente-dev` lists `twente.dev` and the policy
   `ci-twente-dev`; `bao policy read ci-twente-dev` grants read on
   `secret/data/cloudflare/dns/twente-dev-ro` and nothing else.
2. A `development` run of `on_dns_change.yml` prints a preview and its claims, and no Cloudflare
   token appears in any Forgejo secret: the repository's Actions secrets list contains no
   `CLOUDFLARE_DNS_TOKEN`.
3. A job that requests the write path is refused by policy, visible in the OpenBao audit log.
4. `kubectl -n <ns> logs job/<dns-reconciler>` shows `dnscontrol push` applying from `main`, and
   `dns-drift.yml` reports `0 corrections` the following morning.
5. Each zone's token in the Cloudflare account lists exactly one zone under Zone Resources.
6. The bridge table in [secrets level 3](../runbooks/secrets-level-3-bridge.md) no longer carries
   a `CLOUDFLARE_DNS_TOKEN` row.

## Pros and Cons of the Options

### Reads over OIDC, writes from the cluster, per zone per operation

* Good, because it is the only option that makes the write credential absent rather than
  protected.
* Good, because the mechanism is already proven in this cluster by `cosign-signer`, and the
  missing piece is one action the L4 runbook is already written against.
* Bad, because it is three pieces of work — action, policies, reconciler — before the last bridge
  row can be deleted.

### Bridge, one token per zone, roller extended

* Good, because it needs no new mechanism and fixes the cross-site blast radius on its own.
* Good, because it keeps CI working with no run-time dependency on the vault.
* Bad, because a DNS:Edit token still sits in Forgejo where every job in the repository can read
  it, which is the property that matters most here.
* Bad, because it adds two bridge rows per zone, in the direction ADR-0055 warns against.

### Bridge, one shared multi-zone token

* Good, because it is what is already specified, and it is two commands from working.
* Bad, because one site's CI can rewrite another site's DNS — a cross-site blast radius created
  for convenience.
* Bad, because it gets strictly worse with each zone added.

### Retire the bridge wholesale

* Good, because it is the L4 endgame and ends the question.
* Bad, because ADR-0055 already weighed and rejected the big-bang: external and GitHub-hosted
  lanes cannot reach the vault, and roughly 21 rows would move at once with no proven action.

### Recentralise every zone in `webgrip/cloudflare`

* Good, because one token, one lane, one place to look.
* Bad, because it reverses twente.dev ADR 0018 without the problem that record was solving having
  changed: a zone record belongs next to the code whose hostname it is.
* Bad, because the single token then spans every zone in the estate — the blast radius this
  record exists to close, made maximal.

## More Information

* [ADR-0055](adr-0055-one-secrets-model-six-levels.md) — the six levels, and the trigger this
  record acts on · [ADR-0016](adr-0016-openbao-dynamic-postgres-credentials.md) — the precedent
  for leases over stored values
* [Runbook: secrets level 4 — short-lived](../runbooks/secrets-level-4-short-lived.md) — the
  `ci-<repo>` pattern, and the reusable action it is waiting for ·
  [level 3 — bridge](../runbooks/secrets-level-3-bridge.md)
* [twente.dev ADR 0018](https://forgejo.webgrip.dev/webgrip/twente.dev/src/branch/main/docs/adrs/0018-account-and-zone-resources-in-opentofu.md)
  — why a zone lives in its site's repository
* 2026-09-17 — proposed, after run 413 showed a two-site DNS:Edit token being delivered to one
  repository's every job. Nothing is implemented; the bridge row is seeded first so the lane goes
  green, and is the last thing removed.
* 2026-10-04 — step one landed (2f50f76b): per-zone Cloudflare DNS tokens minted in-cluster by a
  CronJob, and OpenBao JWT roles `ci-unfold` / `ci-twente-dev` granting CI an OIDC read of its
  own zone's token. The bridge row and the in-cluster apply are unchanged; status stays
  proposed
