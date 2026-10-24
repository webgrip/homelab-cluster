#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PASS, FAIL, WARN, MANUAL = "PASS", "FAIL", "WARN", "MANUAL"
AUTHORS = ("auto", "human", "agent")
MERGE_STYLES = ("merge", "rebase", "squash")

LOCKFILES = {
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "composer.lock", "Cargo.lock", "go.sum", "poetry.lock", "uv.lock", "Pipfile.lock",
    "Gemfile.lock", "flake.lock", "mix.lock", "pubspec.lock", "packages.lock.json",
    "gradle.lockfile",
}
MANIFESTS = {
    "package.json", "composer.json", "Cargo.toml", "go.mod", "pyproject.toml", "Pipfile",
    "Gemfile", "pom.xml", "build.gradle", "build.gradle.kts", "mix.exs", "pubspec.yaml",
    "setup.py", "setup.cfg",
}
REQUIREMENTS_RE = re.compile(r"(^|/)requirements[^/]*\.(txt|in)$")
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|specs?|testdata|fixtures|__snapshots__)/"
    r"|(^|/)test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|Tests?\.(php|java|kt|cs)$|_spec\.rb$|\.snap$")
GATE_CONFIG_RE = re.compile(
    r"^\.(github|forgejo|gitea)/workflows/|^\.gitlab-ci\.ya?ml$|^\.gitlab/ci/"
    r"|^\.woodpecker(/|\.ya?ml$)|^\.circleci/|^\.buildkite/|(^|/)Jenkinsfile$"
    r"|^azure-pipelines\.ya?ml$|^\.drone\.ya?ml$|^bitbucket-pipelines\.ya?ml$"
    r"|^\.pre-commit-config\.ya?ml$|(^|/)\.?codecov\.ya?ml$|^CODEOWNERS$|^\.(github|gitlab|forgejo|gitea)/CODEOWNERS$"
    r"|(^|/)(conftest\.py|pytest\.ini|tox\.ini|\.coveragerc|phpunit\.xml(\.dist)?|phpstan\.neon(\.dist)?"
    r"|psalm\.xml|jest\.config\.[cm]?[jt]s|vitest\.config\.[cm]?[jt]s|karma\.conf\.js"
    r"|\.eslintrc[^/]*|eslint\.config\.[cm]?js|\.golangci\.ya?ml|clippy\.toml|\.rubocop\.yml)$")
MIGRATION_RE = re.compile(r"(^|/)(migrations?|migrate|alembic/versions)/")
JUDGE_PATH_RE = re.compile(r"(^|/)(ci|\.ci|scripts)/|(^|/)(Makefile|justfile|Taskfile\.ya?ml)$")
WEAKENING = (
    ("test skipped or disabled", "any", re.compile(
        r"@pytest\.mark\.(skip|xfail)|@unittest\.skip|pytest\.skip\(|\bt\.Skip(Now|f)?\("
        r"|#\[ignore\]|@(Disabled|Ignore)\b|markTest(Skipped|Incomplete)\("
        r"|\bx(it|describe|test)\s*\(|\b(it|describe|test)\.(skip|todo)\s*\(")),
    ("special-cased for a test", "any", re.compile(
        r"special[- ]?case[sd]?\b.{0,40}\btest|\bif\b.{0,60}\b(PYTEST_CURRENT_TEST|JEST_WORKER_ID|VITEST)\b",
        re.I)),
    ("focused test silences the rest", "any", re.compile(
        r"\b(fit|fdescribe)\s*\(|\b(it|describe|test)\.only\s*\(")),
    ("checker suppressed", "any", re.compile(
        r"eslint-disable|@ts-(ignore|expect-error|nocheck)|#\s*type:\s*ignore|#\s*noqa"
        r"|//\s*nolint|@phpstan-ignore|@psalm-suppress|#!?\[allow\(|@SuppressWarnings"
        r"|pragma:\s*no cover|istanbul ignore|c8 ignore")),
    ("run exits before the tests judge it", "judge", re.compile(
        r"\bsys\.exit\(\s*0?\s*\)|\bos\._exit\(\s*0\s*\)|raise\s+(unittest\.)?SkipTest\b"
        r"|\bprocess\.exit\(\s*0?\s*\)")),
    ("gate made unable to fail", "judge", re.compile(
        r"continue-on-error:\s*true|allow_failure:\s*true|\|\|\s*true\b|--no-verify\b"
        r"|\bset \+e\b")),
)
CONFLICT_MARKER_RE = re.compile(r"^(<{7}|>{7}) \S")
FIXUP_RE = re.compile(r"^(fixup!|squash!|amend!)|^(wip|tmp)\b", re.I)
CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|perf|refactor|revert|docs|style|test|build|ci|chore)(\([\w./,-]+\))?!?: \S")
AGENT_TRAILER_RE = re.compile(
    r"^(assisted-by|generated-by):|^co-authored-by:.*\b(claude|copilot|codex|devin|"
    r"openhands|cursor|jules|aider|gemini|agent|bot)\b", re.I | re.M)
ASSERTION_RE = re.compile(
    r"\bassert|\bexpect\s*\(|\.should\b|\$this->assert|\bAssert\.|\brequire\.\w+\(")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
HEADING_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s+(.+?)|\*\*(.+?)\*\*:?)\s*$", re.M)
BODY_SECTIONS = {
    "what and why": re.compile(
        r"\b(summary|what|why|description|context|motivation|samenvatting|wat|waarom)\b", re.I),
    "verification": re.compile(r"\b(verif\w*|test\w*|evidence|bewijs|getest)\b", re.I),
    "risk": re.compile(r"\b(risks?|risico\w*|impact|limitations?|beperking\w*)\b", re.I),
    "rollback": re.compile(r"\b(roll ?back|revert\w*|terugdra\w*)\b", re.I),
}


class GitError(Exception):
    pass


@dataclass
class Change:
    status: str
    path: str
    old_path: str | None = None
    similarity: int = 100

    def is_test(self) -> bool:
        return bool(TEST_PATH_RE.search(self.path))

    def was_test(self) -> bool:
        return bool(TEST_PATH_RE.search(self.old_path or self.path))


@dataclass
class Report:
    rows: list[dict] = field(default_factory=list)

    def add(self, status: str, group: str, criterion: str, detail: str = "") -> None:
        self.rows.append({"status": status, "group": group, "criterion": criterion,
                          "detail": detail})

    @property
    def failed(self) -> bool:
        return any(r["status"] == FAIL for r in self.rows)


def git(repo: Path, *args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(repo), "-c", "core.quotePath=false", *args],
                          capture_output=True, text=True)
    if proc.returncode not in ok:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip() or proc.returncode}")
    return proc


def resolve(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()


def changes_between(repo: Path, merge_base: str, head: str) -> list[Change]:
    fields = git(repo, "diff", "--name-status", "-M", "-z", merge_base, head).stdout.split("\0")
    changes, i = [], 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status[0] in "RC":
            changes.append(Change(status[0], fields[i + 2], fields[i + 1], int(status[1:] or 100)))
            i += 3
        else:
            changes.append(Change(status[0], fields[i + 1]))
            i += 2
    return changes


def changed_line_counts(repo: Path, merge_base: str, head: str) -> dict[str, int]:
    fields = git(repo, "diff", "--numstat", "-M", "-z", merge_base, head).stdout.split("\0")
    counts, i = {}, 0
    while i < len(fields) and fields[i]:
        added, deleted, path = fields[i].split("\t", 2)
        if path:
            i += 1
        else:
            path = fields[i + 2]
            i += 3
        counts[path] = 0 if added == "-" else int(added) + int(deleted)
    return counts


def diff_lines(repo: Path, merge_base: str, head: str):
    diff = git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", merge_base, head).stdout
    old_path, new_path, lineno, in_header = None, None, 0, False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_header, old_path, new_path = True, None, None
        elif in_header and line.startswith("--- "):
            old_path = side_path(line[4:], "a/")
        elif in_header and line.startswith("+++ "):
            new_path = side_path(line[4:], "b/")
        elif (hunk := HUNK_RE.match(line)):
            in_header, lineno = False, int(hunk.group(1))
        elif not in_header and line.startswith("+") and new_path:
            yield "+", new_path, lineno, line[1:]
            lineno += 1
        elif not in_header and line.startswith("-") and old_path:
            yield "-", old_path, 0, line[1:]


def side_path(target: str, prefix: str) -> str | None:
    if target == "/dev/null":
        return None
    return target[len(prefix):] if target.startswith(prefix) else target


def commits_between(repo: Path, base: str, head: str) -> list[dict]:
    log = git(repo, "log", "--format=%H%x00%P%x00%s%x00%B%x1e", f"{base}..{head}").stdout
    commits = []
    for record in log.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, parents, subject, message = record.split("\x00", 3)
        commits.append({"sha": sha[:10], "merge": len(parents.split()) > 1,
                        "subject": subject, "message": message})
    return commits


def basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def listing(items: list[str], limit: int = 6) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" (+{len(items) - limit} more)" if len(items) > limit else "")


def strict(author: str) -> str:
    return FAIL if author == "agent" else WARN


def check_change(commits: list[dict], changes: list[Change], report: Report) -> None:
    if not commits or not changes:
        report.add(FAIL, "change", "the branch carries a change",
                   "no commits or an empty diff against the base — a zombie PR; close it, "
                   "the work already landed or never happened")
    else:
        report.add(PASS, "change", "the branch carries a change",
                   f"{len(commits)} commit(s), {len(changes)} file(s)")


def check_base(repo: Path, base: str, head: str, require_up_to_date: bool,
               report: Report) -> None:
    behind = int(git(repo, "rev-list", "--count", f"{head}..{base}").stdout.strip())
    if behind == 0:
        report.add(PASS, "base", "contains the current base",
                   "checks on the head are checks on the merge result")
    else:
        report.add(FAIL if require_up_to_date else WARN, "base", "contains the current base",
                   f"{behind} base commit(s) missing — green checks on the head never saw "
                   "them; update the branch, or let a merge queue test the merge result")
    merged = git(repo, "merge-tree", "--write-tree", "--no-messages", base, head, ok=(0, 1, 128, 129))
    if merged.returncode == 0:
        report.add(PASS, "base", "merges without conflicts")
    elif merged.returncode == 1:
        report.add(FAIL, "base", "merges without conflicts", "textual conflicts with the base")
    else:
        report.add(MANUAL, "base", "merges without conflicts",
                   "this git has no merge-tree --write-tree (needs 2.38+) — read the forge")


def check_gates(changes: list[Change], lines: list[tuple[str, str, int, str]], author: str,
                allow_test_edits: bool, report: Report) -> None:
    additions = [(path, lineno, text) for sign, path, lineno, text in lines if sign == "+"]
    test_edit_status = WARN if allow_test_edits else strict(author)
    deleted_tests = [c.old_path or c.path for c in changes if c.was_test()
                     and (c.status == "D" or (c.status == "R" and not c.is_test()))]
    edited_tests = [c.path for c in changes if c.was_test() and c.is_test()
                    and (c.status == "M" or (c.status == "R" and c.similarity < 100))]
    added_tests = [c.path for c in changes if c.status in "AC" and c.is_test()]
    gate_config = [c.path for c in changes if GATE_CONFIG_RE.search(c.path)
                   or (c.old_path and GATE_CONFIG_RE.search(c.old_path))]

    if deleted_tests:
        report.add(test_edit_status, "gates", "no test deleted",
                   f"{listing(deleted_tests)} — deleted or renamed out of test discovery; "
                   "say why in the PR, or restore")
    else:
        report.add(PASS, "gates", "no test deleted")
    if edited_tests:
        report.add(test_edit_status, "gates", "existing tests untouched",
                   f"{listing(edited_tests)} — a reviewer confirms each edit tightens or "
                   "follows a stated behavior change, never loosens")
    else:
        report.add(PASS, "gates", "existing tests untouched",
                   f"{len(added_tests)} test file(s) added" if added_tests else "")
    if gate_config:
        report.add(strict(author), "gates", "gate configuration untouched",
                   f"{listing(gate_config)} — CI, test-runner, linter or ownership config: "
                   "the change edits the thing that judges it")
    else:
        report.add(PASS, "gates", "gate configuration untouched")

    weakened = []
    for path, lineno, text in additions:
        judges = bool(TEST_PATH_RE.search(path) or GATE_CONFIG_RE.search(path)
                      or JUDGE_PATH_RE.search(path))
        for label, scope, pattern in WEAKENING:
            if (scope == "any" or judges) and pattern.search(text):
                weakened.append(f"{path}:{lineno} {label}")
    if weakened:
        report.add(strict(author), "gates", "no check weakened", listing(weakened, 8))
    else:
        report.add(PASS, "gates", "no check weakened")

    net_removed: dict[str, int] = {}
    for sign, path, _lineno, text in lines:
        if TEST_PATH_RE.search(path) and ASSERTION_RE.search(text):
            net_removed[path] = net_removed.get(path, 0) + (1 if sign == "-" else -1)
    thinned = [f"{path} (-{n})" for path, n in sorted(net_removed.items()) if n > 0]
    if thinned:
        report.add(test_edit_status, "gates", "no assertion removed",
                   f"{listing(thinned)} — net assertions lost; each removal names the "
                   "behavior change that retired it")
    else:
        report.add(PASS, "gates", "no assertion removed")

    markers = [f"{path}:{lineno}" for path, lineno, text in additions
               if CONFLICT_MARKER_RE.match(text)]
    if markers:
        report.add(FAIL, "gates", "no conflict markers", listing(markers))
    else:
        report.add(PASS, "gates", "no conflict markers")


def check_scope(changes: list[Change], counts: dict[str, int], protected: list[str],
                max_lines: int, max_files: int, report: Report) -> None:
    touched = [c.path for c in changes] + [c.old_path for c in changes if c.old_path]
    hits = sorted({p for p in touched for g in protected if fnmatch.fnmatchcase(p, g)})
    if not protected:
        report.add(MANUAL, "scope", "protected areas untouched",
                   "pass the ticket's Protected areas as --protected globs")
    elif hits:
        report.add(FAIL, "scope", "protected areas untouched", listing(hits))
    else:
        report.add(PASS, "scope", "protected areas untouched", f"{len(protected)} glob(s)")

    reviewable = sum(n for p, n in counts.items() if basename(p) not in LOCKFILES)
    files = len([p for p in counts if basename(p) not in LOCKFILES])
    criterion = f"reviewable size (<= {max_lines} changed lines, <= {max_files} files)"
    if reviewable > max_lines or files > max_files:
        report.add(WARN, "scope", criterion,
                   f"{reviewable} lines in {files} files outside lockfiles — split, stack, "
                   "or say in the PR why it cannot be smaller")
    else:
        report.add(PASS, "scope", criterion, f"{reviewable} lines in {files} files")

    manifests = [c.path for c in changes
                 if basename(c.path) in MANIFESTS or REQUIREMENTS_RE.search(c.path)]
    lockfiles = [c.path for c in changes if basename(c.path) in LOCKFILES]
    if manifests or lockfiles:
        report.add(WARN, "scope", "dependencies unchanged",
                   f"{listing(manifests + lockfiles)} — a reviewer checks each new or bumped "
                   "package (need, licence, maintenance)")
    else:
        report.add(PASS, "scope", "dependencies unchanged")

    migrations = [c.path for c in changes if MIGRATION_RE.search(c.path)]
    if migrations:
        report.add(WARN, "scope", "schema unchanged",
                   f"{listing(migrations)} — expand-only? the running version must work "
                   "against the new schema, and the down-path is written")
    else:
        report.add(PASS, "scope", "schema unchanged")


def check_history(commits: list[dict], merge_style: str, conventional: bool,
                  title: str | None, trailer: re.Pattern | None, body: str,
                  report: Report) -> None:
    own = [c for c in commits if not c["merge"]]
    fixups = [f"{c['sha']} {c['subject']}" for c in own if FIXUP_RE.search(c["subject"])]
    if fixups and merge_style != "squash":
        report.add(FAIL, "history", "no fixup/WIP commits land",
                   f"{listing(fixups)} — squash them; the {merge_style!r} merge style lands them on main")
    else:
        report.add(PASS, "history", "no fixup/WIP commits land",
                   "squash merge folds them" if fixups else "")

    if conventional:
        subjects = [title] if merge_style == "squash" and title else [c["subject"] for c in own]
        off = [s for s in subjects if not CONVENTIONAL_RE.search(s)]
        if merge_style == "squash" and not title:
            report.add(MANUAL, "history", "conventional subject",
                       "squash merge: the PR title becomes the commit — pass it as --title")
        elif off:
            report.add(FAIL, "history", "conventional subject", listing(off, 4))
        else:
            report.add(PASS, "history", "conventional subject")

    if trailer is None:
        report.add(MANUAL, "history", "ticket referenced",
                   "pass the contract's ticket trailer as --trailer REGEX")
    elif any(trailer.search(c["message"]) for c in own) or trailer.search(body):
        report.add(PASS, "history", "ticket referenced")
    else:
        report.add(FAIL, "history", "ticket referenced",
                   f"no commit or PR body matches /{trailer.pattern}/")


def check_description(body: str | None, author: str, report: Report) -> None:
    if body is None:
        report.add(MANUAL, "description", "PR states what/why, verification, risk, rollback",
                   "pass the PR description as --body FILE")
        return
    headings = [" ".join(filter(None, m.groups())) for m in HEADING_RE.finditer(body)]
    missing = [name for name, pattern in BODY_SECTIONS.items()
               if not any(pattern.search(h) for h in headings)]
    if missing:
        report.add(strict(author), "description", "PR states what/why, verification, risk, rollback",
                   "no heading for: " + ", ".join(missing))
    else:
        report.add(PASS, "description", "PR states what/why, verification, risk, rollback")


def add_forge_lines(author: str, report: Report) -> None:
    report.add(MANUAL, "forge", "required checks green on the merge result",
               "none skipped, soft-failed, or re-run until green without a flaky-test ticket")
    reviewer = ("a human, never the authoring agent or another run of it" if author == "agent"
                else "someone other than the author")
    report.add(MANUAL, "forge", "approved on the current head", reviewer +
               "; a push after approval voids it")
    report.add(MANUAL, "forge", "blocking threads resolved", "nits never block")
    report.add(MANUAL, "forge", "ticket Verification executed, output in the PR",
               "not promised, not the agent's own log alone")
    report.add(MANUAL, "forge", "ships dark or safe", "unfinished behavior behind a default-off "
               "flag; the rollback is a revert or a flag flip")


def render(meta: dict, report: Report) -> str:
    symbols = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn ", MANUAL: "manual"}
    out = [f"base: {meta['base']} ({meta['base_sha']})   head: {meta['head']} "
           f"({meta['head_sha']})   author: {meta['author']}", ""]
    current = None
    for row in report.rows:
        if row["group"] != current:
            current = row["group"]
            out.append(f"  {current}")
        detail = f"  — {row['detail']}" if row["detail"] else ""
        out.append(f"    [{symbols[row['status']]}] {row['criterion']}{detail}")
    fails = [r for r in report.rows if r["status"] == FAIL]
    warns = [r for r in report.rows if r["status"] == WARN]
    out.append("")
    if fails:
        out.append(f"VERDICT: not mergeable — {len(fails)} blocker(s). Send it back with a "
                   "comment naming each; do not fix it inside the review.")
    elif warns:
        out.append(f"VERDICT: no mechanical blocker; {len(warns)} warning(s) need a stated "
                   "reason in the PR. The MANUAL lines are the forge's and the reviewer's.")
    else:
        out.append("VERDICT: no mechanical blocker. The MANUAL lines are the forge's and "
                   "the reviewer's.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a branch against the mechanical half of the Definition of "
                    "Mergeable. Reads git only; never touches the forge or the network.",
        epilog="example: merge_check.py --base origin/main --head pr-42 --author agent "
               "--protected 'deploy/*' --trailer 'VIK-\\d+' --body pr.md --conventional")
    parser.add_argument("--repo", default=".", help="the checkout (default: .)")
    parser.add_argument("--base", required=True, help="target branch ref, e.g. origin/main")
    parser.add_argument("--head", default="HEAD", help="the PR head ref (default: HEAD)")
    parser.add_argument("--author", default="auto", choices=AUTHORS,
                        help="agent tightens WARN to FAIL on tests, gates and the PR body; "
                             "auto = agent when a commit carries Assisted-by, Generated-by, "
                             "or an agent Co-authored-by")
    parser.add_argument("--protected", action="append", default=[], metavar="GLOB",
                        help="the ticket's protected areas; fnmatch, * crosses directories")
    parser.add_argument("--allow-test-edits", action="store_true",
                        help="the ticket scopes changes to existing tests: an agent's test "
                             "edits and deletions WARN instead of FAIL")
    parser.add_argument("--max-lines", type=int, default=400,
                        help="reviewable size ceiling, lockfiles excluded (default: 400)")
    parser.add_argument("--max-files", type=int, default=20,
                        help="reviewable spread, lockfiles excluded (default: 20)")
    parser.add_argument("--merge-style", default="merge", choices=MERGE_STYLES)
    parser.add_argument("--conventional", action="store_true",
                        help="require conventional-commit subjects")
    parser.add_argument("--title", default=None, help="the PR title (the squash subject)")
    parser.add_argument("--trailer", default=None, metavar="REGEX",
                        help="the contract's ticket reference, e.g. 'VIK-\\d+'")
    parser.add_argument("--body", default=None, metavar="FILE",
                        help="the PR description, or - for stdin")
    parser.add_argument("--require-up-to-date", action="store_true",
                        help="a branch behind its base FAILs instead of WARNs")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    try:
        body = None
        if args.body == "-":
            body = sys.stdin.read()
        elif args.body:
            body = Path(args.body).read_text()
        trailer = re.compile(args.trailer) if args.trailer else None
        base_sha, head_sha = resolve(repo, args.base), resolve(repo, args.head)
        merge_base = git(repo, "merge-base", base_sha, head_sha).stdout.strip()
        commits = commits_between(repo, base_sha, head_sha)
        changes = changes_between(repo, merge_base, head_sha)
        counts = changed_line_counts(repo, merge_base, head_sha)
        lines = list(diff_lines(repo, merge_base, head_sha))
    except (GitError, FileNotFoundError, re.error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    author = args.author
    if author == "auto":
        author = "agent" if any(AGENT_TRAILER_RE.search(c["message"]) for c in commits) else "human"

    report = Report()
    check_change(commits, changes, report)
    check_base(repo, base_sha, head_sha, args.require_up_to_date, report)
    check_gates(changes, lines, author, args.allow_test_edits, report)
    check_scope(changes, counts, args.protected, args.max_lines, args.max_files, report)
    check_history(commits, args.merge_style, args.conventional, args.title, trailer,
                  body or "", report)
    check_description(body, author, report)
    add_forge_lines(author, report)

    meta = {"base": args.base, "base_sha": base_sha[:10], "head": args.head,
            "head_sha": head_sha[:10], "author": author}
    if args.json:
        print(json.dumps({**meta, "mergeable": not report.failed, "checks": report.rows},
                         indent=2, ensure_ascii=False))
    else:
        print(render(meta, report))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
