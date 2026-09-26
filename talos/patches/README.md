# Talos Patching

Strategic-merge patches passed to `talosctl gen config` by `scripts/talos-genconfig.sh`
(`just talos-generate-config`). The generator and its inputs are described in
[ADR-0062](../../docs/techdocs/docs/adr/adr-0062-talos-configs-from-plain-talosctl.md).

<https://www.talos.dev/latest/talos-guides/configuration/patching/>

## Which patch lands where

`talos/nodes.yaml` is the only place that decides it. Patches apply in this order, and a later
patch wins:

1. `patches.all` — every node (`global/`)
2. `patches.controlplane` / `patches.worker` — by the node's `role` (`controller/`)
3. `nodes[].patches` — that node alone (`worker/<node>.yaml`, and the network documents in
   `talos/nodes/<hostname>.yaml`)

## Substitution

String values may reference keys from `talos/talenv.yaml` as `${name}`, for example
`harbor.${secretDomain}`. They are filled in with yq's `envsubst(nu, ne)`, so a missing or empty
variable fails the render. Keys are never substituted: write `$patch: delete` as-is.
