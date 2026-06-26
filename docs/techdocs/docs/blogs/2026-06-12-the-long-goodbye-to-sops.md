# The Long Goodbye to SOPS

### How a homelab taught its secrets to manage themselves — a migration from age‑encrypted files to External Secrets and OpenBao

*Published 2026‑06‑12*

---

## Prologue: the ritual

Every secret in this cluster used to begin its life with a small, tedious ceremony.

You generated a value. You opened the right `*.sops.yaml` file. You ran `sops --encrypt --in-place`. You committed the ciphertext. You uncommented the reference in a kustomization. You waited for Flux to reconcile. And if you fat‑fingered the YAML anchor, or forgot that the secret was wired from a *sibling* directory's kustomization rather than the app's own, you did it again.

For a single password, the ritual is harmless. Multiply it by forty‑seven encrypted files across two dozen applications and it becomes a tax — one paid not in money but in attention, levied every time the platform grows. Worse, it puts a human squarely in the critical path of the most error‑prone, highest‑consequence operation in the whole system: handling secrets. The toil was sharpest for two classes of secret that no human should ever have touched in the first place:

- **Random/internal entropy** — session keys, signing secrets, registration tokens. Pure noise. There is no reason a person should generate, see, or copy these. Yet there they were, hand‑rolled and hand‑encrypted.
- **OIDC client secrets** — minted by Authentik, then hand‑carried into a SOPS file so the consuming app could read them. A copy‑paste of a credential, by a human, on every new integration.

This is the story of removing the human from that loop. Not all the way — there is an irreducible floor of secrets that must exist before anything else can, and pretending otherwise is how you build a system that can't boot itself. But everywhere above that floor, the goal was simple and slightly utopian: **a secret you never have to encrypt, because you never have to touch it.**

---

## The shape of the answer

The engine is the [External Secrets Operator](https://external-secrets.io/) (ESO). The mental model that makes everything else click is this:

> **ESO writes real, cached Kubernetes Secrets.** Once written, pods read them like any other Secret — with no runtime dependency on ESO or the backend behind it.

That single property is what makes the architecture safe. A backend outage blocks *creating* or *rotating* a secret; it never blocks a running pod from *reading* one, because the pod is reading a perfectly ordinary `Secret` object that ESO already materialised into etcd. The vault can fall over at 3am and your applications keep serving traffic, blissfully unaware. We would lean on that guarantee more than once.

On top of ESO, secrets sort into two lanes:

1. **Random/internal** → an ESO `Password` `ClusterGenerator` named `password-generator`. No backend at all. ESO mints the entropy directly, writes the Secret, and with `refreshInterval: "0"` never touches it again. This is the lane that finally killed the "human generates noise" anti‑pattern.
2. **External / stateful / provider** → a real secrets store. Values that already exist (a Cloudflare token, a GitHub App key, a database password) live in a vault and are pulled by an `ExternalSecret`.

For lane two we needed a vault.

---

## Choosing a vault: OpenBao

For lane two we chose **[OpenBao](https://openbao.org/)** — the OSS, MPL‑2.0 fork of Vault. In a homelab whose entire identity story is "everything logs in through Authentik," the deciding factor was that OpenBao speaks **OIDC login for free**, with no commercial license required to be a first‑class citizen of an SSO‑centric cluster. It runs as a single‑node raft instance — no external database, no extra moving parts.

ESO authenticates to OpenBao through the **Kubernetes auth method**, using its own ServiceAccount. There are no static vault credentials sitting in a SOPS file bootstrapping the thing that's supposed to replace SOPS files. The chicken‑and‑egg problem that haunts every secrets migration is solved by Kubernetes itself vouching for ESO's identity.

---

## No gods, no root tokens

Here is the design constraint that shaped the most interesting code in the whole project: **there is no live root token, and no human ever runs a `bao` command.**

That is a strong statement for a Vault‑family system, where the root token is normally the keys to the kingdom and lives in someone's password manager forever. We wanted it gone. The bootstrap is therefore entirely GitOps, expressed as two CronJobs in `openbao/bootstrap/`:

- **`openbao-init`** runs every five minutes and is idempotent. On a *fresh* instance it initialises OpenBao, unseals it, performs a one‑time root‑only setup (enable the KV v2 mount at `secret/`, enable Kubernetes auth, configure OIDC, and create a tightly scoped `config-admin` policy and role), and then does the thing that makes the whole design honest: **`bao token revoke -self`.** The root token is generated, used exactly once, and destroyed. The only thing persisted is the unseal key, stored as the `openbao-keys` Secret. Not the root token. Just enough to unseal.
- **`openbao-config`** runs as that scoped `config-admin` role — authenticating *through Kubernetes auth, with no root* — and reconciles the policies, the per‑namespace roles, the identity mappings, and the OIDC configuration on every pass. It is the steady‑state janitor that keeps OpenBao's own configuration as code.

If you ever need emergency root again, you regenerate it from the unseal key with `bao operator generate-root` — a deliberate, audited, break‑glass act, not an ambient standing power. The blast radius of a leaked credential is dramatically smaller when the most powerful credential in the system only exists for a few seconds at a time.

There were scars here, too. The store container originally used `registry.k8s.io/kubectl`, which is distroless and has no shell — so the script that stores the unseal key simply couldn't run. Swapping to `alpine/k8s` fixed it. And there was a genuinely vicious one: the chart's own server‑configuration ConfigMap is *also* named `openbao-config`. A `configMapGenerator` we added with the same name quietly pruned the chart's ConfigMap and stranded the pod. The lesson — *never reuse a name the chart already owns* — is obvious in retrospect and invisible in advance.

We validated the entire no‑root bootstrap end‑to‑end on a freshly wiped volume: `openbao-keys` contained the unseal key and nothing else, the `config-admin` reconcile worked without root, and both secret stores came up Ready. (Wiping correctly is its own trap: deleting the pod and PVC together races the StatefulSet, which re‑grabs the volume before Longhorn releases it. The correct dance is scale to zero, wait for the pod to actually delete, delete the PVC, then scale back up.)

---

## The recipe

With the vault in place, every migration followed the same two‑beat rhythm. It is worth writing down precisely, because its safety comes entirely from the ordering.

**Beat one — seed.** Add a `PushSecret` (apiVersion `external-secrets.io/v1alpha1`, pointed at the write‑only `openbao-push` store) that copies the *existing* SOPS‑owned Secret up into OpenBao at `secret/<app>/<name>`. Commit. Wait for the PushSecret to report `True / Synced`. At this point the value lives in two places — the old SOPS file and the vault — and nothing has changed for the running app.

**Beat two — swap.** In a single commit, add an `ExternalSecret` (apiVersion `external-secrets.io/v1`, pointed at the read store `openbao`) that targets the *same* Secret name and keys, and `git rm` the `*.sops.yaml`. Flux applies the ExternalSecret, ESO pulls the value back down from the vault, and the Secret is now owned by ESO instead of SOPS. Verify the Secret's `ownerReferences` point at the ExternalSecret, the key count is exact, and the app is healthy.

Two refinements made this scale:

- **`dataFrom: [{ extract: { key: <path> } }]`** pulls *every* key from a vault path in one stanza, so a fifteen‑key secret needs one ExternalSecret rather than fifteen. (The PushSecret side has no such shorthand — you must list each key explicitly to push it. The asymmetry is mildly annoying and entirely survivable.)
- **`creationPolicy: Owner` adopts in place.** Many of our live Secrets were `owner=<none>` — applied once long ago, then orphaned from their kustomization. ESO will quietly take ownership of an existing, unowned Secret without recreating it, which means the migration is seamless: the value never blinks, the resourceVersion barely moves, and consuming pods never notice. We proved this on dozens of secrets and came to trust it completely.

One principle governed all of it, and violating it would have been catastrophic: **at‑rest encryption keys are never regenerated.** A database password can be rotated — CloudNativePG will happily reconcile a new one. But a key that has already encrypted data at rest — `AUTHENTIK_SECRET_KEY`, Dependency‑Track's `secret.key`, an app's `API_ENCRYPTION_KEY` — must be migrated by *seeding the existing value*, never by minting a fresh one from a generator. A new value there doesn't rotate anything; it corrupts everything the old key ever touched. So the generator lane is strictly for entropy that is allowed to be thrown away, and everything stateful goes value‑preserving through the vault. This distinction is the difference between a migration and an outage.

---

## The OIDC yak‑shave

Nothing in this project fought back harder than getting OpenBao to log *itself* in through Authentik. The symptom was maddening: the `openbao-config` job ran, claimed success, and silently skipped OIDC configuration. Underneath were **three stacked bugs**, each hiding the next.

1. **Wrong RBAC subject.** The cross‑namespace permission that lets the config job read Authentik's bootstrap token was bound to the old `openbao-bootstrap` ServiceAccount — but the job actually runs as `openbao-config`. The token read came back empty, permission‑denied, swallowed.
2. **Wrong provider lookup.** The script queried Authentik for a provider named `openbao-oidc`. The provider's real name is `OpenBao OIDC`. A `?name=` exact match found nothing; switching to `?search=openbao` found it.
3. **The one that cost the most hair: pretty‑printed JSON.** The in‑cluster Kubernetes API returns JSON formatted *with spaces* — `"key": "value"`, not `"key":"value"`. Every `grep '"key":"value"'` and `sed 's/.*:"//'` in the parser assumed the compact form and matched nothing. The fix was to make every pattern whitespace‑tolerant: `grep '"k": *"[^"]*"'`, `sed 's/.*: *"//; s/"$//'`.

Isolating these required dropping debug logging right into the job (`k8s_resp_len=1626 is_secret=0 ak_token=set … cs=set`) and watching the values appear one layer at a time until the log finally printed `oidc configured`. A reminder that "it returned success" and "it did the thing" are different claims, and only the second one matters.

(There's a related landmine worth flagging: OpenBao's OIDC needs **RS256**. Pin a `signing_key` on the Authentik provider or it falls back to HS256 and login fails with an error that points nowhere near the actual cause.)

---

## An interlude in which the backups were briefly on fire

Mid‑migration, a glance at a CloudNativePG cluster's `.status.lastSuccessfulBackup: <none>` set off alarms: *the backups are broken.* They were not. This was a good lesson in reading instruments correctly before yanking levers.

The truth was more nuanced. Most databases were backing up nightly exactly as designed; the `lastSuccessfulBackup` status field simply **does not populate on the barman‑cloud *plugin* path** the way it does on the legacy in‑tree path. The disaster‑recovery clusters showing nothing were *hibernated*, which is their correct resting state. The real, narrow gap was three databases that genuinely had no `ScheduledBackup` at all — because, it turns out, the `ScheduledBackup` is a **per‑application** resource, not something the shared backup component fans out for you. We added the three missing ones, staggered across the small hours, and every database was covered.

While in there, a second, unrelated mystery: the CNPG operator and the barman‑cloud plugin were both restarting on a loop. The easy assumption was OOM — but the pods were sitting at 16Mi against a 256Mi limit, nowhere near the ceiling. The crash logs told the real story: `leader election lost`, exit 1. On a **single‑replica** controller‑runtime manager, leader election buys you nothing and can only *cause* restarts when a lease renewal blips. The fix was a one‑line `--leader-elect=false` on each, and both have sat at zero restarts since. The detective‑work lesson stuck: *let the logs tell you the cause; don't pattern‑match the symptom to the nearest familiar villain.*

---

## The held bucket: doing the scary part deliberately

The bulk of the migration — random secrets, OIDC client secrets, external tokens, the shared S3 components — went in waves, low blast radius first, dozens of secrets falling in batches. But a handful were deliberately **held back** into a separate, gated pass, because their failure modes were ugly: the secrets referenced directly by CloudNativePG `Cluster` objects, and the single most dangerous secret in the cluster, `authentik-secret`.

We worked the held bucket methodically, and every one followed the seed → swap → verify recipe with the verification dial turned all the way up.

**Six database credential secrets** — for n8n, FreshRSS, SparkyFitness, Backstage, Grafana, and Guacamole — went first. Each adopted cleanly (`owner=ExternalSecret`), preserved its exact key count, and left all six CNPG clusters in a healthy `1/1` state with applications reconnecting without a stutter. SparkyFitness was the one to watch, because its password lives in a CNPG **managed role** that gets *reconciled* on change rather than merely *read* once at bootstrap — and it, too, came through with the managed role showing `reconciled`.

This batch also surfaced a genuinely sneaky structural gotcha. For n8n and Grafana, the database secret's SOPS file was referenced not from the app's own kustomization but from a **sibling `database/kustomization.yaml`** belonging to a separate `*-db` Flux Kustomization. Remove the SOPS file, and a build that *looked* unrelated would fail with `no such file or directory` from a path you weren't editing. The cross‑directory reference had to be unwired in lockstep with the swap. It is exactly the kind of coupling that no single file reveals.

**Two application‑config secrets** followed — FreshRSS's eleven keys and SparkyFitness's seven — adopted in place, pods Running.

**The arc runner secret** was a tidy case with a twist: a single GitHub App credential (`gha-runner-scale-set-secrets`, four keys) is *shared by two* autoscaling runner sets but defined once. Migrating the one definition quietly served both; afterward both listeners stayed Running and a runner was already mid‑job, none the wiser.

And then the boss fight.

---

## authentik-secret, and the circular dependency at the heart of the cluster

`authentik-secret` is the secret you migrate last and most carefully, for two compounding reasons. First, Authentik *is* single sign‑on for the entire cluster — get this wrong and you don't break one app, you break the front door to all of them. Second, and more subtly, one of its four keys — `AUTHENTIK_BOOTSTRAP_TOKEN` — is the credential the **`openbao-config` job uses to talk to Authentik.** That is a circular dependency with teeth: the vault's own configuration loop depends on a token stored in a secret we were about to hand from SOPS to the vault.

The saving grace was that the migration is **value‑preserving by construction.** Adoption via `creationPolicy: Owner` takes over the *existing* Secret in place; the four keys — `AUTHENTIK_SECRET_KEY` (an at‑rest key, never regenerated), the bootstrap password hash, the bootstrap token, the bootstrap email — keep their exact values. Nothing rotates. The token that `openbao-config` relies on is the same token before and after.

We seeded it, waited for `True / Synced`, swapped it, and then watched the two signals that actually mattered. The Secret came up `owner=ExternalSecret` with all four keys intact. And the `openbao-config` job — the one that authenticates to Authentik with that bootstrap token — ran again and completed in seven seconds. The circular dependency held. The front door stayed open.

(A small operational footnote: Flux's GitRepository polls on a one‑minute interval, and the webhook didn't fire for this particular push, so the swap took a couple of minutes to reconcile rather than seconds. Watching the git source revision lag the local `HEAD` is a good reminder that "I pushed" and "the cluster has it" are, again, two different claims.)

---

## Scars worth keeping

Some lessons were paid for in small disasters and near‑misses, and they're the part of the story most worth preserving.

- **Don't generate manifests inside a bash function here.** Partway through, `sed`, `wc`, `cat`, and even `kubectl` started returning "command not found" — but only inside a shell function and inside a piped `while` loop, where the PATH wasn't what the top‑level shell had. The cure was to stop being clever: generate manifests with the editor tools, do wiring with plain top‑level `sed` one command at a time.
- **A wildcard `rm` is a loaded gun.** An over‑broad `rm *-secrets.pushsecret.yaml` matched several *committed* files it was never meant to touch. They came back with `git restore` — the deletions were local and unpushed, the cluster untouched — but it was close enough to be instructive. That near‑miss is precisely why the rest of the work moved one explicit path at a time.
- **Verify the thing, not a proxy for the thing.** `lastSuccessfulBackup: <none>` looked like broken backups and wasn't. "Job succeeded" looked like OIDC configured and wasn't. Single‑replica "leader election lost" looked like OOM and wasn't. Every one of these was a case where the obvious reading of an instrument was wrong, and the only cure was to go look at the actual state — the Secret's owner, the key count, the job's real exit, the pod's real memory.

Underneath all of it ran a steady discipline: every change validated with `flux-local build ks` before commit, every swap gated on the seed actually syncing first, every adoption confirmed by `ownerReferences` and an exact key count rather than a hopeful glance. It is slow. It is also why nothing in this migration caused an outage.

---

## The irreducible floor

You cannot bootstrap a secrets manager entirely from secrets it manages. Something has to come first. Honest systems name that floor instead of pretending it doesn't exist, and ours is deliberately tiny:

- The **age key** itself, the github deploy key, and the Talos machine identity — the things needed before Flux, or even the cluster, exists.
- **`cluster-secrets.sops.yaml`**, which carries `${SECRET_DOMAIN}` and is substituted into roughly fifty `ks.yaml` files at *build time*. ESO writes runtime Secrets; it cannot do build‑time string substitution into Flux Kustomizations. This one stays SOPS forever, by design and without apology.
- The **OpenBao unseal key**, held as `openbao-keys` — the one credential that lets the vault open itself.

Everything above that floor is now ESO. Out of forty‑seven encrypted files, the cluster is down to exactly two `*.sops.yaml` under `kubernetes/`: the permanent `cluster-secrets` floor, and a single straggler. The migration above the floor is, for all practical purposes, done.

That straggler is **`zomboid-secrets`**, and it's blocked for an honest reason: there is no live `zomboid-secrets` Secret in the cluster at all — only the SOPS file. A `PushSecret` seeds *from* a live Secret, so there's nothing to seed. It's a decision, not a task: either provide the values or delete an unused file. Exactly the kind of thing worth leaving to a human who knows which it is.

---

## Epilogue: what we actually earned

Strip away the war stories and the win is mundane in the best way. Adding a secret to this cluster used to be a five‑step encryption ritual with a human in the middle. Now it is, at most, two manifests — a `PushSecret` to seed a value the human already has, or nothing at all for the random class, because a generator mints it and a human never sees it. No `sops --encrypt`. No ciphertext in git. No copy‑paste of a credential from one window to another.

And the properties we got almost for free are the ones that matter at 3am:

- **Running pods don't depend on the vault.** ESO caches real Secrets; a backend outage blocks rotation, never reads. The cluster keeps serving.
- **The most powerful credential barely exists.** OpenBao's root token is generated, used once, and revoked. There is no standing god‑mode to leak.
- **Rotation is a value change, not a ceremony.** Push a new value, let ESO reconcile it down. The thing that used to be a careful manual encryption is now a write to a vault.
- **Disaster recovery has a known shape.** The vault's own state rides the CNPG backups; the floor that recovers it is four files and an unseal key, all written down.

The human is out of the loop where the human was only ever a source of toil and risk — and still firmly *in* the loop for the two or three decisions that genuinely need judgment. That was the whole point. SOPS served this cluster well for a long time, and a thin, deliberate sliver of it always will. But the long goodbye is, at last, over: everything above the floor has crossed to ESO, and all that remains of SOPS is the handful of files that were always meant to stay — the age key, `cluster-secrets`, the Talos and deploy identities, the unseal key — plus one honest straggler waiting on a decision, not a migration.

*— and the secrets, for the first time, mostly look after themselves.*
