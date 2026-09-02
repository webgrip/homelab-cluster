---
status: accepted
date: 2026-09-02
---

# Off-LAN git-SSH rides the Cloudflare Tunnel, on SSH key auth alone

Technical Story: owner request (2026-08-31) — "I want to be able to push to Forgejo over SSH
without being on my VPN". Extends the exposure posture set by
[ADR-0021](adr-0021-lan-only-exposure.md) (LAN-only for services that don't need the internet)
and [ADR-0011](adr-0011-flux-source-forgejo.md) (Forgejo is the Flux source of truth).

## Context and Problem Statement

Forgejo has two front doors. The web UI is public at `forgejo.${SECRET_DOMAIN}` through the
Cloudflare Tunnel → `envoy-external`. Git-over-SSH was **LAN-only**: the chart's `service.ssh` is
a Cilium LoadBalancer on `10.0.0.11:22`, named by a `coredns.io/hostname` annotation that only
k8s-gateway (`10.0.0.26`, authoritative for the zone on the LAN) answers. `dig
forgejo-ssh.${SECRET_DOMAIN} @1.1.1.1` returned nothing.

So every push from outside the house required dialling the WireGuard VPN on the OPNsense router
first. That is friction on the single most frequent operation in this estate — this repo is
pushed to `main` many times a day — and it bites precisely when the network is least convenient
(tethering, someone else's Wi-Fi, a captive portal that drops UDP/51820 outright).

The cluster has exactly one public door: the Cloudflare Tunnel, whose config carried a single
wildcard rule (`*.${SECRET_DOMAIN}` → `envoy-external:443`) and had never carried anything but
HTTP. There are no WAN port-forwards, and the tunnel is what keeps the home IP address off
public DNS in the first place.

The constraint that shaped the answer: **git remotes and Forgejo's own rendered clone URLs must
not change.** Forgejo renders `SSH_DOMAIN: forgejo-ssh.${SECRET_DOMAIN}` into every clone
button, this repo's `origin` is `ssh://git@forgejo-ssh.${SECRET_DOMAIN}/webgrip/homelab-cluster.git`,
and the `forgejo-leading` cutover procedure hard-codes that hostname. A second hostname for
"the off-LAN one" would fork all of that and rot.

## Decision Drivers

* **No inbound firewall hole.** The home IP stays off public DNS; nothing new listens on the WAN.
* **One hostname, one host key, unchanged remotes** — LAN and off-LAN differ only in transport.
* **The LAN path must not regress.** Pushing from the couch must not hairpin through Cloudflare's
  edge and back, and must not acquire a dependency on the internet being up.
* **No second thing that can break a push.** A push failing at 23:00 because a browser session
  expired is a worse outcome, on this estate, than the marginal risk it would have bought.
* **Manifest-managed.** Router NAT rules and dashboard-only config are outside this repo, and
  therefore outside review, diff, and rollback.

## Considered Options

* A `ssh://` ingress rule on the existing Cloudflare Tunnel + `cloudflared access ssh` on clients
* The same, with a Cloudflare Access application gating the hostname
* An OPNsense WAN port-forward to `10.0.0.11:22`
* Switch remotes to git-over-HTTPS on the already-public `forgejo.${SECRET_DOMAIN}`
* A Tailscale subnet router advertising `10.0.0.0/24`

## Decision Outcome

Chosen option: "A `ssh://` ingress rule on the existing Cloudflare Tunnel + `cloudflared access
ssh` on clients", because it is the only option that reaches the *existing* SSH endpoint under
its *existing* name without opening a WAN port — the tunnel is already running, already
authenticated to Cloudflare, and already the thing hiding the home IP, so off-LAN git-SSH costs
one ingress rule and one DNS record rather than a new exposure surface.

Concretely:

* `kubernetes/apps/network/cloudflare-tunnel/app/helmrelease.yaml` gains a first ingress rule,
  `forgejo-ssh.${SECRET_DOMAIN}` → `ssh://forgejo-ssh.forgejo.svc.cluster.local:22`. It **must**
  sit above the wildcard: cloudflared matches rules in order, and `*.${SECRET_DOMAIN}` would
  otherwise swallow this hostname and hand an SSH byte stream to Envoy as if it were HTTPS.
* `dnsendpoint.yaml` gains a proxied CNAME for the same name to the tunnel, alongside the
  `external.${SECRET_DOMAIN}` record, so the tunnel UUID stays written down once.
* Clients off-LAN set `ProxyCommand cloudflared access ssh --hostname %h`, and a preceding
  `Match … exec` clause pins `ProxyCommand none` when the name **resolves to** `10.0.0.11` —
  so on the LAN and on the VPN nothing changes at all. The condition is resolution, not
  reachability; see the 2026-09-02 entry under More Information for why that distinction is
  load-bearing rather than pedantic.

Split-horizon does the rest for free: k8s-gateway stays authoritative for the zone on the LAN
and keeps answering `10.0.0.11`, so only off-LAN resolvers ever see the tunnel record.

No NetworkPolicy change was needed — `forgejo-allow-ingress` already admits the `network`
namespace (where cloudflared runs) on all ports, for the gateway's sake.

**The authentication barrier is Forgejo's own sshd, and deliberately nothing else** (owner
decision, 2026-08-31). A Cloudflare Access application in front of the hostname was designed and
then declined: it would add a browser session that expires mid-push, a service token to rotate
for headless clients, and a dashboard object this repo cannot diff or roll back — to sit in front
of a daemon that already accepts publickey auth only, for a single forced-command `git` user.
That is the same posture GitHub, Codeberg and every public forge run their SSH endpoint on. The
honest consequence, recorded rather than buried: `forgejo-ssh.${SECRET_DOMAIN}` is now an
internet-reachable SSH endpoint, and the SSH key is the whole gate.

### Positive Consequences

* Push from anywhere, over the same remotes, with the same key and the same `known_hosts` entry.
* Nothing new listens on the WAN; the home IP stays out of public DNS.
* Works where WireGuard does not — captive portals and networks that drop UDP still pass 443.
* No login flow, no token, no session expiry: the off-LAN path has exactly one moving part more
  than the LAN one, and it is a `ProxyCommand`.
* Reversible in one commit: delete the ingress rule and the DNS record and the name goes back to
  being LAN-only.

### Negative Consequences

* **A git SSH daemon is now on the public internet**, defended by publickey-only auth. The
  practical follow-through is key hygiene: every key in a Forgejo account is now a key that works
  from anywhere, so revoking a lost one is urgent in a way it was not when the LAN was the moat.
* **`cloudflared` becomes a client dependency** on every off-LAN machine (`brew install
  cloudflared`). A machine without it, off-LAN, fails at `ProxyCommand` — not with a helpful
  error.
* Off-LAN pushes now depend on Cloudflare's edge; a Cloudflare incident means falling back to the
  VPN, which remains configured and remains the break-glass path.
* Off-LAN throughput is bounded by the tunnel rather than the LAN — irrelevant for commits,
  noticeable for a first clone of a large repo or an LFS-heavy fetch.
* The tunnel now carries non-HTTP traffic, so its config has an ordering constraint a future edit
  can silently break. The rule is commented in place for exactly that reason.
* SSH brute-force noise now reaches the pod. Forgejo refuses password auth outright, so this is
  log volume rather than risk — but it is log volume that did not exist before.

## Pros and Cons of the Options

### A `ssh://` ingress rule on the existing Cloudflare Tunnel + `cloudflared access ssh`

* Good, because it reuses the one public door that already exists — no new exposure surface.
* Good, because the hostname, host key, and every git remote stay exactly as they are.
* Good, because it is entirely manifest-managed: two files, one commit, one revert.
* Bad, because clients need `cloudflared` installed.
* Bad, because it puts a git SSH daemon on the public internet with key auth as the only gate.

### The same, with a Cloudflare Access application gating the hostname

* Good, because an identity check would sit in front of the SSH handshake, and be revocable in
  one click without touching the cluster.
* Good, because it would keep the endpoint invisible to internet-wide scanning.
* Bad, because interactive sessions expire and re-prompt in a browser — mid-push, on the machine
  least likely to have one handy.
* Bad, because headless clients need a service token, i.e. a second long-lived credential to
  store and rotate, sitting in front of the key that was already sufficient.
* Bad, because the policy is a dashboard object: invisible to this repo, absent from review, and
  not restorable by `git revert` — the ADR would assert a control nothing in CI could verify.

### An OPNsense WAN port-forward to `10.0.0.11:22`

* Good, because no client software at all, and native LAN-speed transfers.
* Good, because it works from machines you cannot install tooling on.
* Bad, because it publishes the home IP address, undoing what the tunnel is for, and needs DDNS
  to survive a WAN IP change.
* Bad, because the NAT rule lives in the router, outside this repo — no diff, no review, no
  rollback, and invisible to anyone reading the manifests.

### Switch remotes to git-over-HTTPS on `forgejo.${SECRET_DOMAIN}`

* Good, because it needs no new infrastructure whatsoever — that endpoint is already public.
* Bad, because it is not SSH: it trades the existing key for a token in a credential helper.
* Bad, because Cloudflare's free plan caps request bodies at ~100 MB, so a large push fails —
  the same cap that put Harbor on `envoy-internal` in [ADR-0021](adr-0021-lan-only-exposure.md).
* Bad, because it forks every remote URL, the `forgejo-leading` procedure, and Forgejo's own
  rendered clone URLs away from the SSH ones.

### A Tailscale subnet router advertising `10.0.0.0/24`

* Good, because it would fix off-LAN access to *everything* LAN-only at once — Harbor, the MCP
  endpoints, `kubectl` against the API VIP — not just git.
* Good, because it is always-on and effectively invisible, unlike hand-dialled WireGuard.
* Bad, because it is still a VPN, which is the thing being removed from the loop.
* Bad, because it adds a second overlay and a second identity plane next to the WireGuard one
  already on the router, for a problem one ingress rule solves.

## Confirmation

Flux reporting the Kustomization green is **not** the confirmation — it proves the manifest
rendered, not that a byte of SSH crossed the tunnel. All four must hold:

1. `dig forgejo-ssh.${SECRET_DOMAIN} @1.1.1.1` answers Cloudflare proxy addresses, while
   `@10.0.0.26` still answers `10.0.0.11` — split-horizon intact.
2. `ssh -T -o ProxyCommand="cloudflared access ssh --hostname %h" git@forgejo-ssh.${SECRET_DOMAIN}`
   returns Forgejo's greeting. Forcing the `ProxyCommand` exercises the tunnel path even from the
   LAN, so this is testable without leaving the house.
3. The LAN path is still direct: with the `Match … exec` clause in place, `ssh -v` on the LAN
   shows no `cloudflared` invocation. Check the *off*-LAN direction too, and specifically from a
   network in `10.0.0.0/24` — `ssh -G … | grep proxycommand` must show `cloudflared` there.
4. A real `git push` over the tunnel path succeeds — the greeting proves auth, not that git's
   pack protocol survives the proxy.

## More Information

* 2026-08-31 — proposed; tunnel ingress rule + public CNAME committed.
* 2026-08-31 — **accepted**; all four Confirmation checks passed against live state.
  `@1.1.1.1` answers the tunnel CNAME while `@10.0.0.26` still answers `10.0.0.11`;
  `ssh -T` through the tunnel returned Forgejo's greeting for `ryangr0`; the LAN path takes
  no `ProxyCommand`; and this very commit was pushed over the tunnel path.

  Worth writing down, because it will bite the next person who tries to test this from home:
  **the tunnel path is not directly testable from the LAN.** `cloudflared access ssh` resolves
  the hostname with the system resolver, which on the LAN is k8s-gateway — so it dials
  `10.0.0.11:443` (the LoadBalancer, which does not serve TLS) and fails with `network is
  unreachable`. That failure is split-horizon working correctly, not a broken tunnel. To
  exercise the real path from inside the house, give cloudflared a public resolver:

  ```bash
  docker run -d --rm --name cf-ssh-test --dns 1.1.1.1 -p 12222:2222 \
    docker.io/cloudflare/cloudflared:2026.7.3 \
    access tcp --hostname forgejo-ssh.${SECRET_DOMAIN} --url 0.0.0.0:2222
  ssh -T -p 12222 -o HostKeyAlias=forgejo-ssh.${SECRET_DOMAIN} git@127.0.0.1
  ```

  `HostKeyAlias` is the part that makes this a real test rather than a reachable-port check:
  it validates the far end against the existing `known_hosts` entry, so a pass proves it is
  the same sshd with the same host key, reached over the tunnel.

* 2026-09-02 — **amended**: the client-side switch was wrong, and the tunnel itself was fine.
  A `git clone` from a café network failed with `ssh: connect to host forgejo-ssh.<domain> port
  22: Operation timed out` after 75s. Cause: the original `Match … exec` probed *reachability*
  (`nc -z 10.0.0.11 22`), and that network was itself a `10.0.0.0/24` — an unrelated host
  answered on `10.0.0.11:22`, the probe concluded "on LAN", `ProxyCommand none` was pinned, and
  ssh dialled the public name on port 22, where Cloudflare serves no SSH.

  The probe now tests **resolution** instead: `dig +short %h | grep -qx 10.0.0.11`. The direct
  path is correct exactly when the name resolves to the LoadBalancer, and an RFC1918 collision
  cannot change DNS. A `ConnectTimeout 15` was added so a future wrong decision fails in seconds
  rather than 75. Verified from the colliding network: `ssh -G` selects `cloudflared`, `ssh -T`
  returns Forgejo's greeting, and `git clone` of an empty repo completes in 0.83s.

  Nothing was exposed by the bug: `ProxyCommand none` does not rewrite `HostName`, so the
  foreign host received only a bare TCP connect from `nc` and was never offered a key. The
  generalisable lesson, and the reason this is recorded rather than quietly fixed: *"can I reach
  that address"* is not the same question as *"is that address the host I mean"*, and a probe
  that conflates them fails **open**, in the one situation it exists to handle.
