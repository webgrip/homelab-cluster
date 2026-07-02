# Runbook: New-machine setup (continue working from a fresh clone)

How to get a working local environment against the **existing** cluster on a new
machine. A `git clone` gives you the manifests and all tooling *config*, but is
missing two things: the pinned binaries (mise solves this) and the gitignored
local secret/state files. The single irreplaceable file is **`age.key`** — it
gates all SOPS decryption, `talhelper genconfig`, and the safety hooks.

> This is **dev-environment** setup against the live cluster — not a cluster
> bootstrap. Do **not** run `just bootstrap-talos` / `just bootstrap-apps` /
> `just talos-reset` as part of this; those provision or wipe nodes. See the
> bottom of this page.

## What you must carry over vs. regenerate

| File / dir | Role | Regenerable? |
| --- | --- | --- |
| `age.key` | SOPS AGE private key (`SOPS_AGE_KEY_FILE`). Decrypts every `*.sops.yaml`, including `talos/talsecret.sops.yaml`. | **No — copy it.** Everything else depends on it. |
| `talos/clusterconfig/` + `talos/talosconfig` | Generated Talos node configs + talosctl context (`TALOSCONFIG`). | Yes — `just talos-generate-config` (needs `age.key`). |
| `kubeconfig` | Cluster API access (`KUBECONFIG`). | Yes — fetch via `talhelper gencommand kubeconfig`, or copy. |
| `.mise.local.toml` | Machine-local env: Grafana SA token + Discord webhook. | Copy, or recreate from the committed template. Optional. |
| `.claude/settings.local.json` | Machine-local Claude permissions + enabled MCP servers. | Optional — re-enable MCP on first use. |
| `cloudflare-tunnel.json`, `github-deploy.key{,.pub}`, `github-push-token.txt` | Bootstrap / Flux-push secrets at repo root. | Copy **only if** you'll bootstrap a cluster or push as Flux. Not needed for day-to-day manifest editing. |

The canonical list of tooling-required local files is `.worktreeinclude` in the
repo root.

## System prerequisites (not managed by mise)

- **git**, and **mise** installed + activated in your shell.
- **Docker**, running — `scripts/run-flux-local-test.sh` runs flux-local in a
  container.
- **LAN / WireGuard access to `10.0.0.0/24`** — `kubeconfig`, `talosconfig`, and
  both MCP endpoints (`mcp-grafana.webgrip.dev`, `k8s-mcp.webgrip.dev`) are
  LAN-only via split-DNS.
- **A browser** — `just bao-login` authenticates to OpenBao via Authentik OIDC.

## Steps

```bash
# ── 0. System prereqs (once per machine) ───────────────────────────────
curl https://mise.run | sh
echo 'eval "$(~/.local/bin/mise activate zsh)"' >> ~/.zshrc && exec zsh
# (Docker must also be installed and running.)

# ── 1. Clone ───────────────────────────────────────────────────────────
git clone <repo-url> ~/projects/webgrip/homelab-cluster
cd ~/projects/webgrip/homelab-cluster

# ── 2. Carry over the irreplaceable secret from the old machine ────────
scp OLDHOST:~/projects/webgrip/homelab-cluster/age.key ./age.key
chmod 600 age.key
#   Optional bootstrap/push secrets (only if bootstrapping or pushing as Flux):
#   scp OLDHOST:'.../{cloudflare-tunnel.json,github-deploy.key,github-deploy.key.pub,github-push-token.txt}' ./

# ── 3. Install the whole pinned toolchain (+ venv, + lefthook) ─────────
mise trust && mise trust .mise.local.toml 2>/dev/null; mise install

# ── 4. Regenerate Talos config from the committed SOPS secret ──────────
#     Decrypts talsecret.sops.yaml with age.key → talos/clusterconfig/ + talosconfig
mise exec -- just talos-generate-config

# ── 5. Fetch a fresh kubeconfig from a node (needs LAN/WireGuard) ───────
mise exec -- bash -c 'cd talos && talhelper gencommand kubeconfig \
  --extra-flags="$(git rev-parse --show-toplevel) --force" | bash'
#     Can't reach the cluster? scp the kubeconfig over instead.

# ── 6. Recreate machine-local env (optional) ───────────────────────────
scp OLDHOST:~/projects/webgrip/homelab-cluster/.mise.local.toml ./.mise.local.toml
#     Or edit the committed REPLACE_WITH_* template values by hand.
```

## Verify

```bash
mise exec -- sops -d kubernetes/components/sops/cluster-secrets.sops.yaml >/dev/null && echo "OK sops"
mise exec -- talosctl version --short        && echo "OK talosctl"
mise exec -- kubectl get nodes               && echo "OK kube API"
mise exec -- flux check                       && echo "OK flux"
./scripts/run-flux-local-test.sh             && echo "OK flux-local validation"
mise exec -- just bao-login                   # OpenBao via Authentik OIDC (browser)
```

If SOPS decrypt succeeds, `kubectl get nodes` returns the five nodes, and
flux-local passes, the environment is fully set up. Once mise shell activation is
in place and you've `cd`'d into the repo, the env (`KUBECONFIG`,
`SOPS_AGE_KEY_FILE`, `TALOSCONFIG`) auto-loads, so you can drop the
`mise exec --` prefix in an interactive shell.

## Notes / gotchas

- **`age.key` cannot be regenerated.** Without it, steps 4–6, the verify block,
  and the `guard-secrets` hook all fail. Treat the transfer channel (and any
  tarball that bundles it) as secret material.
- **Step 5 needs the cluster reachable** — `talosctl kubeconfig` contacts a node.
  Off-LAN, bring up WireGuard first or `scp` the `kubeconfig` over.
- **mise does the heavy lifting** in step 3: installs sops, age, kubectl, flux,
  talosctl, talhelper, helm, kustomize, kubeconform, gitleaks, yamllint, just,
  task, bao — all version-pinned — plus creates `.venv` and runs
  `lefthook install` via the `postinstall` hook.

## ⚠️ Do NOT run these as part of setup

These provision or wipe a **new** cluster — they are not part of getting your dev
environment running against the live one:

```bash
just bootstrap-talos     # applies machine config + bootstraps etcd (DESTRUCTIVE to nodes)
just bootstrap-apps      # installs Flux/Helmfile onto a fresh cluster
just talos-reset         # wipes nodes
```
