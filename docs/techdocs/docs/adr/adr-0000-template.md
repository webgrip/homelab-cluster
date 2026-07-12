---
status: "{proposed | rejected | accepted | deprecated | superseded by [ADR-0123](adr-0123-example.md)}"
date: "{YYYY-MM-DD when the decision was last updated}"
---

<!-- MkDocs/TechDocs treats frontmatter as page metadata and does NOT render it. Every status
     change must therefore also land where readers can see it: a dated bullet in More
     Information and the index.md Records row. Upstream MADR also defines decision-makers /
     consulted / informed; omitted here (one-person lab). -->

# {short title, representative of solved problem and found solution}

## Context and Problem Statement

{Describe the context and problem statement in two to three sentences, or as an illustrative
story. You may phrase the problem as a question. Make the scope of the decision explicit —
name the components, namespaces, or `kubernetes/apps/<ns>/<app>/…` paths it covers.}

<!-- This is an optional element. Feel free to remove. -->
## Decision Drivers

* {decision driver 1 — a desired quality, faced concern, constraint or force}
* {decision driver 2}

## Considered Options

* {title of option 1 — the chosen option, listed first (house convention)}
* {title of option 2}
* {title of option 3}

## Decision Outcome

Chosen option: "{title of option 1}", because {justification — e.g. only option meeting k.o.
decision driver | resolves force X | comes out best (see below)}.

{Then the load-bearing specifics: component, chart, config, the exact
`kubernetes/apps/<ns>/<app>/…` paths that implement the decision.}

<!-- This is an optional element. Feel free to remove. -->
### Consequences

* Good, because {positive consequence, e.g. improvement of one or more desired qualities}
* Bad, because {negative consequence, e.g. compromised quality, follow-up decision required}

<!-- Optional upstream; include it here whenever the decision is checkable (house verify
     ethos: cite the actual check, not a proxy). -->
### Confirmation

{How implementation/compliance of this ADR can be confirmed — a live `kubectl`/MCP read, a
flux-local test, a dashboard or alert, a Kyverno policy, a CI job. Name the concrete
command/resource/panel.}

<!-- This is an optional element (omit when no real alternative was weighed). -->
## Pros and Cons of the Options

### {title of option 1}

{example | description | pointer to more information} <!-- optional -->

* Good, because {argument a}
* Neutral, because {argument b} <!-- use "Neutral" when it weighs neither for nor against -->
* Bad, because {argument c}

### {title of other option}

* Good, because {argument a}
* Bad, because {argument b}

## More Information

<!-- Upstream optional; house-required — the record's dated history lives here.
     Bullet shapes:
       * Technical story: [RFC: example](../rfc/index.md)          — parent RFC / issue, first
       * YYYY-MM-DD — {event} ({commit})                           — dated history, oldest first
       * Supersedes | Refined by | Supported by [ADR-0123](adr-0123-example.md)  — relations -->

* Technical story: {parent RFC or issue link}
* {YYYY-MM-DD} — {accepted | reverted | ratified | …} ({commit})

<!-- MADR 4.0.0 (https://adr.github.io/madr/) — house conventions (numbering, Date semantics,
     dated history in More Information) live in index.md; procedure in the adr-writer skill. -->
