# Handoff → `webgrip/workflows`: push images to Harbor from a Forgejo runner

Paste the block below into a Claude Code session in `webgrip/workflows`. Harbor-side coordinates and
the runbook live in `webgrip/homelab-cluster`
([Runbook: Harbor](../runbooks/harbor.md#using-harbor-day-to-day-the-happy-path),
[ADR-0005](../adr/adr-0005-lan-only-exposure.md)).

---

**Mission:** Make the Forgejo build-and-push workflow(s) publish webgrip's images to the in-cluster
Harbor (`harbor.webgrip.dev`), running on an **in-cluster Forgejo runner** (the only runner that can
reach LAN-only Harbor).

**Context:** Harbor is a private OCI registry in `webgrip/homelab-cluster`, **LAN-only** at
`harbor.webgrip.dev`, with a private `webgrip` project and push robot `robot$webgrip+ci`. The image
build logic lives in `webgrip/infrastructure` (companion handoff); the **Forgejo Actions workflows
live here**. GitHub-hosted runners **cannot** reach Harbor; the in-cluster Forgejo runner can (it
resolves `harbor.webgrip.dev` via split-DNS → `envoy-internal` `10.0.0.27`, with a valid TLS cert).

**Tasks:**

1. **Identify** the workflow(s) that build/push images.
2. **Pin the Harbor push to the in-cluster Forgejo runner** (the `runs-on` label targeting the
   self-hosted in-cluster runner) — not a GitHub-hosted/cloud runner.
3. **Add a Harbor login + push step** (keep the existing ghcr push too — dual-publish during
   migration):

   ```bash
   docker login harbor.webgrip.dev -u "${{ secrets.HARBOR_ROBOT_USER }}" -p "${{ secrets.HARBOR_ROBOT_TOKEN }}"
   docker push harbor.webgrip.dev/webgrip/<image>:<tag>
   ```

4. **Secrets:** add Forgejo secrets at org/repo level — `HARBOR_ROBOT_USER` = `robot$webgrip+ci`,
   and `HARBOR_ROBOT_TOKEN` = the robot token provisioned on the Harbor side and vaulted in OpenBao
   `secret/harbor/robot-webgrip` (key `CI_TOKEN`). Get it from Ryan/OpenBao, or use any existing
   OpenBao → Forgejo secret-sync.
5. **Verify** with a test build run.

**Constraints / gotchas:**

- **Must run on the in-cluster runner** — confirm it resolves `harbor.webgrip.dev` and TLS validates
  (no `--insecure`).
- The robot username has a literal `$` (`robot$webgrip+ci`) — quote it in YAML and shell so it isn't
  treated as a variable.
- **Mask the token** — never `echo` it; pass via the secret only.
- **Don't drop the ghcr push yet** — dual-publish until Harbor is proven and cluster workloads
  consume from it.

**Acceptance:** a workflow run shows a successful `docker login` + `docker push` to
`harbor.webgrip.dev/webgrip/<image>`, and the image is visible in the Harbor `webgrip` project.
