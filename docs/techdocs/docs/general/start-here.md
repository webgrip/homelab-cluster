# Start here

Your first day on the webgrip platform, in order. Each step says what you do, what you should
see, and who to ask when you don't. If you are the person adding someone, read the
[joiner runbook](../runbooks/access-model.md#joiner) instead; it is the other half of this page.

## What you are joining

One Kubernetes cluster on six small machines, run entirely from Git. Nobody changes the cluster
by hand: a change is a commit to `webgrip/homelab-cluster`, and [Flux](https://fluxcd.io) applies
it. Every application signs you in through one front door, Authentik, which in turn asks Google.

Three words you will meet everywhere:

| Word | Meaning here |
| --- | --- |
| Roster | `people.yaml` in the access-plane model. If you are not in it, no application lets you in, even after Google says yes. |
| Role | The bundle of rights the roster gives you: `developer`, `platform-engineer` or `client`. |
| Project | What your rights apply to: namespaces in the cluster, repositories, registry projects. |

## Before day one

These happen on someone else's side. Check them with whoever added you.

- [ ] You have a Google Workspace account on `webgrip.nl` with 2-step verification on. Every
      login in the estate is that account; there are no other passwords.
- [ ] Your entry in `people.yaml` is merged and the access plane has applied it. The admin
      checks with `kubectl -n security get terraform access-broker` (Ready, no pending plan).
- [ ] You have a way onto the network. Most applications are reachable only from the home LAN
      (`10.0.0.0/24`) or over the WireGuard VPN that ends on the router. For the VPN, see
      [step 0](#0-the-vpn-if-you-work-away-from-the-lan).

## 0. The VPN, if you work away from the LAN

Your VPN access is a line in the roster, like everything else. Each device gets its own key pair,
and the private key never leaves the device.

1. Install WireGuard ([wireguard.com/install](https://www.wireguard.com/install/)) and make a key
   pair on the device:

   ```sh
   umask 077
   wg genkey | tee ~/.config/wg-webgrip.key | wg pubkey
   ```

   On a phone or in the desktop app, **Add empty tunnel** shows the same public key.
2. Send the **public** key (the one line that command printed) to the person who added you, with
   a short device name such as `laptop`. They add it under your entry in `people.yaml`:

   ```yaml
       wireguard:
         - device: laptop
           public_key: <your public key>
   ```

3. Within fifteen minutes of that merge the router knows your device. They send you the tunnel
   settings: your address, the router's public key and endpoint, and which networks route
   through it. Paste them into your tunnel and put your private key in `PrivateKey`.

A new device is a new line, a lost device is deleting its line, and leaving removes them all.

## 1. Sign in once

Open [authentik.webgrip.dev](https://authentik.webgrip.dev) and choose **Sign in with Google**.
There is no username field and no sign-up link; that is deliberate
([ADR-0057](../adr/adr-0057-google-only-login-closed-enrolment.md)).

| You see | It means |
| --- | --- |
| Your Authentik dashboard with application tiles | You are in. The tiles are exactly the applications below. |
| Google succeeds, then Authentik refuses you | You are not in the roster yet, or the email differs by a character. Ask the person who added you. |
| The page does not load at all | You are off the LAN and the VPN is down. |

A sign-in lasts twelve hours. Being asked again every morning is normal
([ADR-0077](../adr/adr-0077-admins-prove-a-security-key-at-google-and-sessions-end-in-twelve-hours.md)).

## 2. What you can open

Computed from the access-plane model when these docs are built, so it is always what the roster
actually grants. Your role is on the [access matrix](access-matrix.md).

{{ launchpad() }}

An application you open for the first time creates your account there on the spot. Forgejo puts
you in the `Developers` team (write on every repository) at that first sign-in, and re-checks it
every time you sign in.

## 3. Forgejo and your SSH key

1. Open [forgejo.webgrip.dev](https://forgejo.webgrip.dev) and sign in with Authentik.
2. Add your SSH public key under **Settings → SSH / GPG keys**. That key is the only thing that
   gates `git push`, from anywhere; remove keys you stop using.
3. Off the LAN without the VPN, follow
   [pushing from off the LAN](forgejo.md#pushing-from-off-the-lan-without-the-vpn) once.
4. Clone the platform repository:

   ```sh
   git clone ssh://git@forgejo-ssh.webgrip.dev/webgrip/homelab-cluster.git ~/projects/webgrip/homelab-cluster
   ```

`main` is protected. You push a branch and open a pull request; CI must be green before it
merges. The owner pushes to `main` directly, which is why you will see commits there without a
pull request.

## 4. Your tools

Every tool the repository needs is pinned in `.mise.toml` and installed by
[mise](https://mise.jdx.dev). Docker must be running for the manifest validator.

```sh
curl https://mise.run | sh
echo 'eval "$(~/.local/bin/mise activate zsh)"' >> ~/.zshrc && exec zsh
cd ~/projects/webgrip/homelab-cluster
mise trust && mise install
```

You do **not** need `age.key`, a talosconfig or the admin kubeconfig. Those are the owner's
break-glass material; [new-machine setup](../runbooks/new-machine-setup.md) is the owner's page,
not yours.

## 5. kubectl as yourself

The Kubernetes API checks your Google account directly and knows you as `oidc:you@webgrip.nl`.
One command sets it up, including the cluster address and certificate:

```sh
cd ~/projects/webgrip/homelab-cluster
export BAO_ADDR=https://openbao.webgrip.dev
mise exec -- bao login -method=oidc
KUBERNETES_OIDC_CLIENT_SECRET="$(mise exec -- bao kv get -field=client_secret secret/security/kubernetes-oidc)" \
  mise exec -- ./scripts/kube-oidc-setup.sh
mise exec -- kubectl auth whoami
mise exec -- kubectl auth can-i --list -n erfbeeld
```

A browser opens twice: once for OpenBao, once for Google. The OpenBao login lets you read that
one sign-in value and nothing else. What each tier can do, and what to do when it refuses, is
on [Kubernetes login](../runbooks/kubernetes-login.md).

## 6. Before your first change

Read these four, in this order. They are short and they are the rules CI enforces.

1. [`AGENTS.md`](https://forgejo.webgrip.dev/webgrip/homelab-cluster/src/branch/main/AGENTS.md):
   the working rules. GitOps only, secrets through OpenBao, **no comments in code**.
2. [Adding applications](adding-applications.md): how an app is laid out, three layers deep.
3. [Secrets](../runbooks/external-secrets.md): a secret is never a file in Git.
4. Validate before you push:

   ```sh
   ./scripts/run-flux-local-test.sh
   ```

## 7. Where the work is

The roadmap is a board in [Vikunja](https://vikunja.webgrip.dev), not a file in this repository
([ADR-0043](../adr/adr-0043-vikunja-roadmap-system-of-record.md)). `do-next` is the top of the
stack, `ready` means a ticket can be started as written, `needs-refinement` means ask first.
Commit messages carry the ticket as a `VIK-<id>` trailer.

Your first sign-in puts you in the `Webgrip` team, which has Homelab Roadmap, Erfbeeld, Vellum,
CI/CD and Unfold shared with it, read and write. A board missing from that list is not shared
with the team; ask.

## When something is wrong

| Symptom | Where to look |
| --- | --- |
| An application refuses you after a good sign-in | Your role does not include it. The table above is the truth; ask for a role change or a dated grant. |
| `Forbidden` from kubectl | Your projects do not own that namespace. [Kubernetes login](../runbooks/kubernetes-login.md). |
| `git push` refused on `main` | Expected. Push a branch and open a pull request. |
| Pull request red on `flux-local` | Run `./scripts/run-flux-local-test.sh` locally; it is the same check. |
| Anything else | [Runbooks](../runbooks/index.md), then the owner. |

## Leaving

Your entry is deleted from the roster. On the next reconcile every account, group and binding
goes with it, and open sessions run out on their own within twelve hours. Nothing for you to do.
