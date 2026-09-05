# Runbook: Secrets level 5 — a person

**Status:** active · **Scope:** a value a person needs in a shell on their own machine ·
**Model:** [ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) · **Vault access:**
[L1](secrets-level-1-vault.md)

> A laptop never holds an original. It holds a session export read from the vault, and at most
> a Keychain cache that knows which vault path it mirrors. Rotation happens at L1; the cache is
> refreshed, never edited by hand into something the vault does not know.

## Read a value for this shell

From a checkout of this repository, on LAN or VPN (OpenBao is published on `envoy-internal`):

```bash
mise exec -- just bao-login
eval "$(mise exec -- just secret-env <provider>/<purpose>)"
```

`secret-env` prints one `export KEY=value` line per key at `secret/<provider>/<purpose>`, quoted
for the shell, and nothing else on stdout; the login prompt goes to stderr so the `eval` stays
clean. Check without printing the value:

```bash
[ -n "$<KEY>" ] && echo "<KEY> is set"
```

The export lives in this shell and dies with it. That is the whole point.

## Cache a value off-VPN

When a tool needs the value where the vault is unreachable, the Keychain is allowed as a cache.
The item name is the vault path with the slash turned into a dash, so the copy names its source:

```bash
eval "$(mise exec -- just secret-env <provider>/<purpose>)"
printf '%s' "$<KEY>" | security add-generic-password -U -a "$USER" -s <provider>-<purpose> -w /dev/stdin
```

Then in `~/.zshrc`, beside the line that does the same for Vikunja:

```bash
export <KEY>="$(security find-generic-password -s <provider>-<purpose> -w 2>/dev/null)"
```

After a rotation at L1, run the two commands above again. A cache that is not refreshed is a
value that stopped working, which is the correct failure: it is the vault's copy that the
bridge validated, and the laptop's copy that did not.

## Personal identity tokens

A Vikunja API token, a personal Forgejo PAT, an SSH key: these identify you, not the estate,
and have no vault original. They live in the Keychain under their own name and follow whatever
rotation the issuing system enforces. They never appear in a repo, a workflow or a shared
document.

## What a person does that nothing else may

- Seed a provided value into the vault ([L1](secrets-level-1-vault.md)). An agent writes the
  manifests and hands over the `bao kv put` line; the person runs it.
- Force an ESO re-sync or run a bridge job out of schedule. Hooks block agents from those
  imperative commands by design.
- Generate root on the vault, once, for an engine mount. Break-glass, audited, then revoked.

## Verify

- `mise exec -- bao token lookup` succeeds after `just bao-login` and shows `policies: [admins default]`.
- `env | grep -c '^<KEY>='` is 1 after the `eval`, 0 in a fresh shell.
- `security find-generic-password -s <provider>-<purpose>` finds the cache item by the name
  that matches its vault path.

## Gotchas

- `bao` talks to localhost until `BAO_ADDR` is exported; `secret-env` sets it for its own run,
  but a hand-typed `bao kv get` afterwards needs `export BAO_ADDR="$(mise exec -- just bao-addr)"`.
- `security add-generic-password ... -w <value>` on the command line lands the value in shell
  history; `-w /dev/stdin` with `printf` does not, and `-w` as the last option with no value
  prompts interactively.
- A `.env` file is a laptop original with no source. Do not create one; if a tool insists, feed
  it from the shell export instead.

## See also

- [L1 vault](secrets-level-1-vault.md) — where the value came from and who may write it.
- `secrets-levels` skill in `webgrip/ai-skills` — what an agent does instead of asking you to paste a value.
