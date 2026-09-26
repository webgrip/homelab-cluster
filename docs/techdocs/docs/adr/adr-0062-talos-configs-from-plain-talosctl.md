---
status: proposed
date: 2026-09-27
---

# Talos machine configs come from plain talosctl gen config, driven by a node inventory

Technical Story: [VIK-1224](https://vikunja.webgrip.dev/tasks/1224) — replace the archived
talhelper config generator (epic [VIK-1223](https://vikunja.webgrip.dev/tasks/1223)).

## Context and Problem Statement

Every machine config for the six nodes came from
[talhelper](https://github.com/budimanjojo/talhelper): `talos/talconfig.yaml` plus
`talos/patches/`, secrets from `talos/talsecret.sops.yaml`, rendered by `talhelper genconfig`
and driven by the `talos` recipes in the root `justfile`. The project was archived on
2026-08-26; v3.1.17 is final. Its README now says: *"This project is now archived and
abandoned. I suggest people who depend on this tool to migrate to other similar tools like topf
or talstomize."*

Talos v1.14.0 (2026-09-03) split the Kubernetes half of the machine config into dedicated
documents (`KubeAPIServerConfig`, `KubeAdmissionControlConfig`, `KubeAuditPolicyConfig`,
`UnattendedInstallConfig` and roughly twenty more). talhelper renders our inputs at
`talosVersion: v1.14.1` into `patch delete: path 'cluster.apiServer.admissionControl' … lookup
failed`, and with that patch removed into `kube-apiserver config is already set in v1alpha1
config`. It will never learn Talos 1.15. Which tool renders the configs from now on?

## Decision Drivers

* Maintained, and able to render the Talos version we are about to run on the day it ships.
* Per-node patches and a per-node installer image, because workers run the kata schematic
  `d1200926…` and control planes the base schematic `1da3394e…`.
* `talos/talsecret.sops.yaml` stays the only secret source; no new SOPS file.
* Reproducible: the same inputs render byte-identical machine configs.
* Pinnable through `mise` and callable from `just`, on Linux and macOS.
* The switch must change nothing on the live nodes.

## Considered Options

* Plain `talosctl gen config` with patches, driven by a node inventory and a small script
* [topf](https://github.com/postfinance/topf)
* [talstomize](https://github.com/mirceanton/talstomize)
* Stay on talhelper and hold the installer at 1.13

## Decision Outcome

Chosen option: "Plain `talosctl gen config` with patches", because the generator is the same
binary that Sidero Labs releases with every Talos version, so no wrapper can fall behind a Talos
release again, and the glue it needs is a single script over tools the repo already pins.

The pieces:

* `talos/nodes.yaml` is the inventory: cluster name, endpoint, additional SANs, installer
  registry, the patch lists for all nodes, control planes and workers, and one entry per node with
  `hostname`, `address`, `role`, `installDisk`, `schematic` and that node's `patches`.
* `talos/nodes/<hostname>.yaml` carries each node's network documents (`HostnameConfig`,
  `LinkAliasConfig`, `LinkConfig`, and `Layer2VIPConfig` on control planes), written out in
  exactly the form talhelper used to generate from `networkInterfaces`.
* `talos/patches/` keeps every existing patch. `patches/global/cluster-network.yaml` is new and
  holds the pod and service subnets and `cni: none`, which were talconfig fields.
  `patches/controller/cluster.yaml` now writes `$patch: delete` rather than talhelper's
  `$$patch` escape.
* `talos/talenv.yaml` keeps `talosVersion`, `kubernetesVersion` and `secretDomain`, and gains
  `configContract: v1.13`, passed to `talosctl gen config --talos-version`.
* `scripts/talos-genconfig.sh` decrypts the secrets bundle with `sops` into a private temporary
  directory that it deletes on exit. It fills `${secretDomain}` into the patches with yq's
  `envsubst(nu, ne)`, which fails on an unset or empty variable. It then runs one
  `talosctl gen config` per node with `--install-image
  <installerRegistry>/<schematic>:<talosVersion>`, and writes a talosconfig whose endpoints
  are the control planes and whose nodes are all six.
* `just talos-generate-config [out]` calls the script. The apply, upgrade, upgrade-k8s, reset
  and bootstrap recipes read `talos/nodes.yaml` and call `talosctl` directly.
  `aqua:budimanjojo/talhelper` is gone from `.mise.toml`.

`configContract` is separate from `talosVersion` on purpose. It pins the shape of the machine
config, meaning which documents `gen config` emits, while `talosVersion` pins the installer
image. At contract v1.14, `gen config` emits the Kubernetes settings as separate documents, and
our v1alpha1 `cluster.apiServer` patches collide with them. The 1.14 behaviour changes also
arrive with that contract: `workloadIsolation`, an emitted `KubeFlannelCNIConfig`, and
`UnattendedInstallConfig` replacing `.machine.install`. Moving the patches onto those documents
is a migration of its own, with its own live diff, so it is kept apart from the generator swap.
Talos keeps accepting the v1alpha1 fields for backwards compatibility.

### Consequences

* Good, because the generator can never lag a Talos release: `talosctl` at version X renders X
  on the day X ships.
* Good, because no third-party code sits between the inputs and the configs, and the only new
  file of logic is one script over `talosctl`, `sops` and `yq`, all already pinned in `.mise.toml`.
* Good, because the inventory holds each node's schematic as data. The recipes build the upgrade
  image from it, so kata versus base cannot drift between the render and `talos-upgrade-node`.
* Good, because the output is byte-identical to talhelper's for all six nodes at v1.13.10. The
  switch changes nothing live.
* Bad, because we now own the glue talhelper used to provide: network documents written by hand
  per node, and the script's patch ordering (all, then role, then node).
* Bad, because every render mints a new talosconfig client certificate. This is inherent to
  `gen config` and talhelper did the same; the file stays untracked.
* Neutral, because `configContract: v1.13` leaves the Talos 1.14 document migration as explicit
  follow-up work instead of hiding it inside a tool change.

### Confirmation

* `just talos-generate-config <dir>` renders all six nodes. For each node, the output normalised
  with `yq -o=json | jq -S` equals talhelper v3.1.17's render of the same inputs. Compare the
  secret fields by digest only.
* `talosctl apply-config --dry-run` of each rendered file against its live node shows no change
  beyond drift that is already there.
* `TALOS_VERSION_OVERRIDE=v1.14.1 mise exec aqua:siderolabs/talos@1.14.1 --
  ./scripts/talos-genconfig.sh <dir>` renders all six nodes, and `talosctl validate --mode metal`
  accepts each one.

## Pros and Cons of the Options

### Plain `talosctl gen config` with patches

* Good, because it is the upstream generator, released and versioned with Talos itself.
* Good, because `--with-secrets` takes the bundle format that `talsecret.sops.yaml` already holds,
  and the output is deterministic.
* Bad, because inventory, per-node flags and substitution are ours to maintain.

### topf

* Good, because it is maintained (v0.6.0 on 2026-09-03, commits weekly) and states Talos 1.14
  multi-document support.
* Good, because it has built-in SOPS, a talhelper migration guide that reuses
  `talsecret.sops.yaml` unchanged, per-node `schematicId`, and an aqua package
  (`postfinance/topf`).
* Bad, because it is a nine-month-old, single-organisation wrapper. It is the same class of
  dependency that just stranded us, and it has to release before each new Talos minor can be
  rendered.
* Bad, because it would reshape our patch layout into its `all/`, `<role>/`, `node/<host>/`
  folders and move substitution to Go templates.

### talstomize

* Good, because its single-file, patch-list model is the closest to talhelper's.
* Bad, because it is still a release candidate (v0.1.0-rc.2, 2026-09-05), about seven weeks old,
  and has no aqua package.
* Bad, because issue #14 is still open: it writes the deprecated `machine.install.image` and
  `machine.network.hostname` next to the 1.14 documents. Issue #15 is also open: `diff` runs
  invalid talosctl commands.
* Bad, because schematics are POSTed to the Image Factory at build time, so rendering needs the
  network.

### Stay on talhelper and hold the installer at 1.13

* Bad, because the owner ruled it out: it keeps an archived tool on the critical path, and Talos
  1.14 still cannot be rendered.

## More Information

* 2026-09-25 — talhelper v3.1.17 fails to render the inputs at `talosVersion: v1.14.1`; repro in
  the VIK-1224 research session.
* 2026-09-27 — proposed. The plain-talosctl render at v1.13.10 is identical to talhelper's for
  all six nodes, and every live dry-run shows only the stale `install.image` tag (v1.13.7 stored
  while v1.13.10 runs), which comes from `talosctl upgrade` not rewriting the stored config.
  All six renders at v1.14.1 validate for metal. The one warning is the `.machine.files`
  deprecation.
* Related: [ADR-0024](adr-0024-registry-mirror-talos-spegel.md) (the `${secretDomain}`-templated
  registry mirror patches this generator substitutes).
