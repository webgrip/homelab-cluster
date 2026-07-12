# vikunja-refiner — description template (HTML)

Vikunja descriptions are TipTap HTML (verified round-trip 2026-07-12: `<h3>`, `<p>`, `<code>`,
`<ul>`, and the checkbox taskList markup below all survive the sanitizer and render natively;
raw markdown displays as literal text).

## Checkbox markup (renders as a checklist with an x/y counter)

```html
<ul data-type="taskList">
  <li data-checked="false" data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>criterion text</p></div></li>
</ul>
```

`data-checked="true"` + `checked` on the input for a pre-ticked box.

## Section template

```html
<p><strong>&lt;theme heading&gt;</strong> — <code>[P· · · · ·]</code></p>

<h3>Problem</h3>
<p>What is wrong today + evidence: <code>path/to/file.yaml:12</code>, live symptom, ADR/RFC.</p>

<h3>Outcome</h3>
<p>One sentence end-state.</p>

<h3>Acceptance criteria</h3>
<!-- taskList block, 2–6 items, each verifiable against real state -->

<h3>Approach</h3>
<ol>
  <li>Step naming a real repo path (<code>kubernetes/apps/…</code>) and the applicable skill.</li>
</ol>

<h3>Verification</h3>
<p>The exact command/check that proves it live (<code>kubectl …</code>, MCP query, drill).</p>

<h3>Gates &amp; links</h3>
<ul>
  <li>Blocked by: <em>&lt;exact ticket title&gt;</em> / sequencing note</li>
  <li><code>docs/techdocs/docs/adr/adr-00xx-….md</code></li>
</ul>
```

Omit a section only when genuinely empty (e.g. no gates); never omit Problem, Acceptance
criteria, or Verification — without those the ticket is not ready by definition.

## Worked example (refined ticket, condensed)

Title (unchanged, match key): `Default-deny the security namespace — OpenBao/ESO/cosign crown jewels currently sit on a flat network`

```html
<p><strong>Security — network containment (ADR-0006 rollout)</strong> — <code>[P1 · H · M]</code></p>
<h3>Problem</h3>
<p>The <code>security</code> namespace (OpenBao, ESO, cosign) has no NetworkPolicy — any pod
in the cluster can reach OpenBao:8200. ADR-0006's opt-in default-deny generator is live but
this namespace never got the label (<code>kubernetes/apps/security/kustomization.yaml</code>).</p>
<h3>Outcome</h3>
<p>security ns is default-deny with explicit allows; OpenBao reachable only from ESO, the
unsealer CronJob, and the gateway.</p>
<h3>Acceptance criteria</h3>
<ul data-type="taskList">
<li data-checked="false" data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>ns labeled for the generator; default-deny + allow-dns present (<code>kubectl -n security get netpol</code>)</p></div></li>
<li data-checked="false" data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>ESO ClusterSecretStore still Ready; a test ExternalSecret syncs</p></div></li>
<li data-checked="false" data-type="taskItem"><label><input type="checkbox"><span></span></label><div><p>a busybox pod in <code>default</code> can NOT reach openbao:8200</p></div></li>
</ul>
<h3>Approach</h3>
<ol><li>Label the ns (network-policy skill); add allows per the vikunja-app pattern
(<code>kubernetes/apps/vikunja/vikunja/app/networkpolicy.yaml</code>).</li></ol>
<h3>Verification</h3>
<p><code>kubectl -n security get netpol</code> + ESO sync check + the blocked-probe test above.</p>
<h3>Gates &amp; links</h3>
<ul><li><code>docs/techdocs/docs/adr/adr-0006-….md</code>; do before the OpenBao ingress-scoping ticket.</li></ul>
```
