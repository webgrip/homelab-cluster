# Post plan: Dark DevSecFinOps — the loop, and how far round it we actually got

*Planning document, not the post. Written 2026-07-30.*

## Decisions already taken

- **One new post.** The July draft (`BLOGPOST-dark-factory.md`, 5,866 words, never published)
  becomes ~1,000 words of backstory inside it, not a published Part 1. Its central admission —
  *"Today the dispatch is a curl"* — is the thing Ploeg falsified, and its #1 "what's next" item is
  Ploeg itself. Shipping it standalone now would date badly on contact.

  It also still carries an **unfinished sentence** in the intro (*"The first time I heard about a
  dark factory was when"*) and a placeholder figure (*"60869.56 workloads"*), both from a rewrite
  that stopped mid-edit. Neither survives into the new post.

  Note on provenance: the eight July files were committed by accident, swept into an unrelated CI
  commit (`7936af71 feat(ci): flip DEFAULT_ACTIONS_URL…`) rather than committed deliberately. They
  are tracked; they were never reviewed as a change.
- **Thesis:** assign a ticket, get a **reviewed** pull request. The wider loop — ticket → PR →
  review → merge → production → telemetry → feedback → new tickets → refinement to DoR → assign
  again — is *sketched* around it, with each arc marked as running or not.
- **Register: honest first.** Truth, then good, then beautiful. Every capability claim carries a run
  id, a log line or a ledger row. Anything unbuilt is labelled unbuilt. The July draft's instinct —
  *"roughly half of the engineering here consists of failures that got promoted into design
  decisions"* — is the spine, and this milestone produced a lot of new material for it.

## Where we actually got to

Be careful here: this is the section that decides whether the post is honest.

### Runs today, with evidence

| Claim | Evidence |
|---|---|
| A board decides which repository a ticket's work lands in | `target resolved external_id=624 scope=4 team=bronze repo=webgrip/erfbeeld branch=main rule=4` |
| A ticket assignment produces a real PR in the right repo | **webgrip/erfbeeld#8**, opened by `agent-builder` from VIK-624, 2026-07-30 |
| The board is told, with the link | Comment on VIK-624; and on VIK-586 for a run that opened nothing |
| Ploeg never closes a ticket | VIK-586 settled `done` internally, board stayed `done=false` — DoD is production + telemetry, which Ploeg cannot observe |
| Seven boards route by name, resolved at boot | `target map loaded rules=7`, each `resolved tracker project name=… id=… repo=…` |
| Multi-Role Shifts dispatch as separate workloads | bronze fanned out `builder` → `reviewer` + `devops`, each its own ScaledJob with its own resources |
| Per-run LLM credentials, minted and revoked | `minted per-run key trace=ploeg-…`, LiteLLM ledger rows |
| Workers hold no Kubernetes API authority | `automountServiceAccountToken: false`, own `ploeg-worker` identity |

### Does NOT run today — do not imply otherwise

- **A reviewed pull request.** This is the milestone gate and **it has not been run yet.** The
  reader path is fixed and merged (rc.14) but unproven live. If the post ships before that run, it
  cannot claim review. *Currently the honest sentence is: "the reviewer is wired and about to get
  its first real run".*
- **Per-run forge credentials.** ADR-0013 tier 2 has never worked on this Forgejo: the broker calls
  `/api/v1/admin/users/{bot}/tokens`, which 404s on Forgejo 15.0.2. Every run has used the shared
  token. The boot log said "disabled" and nobody had exercised it.
- **Merge, deploy, telemetry.** Nothing merges. Nothing deploys. No telemetry closes the loop.
- **The refinement/DoR team.** Designed, not built. Blocked on findings reaching the tracker when
  there is no PR.
- **Harness plurality / opencode.** ADR-0051 is still `proposed`.
- **Branch protection.** Agents not merging is convention, not enforcement. The rollout is blocked
  on token scopes.

## The failure museum — this milestone's contributions

These are the best material in the post. Each is verifiable.

1. **The factory worked and told nobody.** A Shift opened a PR, settled `done`, and wrote nothing to
   the board. `notifyHuman` was gated on `needs_human`, so the *success* path was the one that
   stayed silent — and no error appeared anywhere, because no call was made. Underneath it,
   `SetStatus` had never done anything on any path: the caller passed `needs_human`, the provider
   dropped everything that wasn't `done`. Provably dead code, shipped and unnoticed.
2. **The agent edited the wrong repository, correctly.** A ticket saying *"add a note to the erfbeeld
   README"* was assigned to a team whose rule pointed at `webgrip/ploeg`, so the agent dutifully
   edited ploeg's README. It did exactly what it was told. The routing was what lied. (PR #30,
   closed.) This is what motivated boards-decide-the-repo.
3. **The reviewer was trusted on a sentence, and the sentence was false.** Readers were told *"you
   hold no write credential, so a push will be rejected by the forge"*. `AGENT_BUILDER_TOKEN` is
   mandatory on every worker pod, reached the agent through `os.Environ()`, and was baked into the
   clone's `origin`. The only control was an assertion the model could disprove by trying. Telling a
   model a false constraint is the weakest possible control — and worse, it makes the rest of the
   contract less credible.
4. **A reviewer that could not see the work.** The clone is `--depth 50 --branch <base>`, and
   `--depth` implies `--single-branch`, so the branch under review was not in the repository at all
   — while the prompt insisted the checkout was standing on it.
5. **Naming a thing switched it off.** Setting `serviceAccountName: ploeg-worker` — the chart's own
   default — suppressed creation of the account, because the guard read a *name* as "something
   external owns this". Every worker Job then died with
   `serviceaccount "ploeg-worker" not found`. Naming the default and saying nothing were opposites.
6. **Same config, different routing, run to run.** An assignee listed under two teams resolved by Go
   map iteration order. Measured in one process: **168/200 vs 32/200**. The config was valid, the
   behaviour was a coin flip.
7. **Thirty seconds of DNS became a thirty-minute blackout.** k8s-gateway restarted ten times;
   CoreDNS cached the resulting NXDOMAIN for `harbor.webgrip.dev` at the default denial TTL of 1800s
   and kept serving it long after the upstream recovered. Nothing in the cluster could pull a chart
   or an image by hostname. Verified by querying both: k8s-gateway answered `10.0.0.27` while
   CoreDNS still said NXDOMAIN for the same name, and a sibling hostname resolved fine through the
   identical path.
8. **The obvious diagnosis was wrong, and following it would have made things worse.** Readers died
   with `exec: "opencode": executable file not found in $PATH`, which reads as "add the binary".
   Shipping opencode would have turned *failed to start* into *started, reviewed, and threw the
   review away* — ACP and claude-code set no outcome file and populate no findings, so only
   `openhands` and `exec` can return a review at all. The fix was four defects deeper, and the
   reader now runs on the image that was already there.
9. **Removing a waiver revealed what it was hiding.** Narrowing the Kyverno exception to the
   `privileged-dind` hazard label surfaced that non-dind workers fail `run-as-non-root`,
   `privilege-escalation`, `seccomp` and `drop-all-capabilities`. The broad waiver had been
   concealing that for every team, including ones that take no privilege.

## Suggested shape

1. **Cold open** — one ticket, one assignment, and what came back. Use a real run.
2. **~1,000 words of July** — what existed before: KEDA scale-from-zero, per-run LiteLLM keys with
   hard caps, `builder ≠ judge`, the whole thing on owned hardware for cents. Compress hard; it is
   context, not the subject.
3. **The loop diagram** — Dark DevSecFinOps, each arc marked *runs* or *sketched*. This is the
   post's organising image and the honest frame for everything that follows.
4. **The dispatch plane** — teach **Ploeg**, **Shifts / Rounds / Roles**, the **blackboard**. None of
   these words appear in the July draft or in any ADR up to 0051; the reader has never met them.
5. **The middle, where the work is** — boards decide repos; teams are capabilities; a Role is a
   workload. Failures 2, 5, 6 land here.
6. **Security is the interesting part** — failure 3 as the centrepiece. Per-run credentials, why the
   forge broker has never actually worked, and what "enforced" means versus "asked for".
7. **The money** — per-run keys, hard caps, actual figures. FinOps is genuinely earned; use real
   numbers, not the ceiling.
8. **What is not built** — merge, deploy, telemetry, refinement, harness plurality. Say it plainly.
9. **Close** — the loop, and which arc is next.

## Reusable from the July bundle

- `BLOGPOST-dark-factory.review.md` — publish checklist, and the **consent check** on two anonymised
  quotes from a private Discord thread. Still unresolved; still applies.
- `BLOGPOST-dark-factory.hn.md` — eight prepared objection answers. #7 still lands verbatim:
  *"So it's just a CI job. What's new here?"* → *"exactly, and that's the thesis."*
- `BLOGPOST-dark-factory.research.md` — the evidence-gathering pattern to repeat.
- Platform variants get **regenerated**, not edited.

## Only you can do these

- **The read-aloud ownership pass.** HN and Lobsters ban AI-generated prose. The words have to
  become yours. No agent can do this step, including this one.
- **The consent check** on the two carried-over quotes.
- **The manifests decision** — link the repo in the footer, or say the paths are from a private one.

## Before publishing, re-verify

Every number in the July draft is frozen at 2026-07-19 and most are now wrong — 33 open tickets, six
dashboards, agent-runner 1.0.0, `$0.064`. Re-derive anything quoted. And re-check the "runs today"
table above against the cluster on the day you publish, because half of it is younger than a week.
