#!/usr/bin/env python3
"""Automated dependency-update PR reviewer using GitHub Models API.

Reads the system prompt from .github/agents/renovate-reviewer.md (strips YAML
frontmatter). Falls back to a minimal built-in prompt if the file is absent.

Required env vars:
  GITHUB_TOKEN       – workflow token (needs models:read + pull-requests:write)
  GITHUB_REPOSITORY  – owner/repo
  PR_NUMBER          – pull request number

Optional env vars:
  REVIEW_MODEL       – GitHub Models model ID (default: openai/gpt-4o)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

# ── Configuration ─────────────────────────────────────────────────────────────
TOKEN      = os.environ["GITHUB_TOKEN"]
REPO       = os.environ["GITHUB_REPOSITORY"]
PR_NUMBER  = os.environ["PR_NUMBER"]
MODEL      = os.environ.get("REVIEW_MODEL", "openai/gpt-4o")
AGENT_FILE = ".github/agents/renovate-reviewer.md"
SENTINEL   = "<!-- renovate-ai-review -->"

# chars sent to the model; keep cost/latency reasonable
MAX_DIFF  = 15_000
MAX_BODY  = 8_000

FALLBACK_PROMPT = """\
You are a dependency update reviewer for software projects.

Given a Renovate or Dependabot pull request, produce a structured risk
assessment in Markdown. Cover: what changed, risk level
(🟢 Low / 🟡 Caution / 🟠 High / 🔴 Blocking / ⬜ Unknown), local impact
on this repository, a pre-merge checklist, and a final recommendation
(Merge / Merge after checks / Hold / Split PR).

Be concise, evidence-based, and specific to the files shown.
"""

# ── GitHub REST helpers ────────────────────────────────────────────────────────
def _gh(path, method="GET", accept="application/vnd.github+json", body=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode() if body else None,
        method=method,
    )
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        raw = r.read()
    return json.loads(raw) if accept == "application/vnd.github+json" else raw.decode("utf-8", errors="replace")


def get_pr():
    return _gh(f"/repos/{REPO}/pulls/{PR_NUMBER}")


def get_diff():
    return _gh(f"/repos/{REPO}/pulls/{PR_NUMBER}", accept="application/vnd.github.diff")


def get_files():
    return _gh(f"/repos/{REPO}/pulls/{PR_NUMBER}/files")


def find_sentinel_comment():
    comments = _gh(f"/repos/{REPO}/issues/{PR_NUMBER}/comments")
    for c in comments:
        if SENTINEL in c.get("body", ""):
            return c["id"]
    return None


def upsert_comment(text, existing_id=None):
    full = f"{SENTINEL}\n{text}"
    if existing_id:
        _gh(f"/repos/{REPO}/issues/comments/{existing_id}", method="PATCH", body={"body": full})
        print(f"[review] Updated existing comment id={existing_id}")
    else:
        _gh(f"/repos/{REPO}/issues/{PR_NUMBER}/comments", method="POST", body={"body": full})
        print("[review] Posted new comment")


# ── GitHub Models API ──────────────────────────────────────────────────────────
def call_models(system_prompt, user_prompt):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "max_tokens": 4096,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        "https://models.github.ai/inference/chat/completions",
        data=json.dumps(payload).encode(),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode(errors="replace")
        print(f"[review] Models API HTTP {exc.code}: {err_body}", file=sys.stderr)
        sys.exit(1)
    return result["choices"][0]["message"]["content"]


# ── Agent prompt ───────────────────────────────────────────────────────────────
def load_system_prompt():
    if os.path.exists(AGENT_FILE):
        with open(AGENT_FILE) as fh:
            content = fh.read()
        # Strip YAML frontmatter (between the first two --- delimiters)
        parts = re.split(r"^---[ \t]*$", content, flags=re.MULTILINE)
        if len(parts) >= 3:
            return parts[2].strip()
        return content.strip()
    print(f"[review] {AGENT_FILE} not found – using built-in fallback prompt")
    return FALLBACK_PROMPT.strip()


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    pr    = get_pr()
    diff  = get_diff()
    files = get_files()

    title  = pr["title"]
    author = pr["user"]["login"]
    labels = ", ".join(lbl["name"] for lbl in pr.get("labels", [])) or "none"
    body   = (pr.get("body") or "")[:MAX_BODY]
    flist  = "\n".join(
        f"- `{f['filename']}` (+{f['additions']} -{f['deletions']})"
        for f in files
    )
    diff_text = diff[:MAX_DIFF]
    if len(diff) > MAX_DIFF:
        diff_text += "\n\n… [diff truncated — review full diff on GitHub] …"

    user_prompt = f"""\
Review this dependency update pull request.

**Title:** {title}
**Author:** {author}
**Labels:** {labels}
**Repository:** {REPO}

### Changed files
{flist}

### PR body / release notes
{body or "_No PR body._"}

### Diff
```diff
{diff_text}
```

Produce the full structured review as specified in your instructions.
Be specific about the files, versions, and workloads found above.
""".strip()

    system_prompt = load_system_prompt()

    print(f"[review] Calling {MODEL} via GitHub Models API…")
    review = call_models(system_prompt, user_prompt)

    existing_id = find_sentinel_comment()
    upsert_comment(review, existing_id)
    print("[review] Done.")


if __name__ == "__main__":
    main()
