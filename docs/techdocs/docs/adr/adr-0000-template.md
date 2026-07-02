# ADR-0000: Template — copy me for a new decision

> Status: **Proposed** · Date: yyyy-mm-dd

<!--
House ADR format (MADR-derived, trimmed for a one-person homelab — no deciders/consulted/informed).

Rules:
- One decision per ADR. Title states the decision ("Adopt X for Y"), not the topic ("Registry").
- Status: Proposed | Accepted | Rejected | Deprecated | Superseded by ADR-NNNN.
  Optional suffixes on the status line: "· Supersedes ADR-NNNN", "· Part of [RFC](../rfc/…)",
  "· Amended yyyy-mm-dd (see Status log)".
- Target 150–400 words. The ADR records the decision and its why. It is NOT the place for:
  operational steps/commands → runbook under ../runbooks/ (link it);
  design exploration & full option analysis → RFC under ../rfc/ (link it);
  point-in-time implementation detail → git history.
- ADRs are records. When reality changes, do NOT rewrite the body to match — append a dated line
  to the Status log, update the Status line, and (if the decision is replaced) write the new ADR.
- Register every new ADR in index.md. Filename: adr-NNNN-<kebab-title>.md, next free number.
-->

## Context

The problem that forced a decision, and the 2–4 forces that actually shaped the outcome.
Aim for ≤6 sentences; a reader should understand why "do nothing" wasn't acceptable.

## Decision

What we do, present tense, with the load-bearing specifics: component, chart/CR, namespace,
the one or two config choices that matter. End with where it lives:
`kubernetes/apps/<ns>/<app>/…`.

## Alternatives considered

<!-- Omit the section entirely if no real alternative was weighed. One line each — the losing
     option and the reason it lost. Full pros/cons tables belong in an RFC. -->

- **Alternative** — why it lost, in one line.

## Consequences

- What gets better (concrete, verifiable).
- What gets worse — the risk or cost we knowingly accept.
- Rollback: how to undo this decision if it goes wrong.

## Status log

<!-- Dated one-liners, newest last. This is the anti-rot mechanism: reverts, partial rollouts,
     supersessions, and amendments land here instead of silently invalidating the body. -->

- yyyy-mm-dd — Accepted.
