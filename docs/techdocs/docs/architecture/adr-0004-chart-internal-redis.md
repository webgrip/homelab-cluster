# ADR-0004: Use Harbor's chart-bundled Redis

> Status: **Accepted** · Date: 2026-06-12 · Part of [RFC: Harbor Container Registry](rfc-harbor-registry.md)

## Context

Harbor needs Redis for several distinct concerns — the core cache, the jobservice queue, the
registry cache, and Trivy's job state — which the chart maps onto separate Redis logical
databases. There are two ways to provide it: let the chart deploy its own Redis, or stand up an
external instance and point Harbor at it. The cluster has a precedent for app-owned caches
(searxng runs its own Valkey StatefulSet), but no shared Redis service.

## Decision

Use the **chart-bundled internal Redis** (`redis.type: internal`), which ships the
`goharbor/redis-photon` image and auto-wires all four logical databases. Persist it on a small
`longhorn-general`, `ReadWriteOnce` PVC.

## Consequences

- The chart owns the Redis wiring (host, the per-component DB indexes) — no manual connection
  configuration to keep in sync across core/jobservice/registry/trivy.
- **No Bitnami image** enters the stack — `redis-photon` is Harbor's own, sidestepping the
  Bitnami image-distribution changes that now affect the common `bitnami/redis` subchart.
- One fewer StatefulSet to operate and patch than an external cache would add.
- Redis is single-instance (no HA). For a homelab registry that's acceptable; a restart briefly
  interrupts the job queue/cache but loses no durable data (durable state is in Postgres + S3).

## Alternatives considered

- **An external Valkey StatefulSet** (the searxng pattern) — gives independent lifecycle/version
  control and a path to HA later, but adds a component to own for no present benefit, and we'd
  hand-wire the four DB indexes. Worth revisiting only if Redis HA becomes a requirement.
