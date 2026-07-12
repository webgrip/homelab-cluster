# Refinement — raw ticket → Definition of Ready

The DoR itself (7 points + agent-assignability gate) is in [SKILL.md](SKILL.md). This file is the
execution: per-ticket procedure, the HTML template, and the bulk fan-out pattern.

## Per-ticket procedure

1. **Research before writing.** Repo (manifests, `docs/techdocs/docs/{adr,rfc,runbooks,incidents}`,
   `scripts/`, skills) + live state via the read-only MCPs where the premise depends on live truth.
   Every Problem claim and criterion cites `file:line` or a live check. Never invent — an
   unverifiable claim becomes an explicit evidence-gap line, not a fact.
2. **Stale premises are a first-class finding.** If the work already shipped or the failure no
   longer exists, write the Problem as "Premise stale — …", reframe as verify-and-close, flag it.
3. Write the description per the template below via `task_update`; sanity-check `priority` and the
   `impact/·` `effort/·` labels against what research showed; correct drift and say so.
4. Labels: add `ready`, remove `needs-refinement` — via `label_add_to_task`/`label_remove_from_task`
   (NOT `labels_bulk_set_on_task` unless passing the complete set).
5. If sizing tripped (L without a slice): split — children via `task_create` +
   `relation_create` kind `subtask`, sequence with `precedes`.
6. Report per ticket: one-line what-changed + any evidence gap left open.

## HTML description template

Verified round-trip 2026-07-12: `<h3>`, `<p>`, `<code>`, `<ul>`, and the checkbox markup below all
survive the sanitizer and render natively (checklist gets an x/y counter). Escape `&` as `&amp;`,
shell `<`/`>` as `&lt;`/`&gt;`. 1500–3500 chars. Never omit Problem, Acceptance criteria, or
Verification.

```html
<p><strong>&lt;theme&gt;</strong> — <code>[P· · · · ·]</code></p>
<h3>Problem</h3><p>What is wrong today + evidence: <code>path/file.yaml:12</code>, live symptom, ADR/RFC.</p>
<h3>Outcome</h3><p>One sentence end-state.</p>
<h3>Acceptance criteria</h3>
<ul data-type="taskList">
  <li data-checked="false" data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>criterion, verifiable against real state</p></div></li>
</ul>
<h3>Approach</h3><ol><li>Step naming a real repo path + applicable skill.</li></ol>
<h3>Verification</h3><p>The exact command/check that proves it live.</p>
<h3>Gates &amp; links</h3><ul><li>Blocked by: <em>&lt;exact ticket title&gt;</em> · <code>docs/…/adr-00xx-….md</code></li></ul>
```

(`data-checked="true"` + `checked` on the input for a pre-ticked box.)

## Worked example (condensed)

Title (unchanged): `Default-deny the security namespace — OpenBao/ESO/cosign crown jewels currently sit on a flat network`

```html
<p><strong>Security — network containment (ADR-0006 rollout)</strong> — <code>[P1 · H · M]</code></p>
<h3>Problem</h3><p>The <code>security</code> ns has no NetworkPolicy — any pod can reach
OpenBao:8200. ADR-0006's opt-in generator is live but this ns never got the label
(<code>kubernetes/apps/security/namespace.yaml</code>).</p>
<h3>Outcome</h3><p>security ns default-deny; OpenBao reachable only from ESO, unsealer, gateway.</p>
<h3>Acceptance criteria</h3><ul data-type="taskList">
<li data-checked="false" data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>generated default-deny + allow-dns present (<code>kubectl -n security get netpol</code>)</p></div></li>
<li data-checked="false" data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>a probe pod in <code>default</code> can NOT reach openbao:8200</p></div></li>
</ul>
<h3>Approach</h3><ol><li>cnpg-netpol into both DB-layer kustomizations BEFORE the label flip
(deadlock otherwise); label the ns; per-app allows per the vikunja-app pattern.</li></ol>
<h3>Verification</h3><p><code>kubectl -n security get netpol</code> + ESO sync check + blocked-probe test.</p>
<h3>Gates &amp; links</h3><ul><li><code>docs/techdocs/docs/adr/adr-0006-….md</code></li></ul>
```

## Bulk fan-out (N tickets, research-grade, without flooding the parent context)

Proven 2026-07-12 on 92 tickets / 11 agents; **60/92 came back flagged** — stale premises, drift,
real bugs. Refinement's chief value is invalidating stale work.

1. **Packets**: split tickets into theme groups of ~7–10; write each group as a JSON file
   (`packet-<group>.json`: `[{n, theme, title, prio, impact, effort, …}]`).
2. **Shared brief** (`brief.md`, one file all agents read): the DoR + template contract, research
   standard (cite `file:line`; stale premises are findings; never invent), output contract —
   write `refined-<group>.json` as `[{"n": <int>, "html": "...", "flags": ["..."]}]`, validate it
   parses before finishing, final message = one line per ticket, **never paste HTML into the
   final message**.
3. **Launch one general-purpose agent per packet** (single message, parallel); each researches the
   repo read-only and writes only its output JSON.
4. **Central validation** before applying: JSON parses · every packet ticket covered ·
   `'data-type="taskList"' in html` · no markdown smells (`re.search(r'(^|\n)#{1,3} |\]\(', html)`) ·
   cited repo paths exist (beware regex false-positives on basename fragments — check context
   before accusing) · spot-read 2–3 drafts for invented claims.
5. **Apply centrally in ONE MCP session** (sequential; parallel agent MCP sessions risk the
   bridge's memory) via [scripts/mcp_client.py](scripts/mcp_client.py); swap labels; report flags
   grouped (stale premises / drift / bugs / evidence gaps).

Gotcha: a sub-agent that itself spawns children may stall after its children finish (their
notifications bubble to the main loop) — nudge it via `SendMessage` with the findings summary.
