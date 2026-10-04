---
status: accepted
date: 2026-10-04
---

# Forgejo Actions resolve bare `uses:` refs from the local forge, against mirrored action repos

Technical Story: [RFC: CI pipeline performance](../rfc/rfc-ci-pipeline-performance.md)

## Context and Problem Statement

Every CI job runs in a fresh ephemeral runner pod, so every action (`actions/checkout`, the
`docker/*` set, `actions/github-script`) was `git clone`d over the WAN from `data.forgejo.org`
before any real work. [ADR-0028](adr-0028-action-clone-wall.md) established that this runner has
no offline mode at any layer, that the only lever is the server's `DEFAULT_ACTIONS_URL`, and chose
to measure before building anything. It explicitly rejected flipping `DEFAULT_ACTIONS_URL`
server-wide, because a local forge that is authoritative for every action breaks any action that is
not mirrored.

The measurement came in on 2026-07-23: about two minutes per job went to WAN action clones.

## Considered Options

* Global `DEFAULT_ACTIONS_URL` → in-cluster Forgejo, with every used action mirrored first
* Scoped LAN mirror: explicit in-cluster URLs in the `-fast` composite only (ADR-0028's fallback)
* Keep resolving from `data.forgejo.org`

## Decision Outcome

Chosen option: "Global `DEFAULT_ACTIONS_URL` → in-cluster Forgejo, with every used action mirrored
first", because it removes the clone tax from every job in every repo rather than from one
composite, and ADR-0028's objection (un-mirrored actions break) is answered by mirroring every
action the `.forgejo` trees use before the flip.

* `kubernetes/apps/forgejo/forgejo/app/helmrelease.yaml` sets `actions.DEFAULT_ACTIONS_URL` to
  `http://forgejo-http.forgejo.svc.cluster.local:3000`, which also keeps clones off the ingress.
* `scripts/bootstrap-action-mirrors.sh` idempotently creates the local pull-mirrors of every action
  the `.forgejo` workflows use, and verifies each with an anonymous clone. It runs before any change
  that introduces a new action.

### Consequences

* Good, because the measured ~2 min per job of WAN clones is gone for every repository on the forge.
* Good, because action resolution no longer depends on `data.forgejo.org` being reachable.
* Bad, because the local forge is now authoritative for every bare `uses:` ref: a workflow that adds
  an action nobody mirrored fails with a 404 until `bootstrap-action-mirrors.sh` is re-run.
* Bad, because an outage of the in-cluster Forgejo now also stops action resolution, which it
  already did for checkout of the repositories themselves.

### Confirmation

* `actions.DEFAULT_ACTIONS_URL` in the Forgejo HelmRelease reads the in-cluster Service URL.
* `scripts/bootstrap-action-mirrors.sh` reports an anonymous-clone OK for every mirrored action.

## Pros and Cons of the Options

### Scoped LAN mirror in the `-fast` composite only

* Good, because un-mirrored actions elsewhere keep resolving from `data.forgejo.org`.
* Bad, because it only helps the one composite, while every job pays the clone tax.

### Keep resolving from `data.forgejo.org`

* Good, because there is nothing to mirror or maintain.
* Bad, because every job keeps paying the measured two minutes.

## More Information

* Supersedes [ADR-0028](adr-0028-action-clone-wall.md), whose measure-first gate this record
  closes.
* 2026-07-23 — action mirrors bootstrapped (`scripts/bootstrap-action-mirrors.sh`, 666c2ba6).
* 2026-07-24 — `DEFAULT_ACTIONS_URL` flipped to the local forge after all 19 mirrors verified
  (7936af71).
* 2026-10-04 — recorded in the ADR audit; the decision was in effect from 2026-07-24 without a
  record.
