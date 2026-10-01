# Publish checklist: "Tokens are cheap. Review isn't."

Canonical draft: `BLOGPOST-glide.draft-v2.md`. Variants: `.linkedin.md`, `.devto.md`, `.hn.md`.
Every variant carries only claims that are in draft-v2. If draft-v2 changes, re-check the variants.

## 0. Before anything goes out

### Owner-judgment points (not resolved here; your call)

- [ ] **(a) The opening, "In September I planned…".** The capacity plan was produced by an agent
      for you. Decide whether "I planned" is fair, or whether the post (and the LinkedIn hook, and
      the dev.to intro, which both inherit it) should say how the plan came about.
- [ ] **(b) The ledger recording who started a run.** Decided 2026-09-27. Decide whether to announce
      it publicly now. It appears in draft-v2 ("Responsibility stays with whoever presses merge")
      and in the dev.to variant; the LinkedIn variant leaves it out. Remove from both if not.
- [ ] **(c) Voice check.** This post is calmer and more business-like than "I told my AI code
      reviewer it couldn't push". Read draft-v2 aloud and decide whether that register is yours for
      this audience, and rewrite any sentence that isn't.

### Facts and links

- [ ] Links reachable **from outside your LAN** (phone on mobile data, not home Wi-Fi; k8s-gateway
      can hand LAN clients an internal answer):
  - [ ] https://forgejo.webgrip.dev/webgrip/glide loads the repository without signing in.
        (2026-09-27 from the LAN: HTTP 200.)
  - [ ] https://docs.webgrip.dev/glide loads the docs. (2026-09-27 from the LAN: 302 to
        `/glide/`, then 200.)
- [ ] Demo command: `mise run demo-unified` runs on a clean clone and starts Ploeg, Vloer and
      PostgreSQL without model calls. The task exists in `glide/mise.toml` and is documented in
      `docs/workflows/local-demo.md`; that is not the same as a stranger running it. Test it in a
      fresh checkout before any link goes out.
- [ ] Figures still hold on the day: the "What isn't true yet" table, the four-hour key lifetime,
      the bronze caps ($2.00 / $0.40 / $7.20 / $8), agent-sandbox executor still experimental,
      KPI page still "nothing measured yet".
- [ ] Remove the draft header line ("Draft v2, 2026-09-27. Not published…") from the canonical.

## 1. Canonical first (day 0)

- [ ] Publish draft-v2 at the home platform (Substack, as last time, unless you've moved the
      canonical). Title and subtitle as given.
- [ ] `<details>` blocks: check they render there. If the platform strips them, turn each into a
      short "For self-hosters" section at the end.
- [ ] Record the final URL and replace `CANONICAL_URL_TBD` in `.devto.md` (front matter and the
      "Originally published" line), the LinkedIn first-comment text and `.hn.md`.

## 2. LinkedIn (same week as the canonical, a weekday morning)

- [ ] Post the body only. No link in the body.
- [ ] Post the first-comment text (canonical link, repo, docs) yourself, right after publishing.
- [ ] Hashtags: three, at the end, as written.
- [ ] Reply to comments for the first few hours; that window decides distribution.

## 3. dev.to (2–10 days after the canonical)

- [ ] Wait for the canonical to be indexed: 2–3 days if the home domain is well crawled, up to 7–10
      if not.
- [ ] Canonical mechanics: `canonical_url:` in the front matter set to the final canonical URL.
      Check the rendered page source shows `<link rel="canonical" href="…">` pointing home.
- [ ] Tags: `ai, kubernetes, devops, opensource` (four is the maximum).
- [ ] The `{% details %}` liquid blocks render as collapsibles in the dev.to preview.
- [ ] Flip `published: false` to `true` only after the preview looks right.

## 4. Hacker News, then Lobsters (after the canonical has settled; not the LinkedIn day)

- [ ] Any text you post there is written by you, start to finish (see `.hn.md`).
- [ ] Submit the canonical URL with the original title, Tue–Thu 09:00–12:00 US Eastern.
- [ ] Lobsters: "authored by" ticked, tags checked against the live taxonomy; skip if your
      self-promotion share there is already high.
- [ ] Block out 24–48 hours to be in the thread.

## Canonical-URL mechanics, per platform

| Platform | How the canonical is set |
| --- | --- |
| Home (Substack) | It is the canonical. Nothing to set. |
| dev.to | `canonical_url` front matter (or the editor's "republishing" field). |
| LinkedIn | No canonical mechanism. Native post; the link lives only in the first comment. |
| Hacker News | Submit the canonical URL itself. |
| Lobsters | Submit the canonical URL itself, "authored by" ticked. |

## The rule that overrides everything else

**Never solicit votes**, on HN, Lobsters or Reddit, in any form: not in the post, not in a
LinkedIn comment, not in a DM or group chat, not "it's on the front page, have a look". Detection is
automated and the penalty is the account, not the post. One submission per venue per piece; no
resubmitting if it doesn't take.
