# guard-secrets

The secrets-handling floor for Webgrip repos, shipped as a Claude Code
plugin: a `PreToolUse` hook that **blocks an edit/write before it lands** if
it would leak a plaintext secret, plus a background-knowledge skill so the
agent follows the compliant path in the first place.

The Claude Code twin of `opencode/plugins/guard-secrets.js` — one secrets
floor, enforced in both tools.

**The three hard rules** (the hook denies on each): no decrypted secret
artifacts on disk; `*.sops.yaml` must stay ciphertext (`ENC[`); no plaintext
secrets (best-effort `gitleaks` scan when installed).

**Install (Claude Code plugin — recommended for this skill):**

```text
/plugin install guard-secrets@ai-skills
```

The hook activates on install (after you trust the marketplace). It is
fail-open on its own errors — a same-machine convenience guard, not a
security boundary; MR review and protected branches are that.

**Install (`npx skills`) — read this first:** `npx skills add … -s guard-secrets`
copies the skill *and* `hooks/hooks.json`, but nothing registers the hook, so
**the guard does not fire** — you get the background knowledge only. The plugin
route above is the one that enforces. To enforce from the npx layout, register it
yourself in `~/.claude/settings.json` (the command runs through a shell, and
`${CLAUDE_PLUGIN_ROOT}` does not exist outside the plugin loader):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          { "type": "command", "command": "python3 \"$HOME/.agents/skills/guard-secrets/scripts/guard_secrets.py\"" }
        ]
      }
    ]
  }
}
```

**opencode:** the equivalent plugin ships via `scripts/install_opencode.sh`
(`opencode/plugins/guard-secrets.js`), so opencode users are already covered.
