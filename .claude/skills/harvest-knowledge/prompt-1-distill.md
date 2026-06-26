You are auditing THIS ENTIRE conversation to extract durable, reusable knowledge so I can
later fold it into a repository's docs, CLAUDE.md, Claude Code skills, and memory. Your
output will be pasted (alongside digests from other threads) into a separate "integration"
thread, so it must be self-contained and uniformly structured. Do not assume the reader
has any access to this conversation.

SCOPE — include only knowledge that is durable and reusable beyond this thread:
- Facts about how the system/repo/tooling actually works (that weren't obvious upfront)
- Gotchas, footguns, and "this surprised us" learnings — with the cause
- Decisions made and the rationale/trade-offs behind them
- Reusable procedures or workflows (candidates for a skill)
- Reference material: exact commands, config snippets, file paths, version pins,
  env vars, API shapes, URLs/dashboards/tickets
- Explicit preferences or working-style feedback I gave you
- Naming conventions, invariants, or constraints

EXCLUDE: one-off debugging chatter, transient state, restating the obvious,
pleasantries, and anything already self-evident from reading the code/repo.
REDACT any secrets/tokens/credentials as <REDACTED>.

RULES:
- Prefer VERBATIM commands, config, and paths — do not paraphrase them.
- Be honest about verification. Tag each item: [VERIFIED] (we ran it / saw it work),
  [ASSERTED] (claimed but not confirmed), or [OPEN] (unresolved / assumption).
- Deduplicate. One item per distinct fact.
- If a claim turned out to be WRONG during the thread, record the correction, not the
  original mistake.
- If this thread produced little or no durable knowledge, say so plainly instead of
  padding.

OUTPUT FORMAT (markdown, exactly this shape):

# Thread Digest: <short topic title>
**One-line summary:** <what this thread was about>
**Approx date / status:** <if inferable, else "unknown"> — <done / in progress / abandoned>

## Items
For each item, emit this block:

### [TYPE] <concise title>
- **Type:** FACT | GOTCHA | DECISION | PROCEDURE | REFERENCE | PREFERENCE | OPEN
- **Verification:** [VERIFIED] | [ASSERTED] | [OPEN]
- **What:** <the knowledge, stated so it stands alone>
- **Why it matters:** <rationale / what it prevents or enables>
- **Snippet:** <verbatim command/config/path, or "none">
- **Suggested home:** new-skill | existing-skill | doc | CLAUDE.md | memory
  (your best guess; the integrator will reconcile against what actually exists)

## Open questions / unfinished
- <bullets, or "none">

## Explicit preferences/feedback I gave
- <bullets, or "none">
