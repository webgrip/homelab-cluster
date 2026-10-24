#!/usr/bin/env python3
"""Check one ticket body against the skill's gates: intake, ready, agent-ready.

Offline and credential-free: feed it the ticket description (markdown or
TipTap/board HTML — auto-detected, English or Dutch headings) and the gate you
want to pull the ticket into. It reports, per criterion, PASS / FAIL / WARN /
MANUAL. What it cannot see it says so rather than guessing: board-level facts
(WIP, labels, estimation fields) and every judgement call come back MANUAL.

    python3 ticket_lint.py ticket.md --gate ready
    python3 ticket_lint.py ticket.html --gate agent-ready --title "ci: bring pipeline under 8 min"
    cat body.md | python3 ticket_lint.py - --gate ready --type bug --json

Gates are CUMULATIVE: `ready` includes intake; `agent-ready` includes both.
Work type (change|feature|bug|spike|chore) is inferred from the sections
present; override with --type. Exit codes: 0 = no FAIL, 1 = at least one FAIL,
2 = bad input. WARNs never fail the run — they are judgement calls.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

GATES = ("intake", "ready", "agent-ready")
TYPES = ("change", "feature", "bug", "spike", "chore")

# Canonical section -> heading aliases (lowercased), English + Dutch.
SECTIONS = {
    # A plain-language TL;DR may stand in for Problem when the evidence moved to the
    # technical half (refine.md, "Two readers").
    "problem": ("problem", "probleem", "tl;dr", "tldr"),
    "outcome": ("outcome", "uitkomst"),
    "criteria": ("acceptance criteria", "acceptatiecriteria"),
    "verification": ("verification", "verificatie", "technical verification",
                     "technische verificatie"),
    "scope": ("not in scope", "out of scope", "niet in scope"),
    "questions": ("open questions", "open vragen"),
    "context": ("context", "gates & links", "gates &amp; links", "links",
                "technical context", "technische context"),
    "approach": ("approach", "aanpak"),
    "repro": ("reproduction", "reproductie", "repro", "steps to reproduce"),
    "environment": ("environment", "omgeving"),
    "impact": ("impact",),
    "question": ("question", "vraag"),
    "timebox": ("timebox",),
    "decide_on": ("decision criteria", "waarop we kiezen", "what we decide on"),
    "decider": ("who decides", "wie beslist", "decider", "beslisser"),
    "protected": ("protected areas", "protected", "do not touch", "beschermde gebieden"),
    "rollback": ("rollback", "rollback plan", "terugdraaipad"),
}

# Words that promise a judgement instead of a fact. Harmless next to a number
# ("30% faster"), a smell on their own ("works well").
JUDGEMENT_WORDS = (
    "good", "well", "nice", "clean", "proper", "properly", "fast", "faster", "quick",
    "improved", "better", "robust", "stable", "reliable", "reliably", "clear",
    "sufficient", "adequate", "user-friendly",
    "goed", "netjes", "voldoende", "beter", "sneller", "snel", "duidelijk", "correct",
    "stabiel", "robuust", "betrouwbaar", "fatsoenlijk", "acceptabel", "gebruiksvriendelijk",
)
NUMBER_RE = re.compile(r"\d")
# Evidence someone can look up: a URL, a path-like token, or a dated reference.
EVIDENCE_RE = re.compile(
    r"https?://|\[[^\]]+\]\([^)]+\)|`[^`]*[/.][^`]*`|\b[\w./-]+\.(?:py|ts|js|php|go|rs|yaml|yml|json|md|vue|tf)\b"
    r"|\b[\w-]+/[\w./-]+:\d+|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:0?[1-9]|[12]\d|3[01])-(?:0?[1-9]|1[0-2])(?:-\d{2,4})?\b"
    r"(?!\s*(?:s\b|sec|min|uur|hours?|days?|dagen|weken|weeks?|ms\b|%|keer|times))", re.I)
PATH_RE = re.compile(r"`[^`]*[/.][^`]*`|\b[\w-]+/[\w.-]+[\w/]", )
COMMAND_RE = re.compile(r"`[^`]+`|<code>[^<]+</code>", re.I)
MD_CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s*(.+)$", re.M)
OWNER_RE = re.compile(r"@\w|\bDRI\b|\b(?:owner|eigenaar|decides|beslist)\b\s*:?\s*\S|"
                      r"\bneeds client\b", re.I)
SPLIT_TITLE_RE = re.compile(r"\s-\s(?:Deel|Part)\s\d+/\d+\s-\s\S", re.I)
# A paragraph line directly above `---` makes it a setext heading, not a rule.
SETEXT_TRAP_RE = re.compile(r"^(?![\s#>|`*+-]|\d+[.)]\s).+\n-{3,}[ \t]*$", re.M)
BLAST_RE = re.compile(r"allowed paths?|blast radius|only touch|may only (?:change|edit)|"
                      r"protected areas?|do[- ]?not[- ]?touch|beschermde|niet aankomen|"
                      r"mag alleen|raakt alleen|scope of change", re.I)
ESCALATION_RE = re.compile(r"escalat|ask a human|human decides|stop and ask|needs a human|"
                           r"vraag een mens|mens beslist", re.I)
DECIDED_RE = re.compile(r"\bdecided\b|\bdecision\b|\bbesloten\b|\bbesluit\b|\brecorded\b|"
                        r"\bvastgelegd\b", re.I)

PASS, FAIL, WARN, MANUAL = "PASS", "FAIL", "WARN", "MANUAL"


class DataError(Exception):
    pass


# --------------------------------------------------------------------- parsing


def looks_like_html(text: str) -> bool:
    return bool(re.search(r"<h[1-6][ >]|<p[ >]|<ul[ >]|<li[ >]", text))


def strip_tags(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", html))


def sections_of(text: str) -> tuple[dict[str, str], list[str]]:
    """Map canonical section -> body text, plus the list of raw headings found."""
    found: dict[str, str] = {}
    raw: list[str] = []
    if looks_like_html(text):
        parts = re.split(r"<h[1-6][^>]*>(.*?)</h[1-6]>", text, flags=re.I | re.S)
        # parts = [preamble, h1, body1, h2, body2, ...]
        pairs = list(zip(parts[1::2], parts[2::2]))
        if parts[0].strip():
            found["preamble"] = parts[0].strip()
        for heading, body in pairs:
            raw.append(strip_tags(heading).strip())
    else:
        pairs = []
        current, buffer = None, []
        fenced = False
        for line in text.splitlines():
            if re.match(r"^\s{0,3}(```|~~~)", line):
                fenced = not fenced
            m = None if fenced else re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*$", line)
            if m:
                if current is not None:
                    pairs.append((current, "\n".join(buffer)))
                current, buffer = m.group(1), []
                raw.append(current.strip())
            elif current is not None:
                buffer.append(line)
            elif line.strip():
                # Text above the first heading, e.g. a "**Source:** <quote, date>" line.
                found["preamble"] = (found.get("preamble", "") + "\n" + line).strip()
        if current is not None:
            pairs.append((current, "\n".join(buffer)))

    for heading, body in pairs:
        key = strip_tags(heading).strip().lower().rstrip(":")
        for canonical, aliases in SECTIONS.items():
            if key in aliases:
                found[canonical] = (found.get(canonical, "") + "\n" + body).strip()
                break
    return found, raw


def checkboxes_of(text: str, section_body: str) -> list[str]:
    """Criterion texts: markdown task-list items or TipTap taskItem <li>s."""
    if looks_like_html(text):
        items = re.findall(r'<li[^>]*data-type="taskItem"[^>]*>(.*?)</li>', section_body,
                           flags=re.I | re.S)
        return [" ".join(strip_tags(i).split()) for i in items]
    return [c.strip() for c in MD_CHECKBOX_RE.findall(section_body)]


def infer_type(body: dict[str, str]) -> str:
    if "repro" in body:
        return "bug"
    if "timebox" in body or "question" in body or "decide_on" in body:
        return "spike"
    return "change"


# ---------------------------------------------------------------------- checks


class Report:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, status: str, gate: str, criterion: str, detail: str = "",
            fixable: bool = False) -> None:
        self.rows.append({"status": status, "gate": gate, "criterion": criterion,
                          "detail": detail, "quick_fix": fixable and status == FAIL})

    @property
    def failed(self) -> bool:
        return any(r["status"] == FAIL for r in self.rows)


def check_intake(title: str | None, body: dict[str, str], plain: str, report: Report) -> None:
    if title is not None:
        name = title.strip()
        if (":" in name and len(name.split(":")[0].split()) <= 3) or SPLIT_TITLE_RE.search(name):
            report.add(PASS, "intake", "title reads `area: what changes`")
        elif len(name.split()) <= 2:
            report.add(FAIL, "intake", "title reads `area: what changes`",
                       f"got {name!r} — a product name describes an installation, not a result",
                       fixable=True)
        else:
            report.add(WARN, "intake", "title reads `area: what changes`",
                       f"got {name!r} — can someone who wasn't there tell what it's about?")
        if len(name) > 70:
            report.add(WARN, "intake", "title <= 70 chars", f"{len(name)} chars")
    else:
        report.add(MANUAL, "intake", "title reads `area: what changes`", "pass --title to check")

    # A spike's Question section stands in for Problem ("the question plus the occasion").
    problem = strip_tags(body.get("problem") or body.get("question") or "")
    if not problem.strip():
        report.add(FAIL, "intake", "Problem section filled",
                   "the one section you fill at intake", fixable=True)
    elif len(problem.split()) < 12:
        report.add(WARN, "intake", "Problem section filled",
                   "very short — what goes wrong, for whom, and what does it cost?")
    else:
        report.add(PASS, "intake", "Problem section filled")
    if body.get("problem") and not re.search(r"^\s{0,3}#{1,6}\s*(problem|probleem)\b|"
                                             r"<h[1-6][^>]*>\s*(problem|probleem)\b",
                                             plain, re.I | re.M):
        report.add(MANUAL, "intake", "Problem heading the board gates on",
                   "a TL;DR stands in for Problem — fine on a two-readers board, "
                   "but a board that gates on a literal Problem heading still needs it")
    if SETEXT_TRAP_RE.search(re.sub(r"(?ms)^\s{0,3}(```|~~~).*?^\s{0,3}\1", "", plain)):
        report.add(WARN, "intake", "horizontal rule has a blank line above it",
                   "text directly above `---` renders as a heading — add a blank line")


def check_ready(raw: str, body: dict[str, str], work_type: str, report: Report) -> None:
    # A spike's Question section stands in for Problem, here as at intake.
    problem = body.get("problem") or body.get("question") or ""
    context = body.get("context", "") + "\n" + body.get("preamble", "")
    if EVIDENCE_RE.search(strip_tags(problem) + " " + problem) or EVIDENCE_RE.search(context):
        report.add(PASS, "ready", "evidence someone can look up",
                   "path/URL/date found in Problem, Context or the source line")
    else:
        report.add(FAIL, "ready", "evidence someone can look up",
                   "no file:line, URL, metric, or dated reference in Problem, Context or "
                   "the source line — "
                   "an unverifiable claim is an open question, not a fact", fixable=True)

    if work_type == "spike":
        check_spike(raw, body, report)
        return  # a spike's readiness is question/timebox/decider, not outcome+criteria

    outcome = strip_tags(body.get("outcome", "")).strip()
    if not outcome:
        report.add(FAIL, "ready", "Outcome: one sentence end-state",
                   "the end state, not the activity", fixable=True)
    elif len(outcome.split()) > 45:
        report.add(WARN, "ready", "Outcome: one sentence end-state",
                   f"{len(outcome.split())} words — is this one outcome or three?")
    else:
        report.add(PASS, "ready", "Outcome: one sentence end-state")

    criteria = checkboxes_of(raw, body.get("criteria", ""))
    if not criteria:
        stray = len(checkboxes_of(raw, raw))
        detail = (f"{stray} checkbox(es) exist but not under an acceptance-criteria heading"
                  if stray else "none found — write them as checkboxes")
        report.add(FAIL, "ready", "acceptance criteria present", detail, fixable=True)
    else:
        report.add(PASS, "ready", "acceptance criteria present", f"{len(criteria)} found")
        for text in criteria:
            lowered = text.lower()
            soft = [w for w in JUDGEMENT_WORDS if re.search(rf"\b{re.escape(w)}\b", lowered)]
            if soft and not NUMBER_RE.search(text):
                report.add(WARN, "ready", "criteria are binary",
                           f"{text[:60]!r} leans on {soft[0]!r} with no number — "
                           "two readers, two conclusions")
        report.add(MANUAL, "ready", "one criterion closes the cheap way out",
                   'ask: "how do I finish this ticket WITHOUT solving the problem?" — '
                   "the answer is the missing criterion")

    verification = strip_tags(body.get("verification", "")).strip()
    if verification:
        report.add(PASS, "ready", "Verification: who proves what, where")
        if not COMMAND_RE.search(body.get("verification", "")) and not NUMBER_RE.search(verification) \
                and len(verification.split()) < 8:
            report.add(WARN, "ready", "Verification names an instrument",
                       "no command, environment, or concrete case visible — "
                       "without a measuring point a criterion is an opinion")
    else:
        report.add(FAIL, "ready", "Verification: who proves what, where",
                   "distinct from the criteria: environment, concrete case, expected result",
                   fixable=True)

    questions = body.get("questions", "")
    # One entry per question: a wrapped bullet's continuation lines belong to it.
    lines: list[str] = []
    for ln in strip_tags(questions).splitlines():
        if not ln.strip(" -*\t"):
            continue
        if lines and not re.match(r"^\s*(?:[-*+]|\d+[.)])\s", ln):
            lines[-1] += " " + ln.strip()
        else:
            lines.append(ln)
    if not lines:
        report.add(PASS, "ready", "open questions empty or owned", "none open")
    else:
        unowned = [ln.strip() for ln in lines if not OWNER_RE.search(ln)]
        if unowned:
            report.add(FAIL, "ready", "open questions empty or owned",
                       f"{len(unowned)} without an owner, e.g. {unowned[0][:50]!r}")
        else:
            report.add(PASS, "ready", "open questions empty or owned",
                       f"{len(lines)} open, all owned — honest, not sloppy")

    if not body.get("scope"):
        report.add(WARN, "ready", "Not-in-scope stated where assumable",
                   "add it when someone could reasonably assume more; delete empty headings")

    if work_type == "bug":
        for key, label in (("repro", "Bug: reproduction steps (expected vs actual)"),
                           ("environment", "Bug: environment (where, since when, how often)")):
            if body.get(key):
                report.add(PASS, "ready", label)
            else:
                report.add(FAIL, "ready", label, "required for a bug", fixable=True)
    if work_type == "chore":
        report.add(MANUAL, "ready", "chore: title + Problem is the whole ticket",
                   "adding empty headings to look thorough makes it worse")


def check_spike(raw: str, body: dict[str, str], report: Report) -> None:
    question = strip_tags(body.get("question", "") or body.get("problem", "")).strip()
    if not question:
        report.add(FAIL, "ready", "Spike: the one question", "no question found", fixable=True)
    elif question.count("?") > 1:
        report.add(WARN, "ready", "Spike: the one question",
                   f"{question.count('?')} question marks — two questions is two spikes")
    else:
        report.add(PASS, "ready", "Spike: the one question")
    if body.get("timebox"):
        report.add(PASS, "ready", "Spike: timebox")
    else:
        report.add(FAIL, "ready", "Spike: timebox",
                   "a spike without a box is a project", fixable=True)
    if body.get("decider") or re.search(r"\bDRI\b|beslisser|who decides|wie beslist",
                                        strip_tags(raw), re.I):
        report.add(PASS, "ready", "Spike: decider named")
    else:
        report.add(FAIL, "ready", "Spike: decider named",
                   "many advise, one decides — name them", fixable=True)
    if body.get("decide_on"):
        report.add(PASS, "ready", "Spike: what we decide on")
    else:
        report.add(WARN, "ready", "Spike: what we decide on",
                   "the comparison criteria (cost, ops burden, lock-in, …)")
    criteria_text = strip_tags(body.get("criteria", ""))
    if DECIDED_RE.search(criteria_text):
        report.add(PASS, "ready", "Spike: done = decided AND recorded")
    else:
        report.add(FAIL, "ready", "Spike: done = decided AND recorded",
                   "without 'decided' + 'recorded' criteria the research repeats in 3 months",
                   fixable=True)


def check_agent_ready(raw: str, body: dict[str, str], report: Report) -> None:
    approach = body.get("approach", "")
    if not approach.strip():
        report.add(FAIL, "agent-ready", "Approach: steps naming real repo paths",
                   "an agent needs a route, not just a destination", fixable=True)
    elif PATH_RE.search(approach):
        report.add(PASS, "agent-ready", "Approach: steps naming real repo paths")
    else:
        report.add(FAIL, "agent-ready", "Approach: steps naming real repo paths",
                   "no path-like reference found in the Approach")

    verification = body.get("verification", "")
    if COMMAND_RE.search(verification):
        report.add(PASS, "agent-ready", "verification an agent can run itself")
    else:
        report.add(FAIL, "agent-ready", "verification an agent can run itself",
                   "no runnable command found — a human-only check means a human in the loop")

    if body.get("protected", "").strip() or BLAST_RE.search(strip_tags(raw)):
        report.add(PASS, "agent-ready", "protected areas / blast radius stated")
    else:
        report.add(FAIL, "agent-ready", "protected areas / blast radius stated",
                   "say which paths may change and which are do-not-touch — "
                   "silent scope drift is the classic agent failure")

    if ESCALATION_RE.search(strip_tags(raw)):
        report.add(PASS, "agent-ready", "escalation point stated")
    else:
        report.add(FAIL, "agent-ready", "escalation point stated",
                   "name what needs a human (decision, credential, production touch)")

    report.add(MANUAL, "agent-ready", "effort <= M and uncertainty low/med",
               "estimation lives on the board (labels/fields) — check the contract's taxonomy")


# ---------------------------------------------------------------------- output


def render(target: str, work_type: str, report: Report) -> str:
    symbols = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn ", MANUAL: "manual"}
    out = [f"gate: {target}   type: {work_type}", ""]
    current = None
    for row in report.rows:
        if row["gate"] != current:
            current = row["gate"]
            out.append(f"  {current}")
        detail = f"  — {row['detail']}" if row["detail"] else ""
        out.append(f"    [{symbols[row['status']]}] {row['criterion']}{detail}")

    fails = [r for r in report.rows if r["status"] == FAIL]
    quick = [r for r in fails if r["quick_fix"]]
    out.append("")
    if not fails:
        out.append(f"VERDICT: passes {target!r} — the MANUAL lines are still yours to check.")
    elif quick and len(fails) <= 3:
        out.append(f"VERDICT: not {target!r} yet — {len(fails)} unmet, all cheap. "
                   "The ten-minute rule: fix them now and pull it through.")
    elif len(fails) <= 3:
        out.append(f"VERDICT: not {target!r} — {len(fails)} unmet; needs a refinement "
                   "conversation, not a ten-minute fix. Send it back with a comment naming "
                   "exactly what is absent.")
    else:
        out.append(f"VERDICT: not {target!r} — {len(fails)} unmet. Too much missing for the "
                   "ten-minute rule; this is a refinement conversation. Send it back with a "
                   "comment naming exactly what is absent.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a ticket body against the intake / ready / agent-ready gates.",
        epilog="Feed it the description text; it never touches the network.")
    parser.add_argument("body", help="file with the ticket body (markdown or HTML), or - for stdin")
    parser.add_argument("--gate", default="ready", choices=GATES)
    parser.add_argument("--title", default=None, help="the ticket title, to check its shape")
    parser.add_argument("--type", default=None, choices=TYPES, dest="work_type",
                        help="work type (default: inferred from the sections present)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        text = sys.stdin.read() if args.body == "-" else Path(args.body).read_text()
    except FileNotFoundError:
        print(f"error: {args.body}: no such file", file=sys.stderr)
        return 2
    if not text.strip():
        print("error: empty ticket body", file=sys.stderr)
        return 2

    body, _raw_headings = sections_of(text)
    work_type = args.work_type or infer_type(body)

    report = Report()
    check_intake(args.title, body, text, report)
    if args.gate in ("ready", "agent-ready"):
        check_ready(text, body, work_type, report)
    if args.gate == "agent-ready":
        check_agent_ready(text, body, report)

    if args.json:
        print(json.dumps({"gate": args.gate, "type": work_type,
                          "passes": not report.failed, "checks": report.rows},
                         indent=2, ensure_ascii=False))
    else:
        print(render(args.gate, work_type, report))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
