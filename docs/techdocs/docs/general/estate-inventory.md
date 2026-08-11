# Cluster inventory (generated at build)

These tables are rendered by [`main.py`](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/docs/techdocs/main.py)
(mkdocs-macros) from the GitOps tree at build time — they state what the repo
*declares*, deterministically, on every docs publish. No cluster API calls.

## Flux Kustomizations

{{ app_inventory() }}

## HelmReleases

{{ helmrelease_inventory() }}
