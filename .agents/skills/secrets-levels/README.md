# secrets-levels

Which of six levels a secret lives at in the Webgrip estate, and the manifest that puts it
there: floor (SOPS), vault (OpenBao), cluster (External Secrets), bridge (Forgejo Actions and
Cloudflare Worker secrets), short-lived (OIDC, dynamic credentials, per-run tokens), person (a
laptop). Decision by origin first (entropy, provided, mintable, floor), then by consumer.

The model is
[homelab-cluster ADR-0055](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/docs/techdocs/docs/adr/adr-0055-one-secrets-model-six-levels.md);
the per-level runbooks live beside it. This skill is the placement half; `guard-secrets` is
the enforcement half (the hook that keeps plaintext out of files).

**Install:**

```text
/plugin install secrets-levels@ai-skills
```

or `npx skills add https://forgejo.webgrip.dev/webgrip/ai-skills.git -s secrets-levels`.
