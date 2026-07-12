# Kubeconfig setup for multiple clusters

How to set up your Mac so you can work with several Kubernetes clusters — each one only reachable over its own VPN — without ever running a command against the wrong cluster.

## The 30-second glossary

- A **kubeconfig** is a file with the address of a Kubernetes cluster and the credentials to talk to it. `kubectl` reads it to know where to send commands.
- A **context** is a named entry inside a kubeconfig ("this cluster, as this user"). Switching context = switching cluster.
- The `KUBECONFIG` environment variable tells `kubectl` which file to use. If it's empty, `kubectl` falls back to `~/.kube/config`.

## The rules

1. **One kubeconfig file per cluster.** Never merge clusters into one big file — merged files make it easy to target the wrong cluster and painful to remove or rotate credentials later.
2. **No `~/.kube/config`.** We deliberately don't create the default file. With no fallback, `kubectl` only works when you've *explicitly* chosen a cluster (see "Daily use"). This is what protects you from "oops, that went to prod".
3. **Name each context after the VPN or environment it belongs to** (`homelab`, `acme-prod`) — not the default `admin@kubernetes`. When your prompt says `acme-prod`, you know which VPN needs to be on.

## One-time setup

Install the tools (assumes [Homebrew](https://brew.sh)):

```sh
brew install kubectl kubie kube-ps1 mise
mkdir -p ~/.kube/clusters
```

- **kubie** opens a sub-shell pinned to one cluster — each terminal tab can point at a different cluster.
- **kube-ps1** shows the current cluster in your prompt.
- **mise** loads per-project environment variables when you `cd` into a repo (we use it to auto-select the right kubeconfig inside cluster repos).

Add this to your `~/.zshrc`:

```sh
# mise — per-project env (KUBECONFIG, tool versions) on cd
eval "$(mise activate zsh)"

# kube-ps1 — show kube context in prompt, only when a cluster is selected
setopt prompt_subst
source "$(brew --prefix)/opt/kube-ps1/share/kube-ps1.sh"
PROMPT='${KUBECONFIG:+$(kube_ps1) }'$PROMPT
```

Create `~/.kube/kubie.yaml` so kubie knows where your cluster files live:

```yaml
shell: zsh

configs:
  include:
    - ~/.kube/clusters/*.yaml
    - ~/.kube/clusters/*.yml
    # repo-managed kubeconfigs, e.g.:
    # - ~/projects/webgrip/homelab-cluster/kubeconfig
  exclude:
    - ~/.kube/kubie.yaml

prompt:
  disable: true # kube-ps1 already shows the context; avoid a double prompt

behavior:
  validate_namespaces: true
  print_context_in_exec: auto
```

Open a new terminal to load it all.

## Adding a cluster

1. Get the cluster's kubeconfig (from the platform team, cloud console, `talosctl kubeconfig`, ...).
2. Save it as one file, named after its VPN/environment, and lock down permissions:

   ```sh
   mv ~/Downloads/kubeconfig.yaml ~/.kube/clusters/acme-prod.yaml
   chmod 600 ~/.kube/clusters/acme-prod.yaml
   ```

3. Rename the context inside it to match:

   ```sh
   kubectl --kubeconfig ~/.kube/clusters/acme-prod.yaml config get-contexts   # see current name
   kubectl --kubeconfig ~/.kube/clusters/acme-prod.yaml config rename-context <old-name> acme-prod
   ```

kubie picks it up automatically — no restart needed.

**Never commit a kubeconfig to git.** The one exception is a cluster repo that manages its own gitignored kubeconfig (like the homelab repo) — check `.gitignore` covers it before you put it there, and add that path to `kubie.yaml`'s `include` list.

## Daily use

Two ways to select a cluster; both make your prompt show `(⎈|<context>:<namespace>)` so you always see where commands will land.

**Working in a cluster repo?** Just `cd` into it. If the repo has a `.mise.toml` with a `KUBECONFIG` entry (the homelab repo does), mise selects the right cluster for you while you're inside that directory:

```toml
# .mise.toml at the repo root
[env]
KUBECONFIG = "{{config_root}}/kubeconfig"
```

**Ad-hoc work?** Use kubie:

```sh
kubie ctx                # pick a cluster from a fuzzy-search list
kubie ctx acme-prod      # or jump straight to one
exit                     # leave the sub-shell; cluster selection gone
```

The selection only exists inside that sub-shell, so two terminal tabs can safely point at two different clusters. For one-off commands without a sub-shell: `kubie exec acme-prod default kubectl get nodes`.

And remember: **connect to the matching VPN first.**

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `kubectl` hangs ~30s, then `i/o timeout` | Wrong VPN (or no VPN) for the selected context. Check your prompt, check your VPN. |
| No context in prompt / `kubectl` says no configuration | Nothing selected — `cd` into the cluster repo or start `kubie ctx`. That's rule 2 working as intended. |
| TLS errors or timeouts on a cluster that worked earlier | Two VPNs with overlapping IP ranges — a second VPN can push a route (e.g. `10.0.0.0/8`) that swallows the first cluster's traffic. Disconnect the other VPN and retry. |
| Duplicate contexts like `admin@kubernetes-1` | A tool (e.g. `talosctl kubeconfig`) *merged* into an existing file instead of replacing it. Delete the extras with `kubectl config delete-context` / `delete-user`. |

Tip: for interactive commands, `--request-timeout=5s` turns a silent 30-second hang into a fast, obvious failure.
