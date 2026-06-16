# Handoff → `webgrip/infrastructure`: publish images to Harbor

Paste the block below into a Claude Code session in `webgrip/infrastructure`. Context, the
Harbor-side coordinates, and the runbook live in `webgrip/homelab-cluster`
([Runbook: Harbor](../runbooks/harbor.md#using-harbor-day-to-day-the-happy-path),
[RFC](../architecture/rfc-harbor-proxy-cache.md), [ADR-0005](../architecture/adr-0005-lan-only-exposure.md)).

---

**Mission:** Add the in-cluster Harbor registry (`harbor.webgrip.dev`) as a publish target for the
container images this repo builds, alongside the current `ghcr.io/webgrip/*` — so webgrip's own
images are hosted in our private registry.

**Context:** The homelab cluster (`webgrip/homelab-cluster`) runs **Harbor** as a private OCI
registry. It is **LAN-only** — reachable only from inside the cluster/LAN at `harbor.webgrip.dev`
(→ the `envoy-internal` gateway), never from the public internet or GitHub-hosted runners. A private
**`webgrip` project** and a push/pull **robot account** (`robot$webgrip+ci`) are provisioned on the
Harbor side in homelab-cluster (GitOps); the robot token is vaulted in OpenBao at
`secret/harbor/robot-webgrip`. This repo owns the image **build definitions and push logic**; the
actual CI *execution* is orchestrated in `webgrip/workflows` (companion handoff) — coordinate.

**Tasks:**

1. **Inventory** every image this repo builds and where it currently pushes (expected:
   `ghcr.io/webgrip/*`, e.g. `github-runner`, `twitch-exporter`).
2. **Add Harbor coordinates** `harbor.webgrip.dev/webgrip/<image>:<tag>`. Parameterize the registry
   host as a single variable/arg — don't hardcode it in many places. Keep the tagging scheme
   identical across registries.
3. **Dual-push during migration:** tag + push to **both** `ghcr.io/webgrip/*` and
   `harbor.webgrip.dev/webgrip/*`. Do **not** remove the ghcr push until Harbor is proven and the
   cluster consumes from Harbor.
4. **Auth via env, never hardcoded:** the push uses `HARBOR_ROBOT_USER` (`robot$webgrip+ci`) and
   `HARBOR_ROBOT_TOKEN`, supplied by the CI environment (set in `webgrip/workflows`). The robot
   username contains a literal `$` — quote/escape it.
5. **Migration of existing tags** (only if Ryan opts in): one-time
   `skopeo copy --all docker://ghcr.io/webgrip/<image>:<tag> docker://harbor.webgrip.dev/webgrip/<image>:<tag>`
   from a LAN host, or a Harbor *replication pull-rule* from the `ghcr` registry endpoint.

**Constraints / gotchas:**

- **LAN-only** → the Harbor push only works from an **in-cluster runner**. If any build runs on a
  GitHub-hosted runner, the Harbor push step must execute on the Forgejo/in-cluster runner (that part
  lives in `webgrip/workflows`).
- Harbor has a valid wildcard TLS cert — **no** `--insecure-registry` / `--tls-verify=false`.
- Don't expose Harbor publicly or weaken `envoy-internal`.

**Acceptance:** from a LAN host, `docker pull harbor.webgrip.dev/webgrip/<image>:<tag>` returns the
image; it appears in the Harbor `webgrip` project with a Trivy scan.

**Confirm with Ryan first:** single `webgrip` project vs per-app projects (default: single
`webgrip`); migrate existing tags or new builds only.
