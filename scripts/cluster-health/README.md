# Nightly cluster-health digest (local)

The cluster MCP (`k8s-mcp.webgrip.dev`, `mcp-grafana.webgrip.dev`) is **LAN-only**, so this
can't run as a remote Claude routine. It runs **locally** via a systemd *user* timer that
invokes a headless `claude -p` read-only audit and posts the result to Discord. It only
fires when this machine is on and on the LAN (`Persistent=true` catches up a missed run).

## Setup

1. Add the Discord webhook to the gitignored machine-local env:
   ```toml
   # .mise.local.toml  → [env]
   DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/XXXX/YYYY"
   ```
2. Test it once by hand:
   ```bash
   ./scripts/cluster-health/digest.sh
   ```
3. Install + enable the user timer:
   ```bash
   mkdir -p ~/.config/systemd/user
   ln -sf "$PWD/scripts/cluster-health/claude-cluster-health.service" ~/.config/systemd/user/
   ln -sf "$PWD/scripts/cluster-health/claude-cluster-health.timer"   ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now claude-cluster-health.timer
   loginctl enable-linger "$USER"   # so it runs even when you're not logged in
   ```
4. Inspect:
   ```bash
   systemctl --user list-timers claude-cluster-health.timer
   journalctl --user -u claude-cluster-health.service -n 50
   ```

## Safety

`digest.sh` runs `claude -p --dangerously-skip-permissions` so cron never hangs on a
prompt — but the repo's `PreToolUse` `guard-destructive.sh` hook still fires and blocks any
cluster mutation. The prompt is read-only; the hook is the backstop. Change the schedule in
the `.timer` (`OnCalendar=`).
