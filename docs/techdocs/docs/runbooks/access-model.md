# The access model: joiner, mover, leaver

How a person gets, changes and loses access. Everything here is an edit to one of four files
under `kubernetes/apps/security/access-plane/model/`, validated on commit, reconciled by the
access plane ([access-plane runbook](access-plane.md)). Never fix a discrepancy by editing
Authentik, OpenBao or a binding by hand; the next reconcile reverts it and the audit log names
you.

## Glossary

| Term | Meaning here |
| --- | --- |
| Capability | One thing a principal may do, named for the act (`k8s-operate`, `registry-admin`). `capabilities.yaml` says what it projects onto and what it escalates to. |
| Role | A bundle of capabilities a person is trusted with (`platform-engineer`, `developer`, `client`). Exactly one per person. |
| Project | What a person's scoped capabilities land on: namespaces, repositories, registry projects. `projects.yaml`. |
| Grant | One extra capability on a person, dated, owned and with a reason. `people.yaml`. |
| Scope | `project` (the person's projects) or `cluster` (everywhere). Cluster scope comes only from a dated grant, never from a role. |
| Reviewed | The date a human last confirmed the entry. Older than a year fails CI. |

## Joiner

The newcomer's half of this is [Start here](../general/start-here.md); send them that link.
This is yours.

### Before the commit

- [ ] They have a Google Workspace account on `webgrip.nl` with 2-step verification enforced.
      The consent screen is Internal, so any other address never reaches Authentik.
- [ ] You know their role and projects. `developer` is the default; `platform-engineer` reaches
      every secret and `main`, so it is a decision, not a convenience. Read what each role gets
      on [Start here](../general/start-here.md#2-what-you-can-open) and the reachable column of
      the [access matrix](../general/access-matrix.md).

### The commit

1. Add an entry to `people.yaml`:

   ```yaml
     - id: jane
       kind: staff
       status: active
       name: Jane Example
       email: jane@webgrip.nl
       username: jane
       forge: jane
       role: developer
       projects: [erfbeeld]
       reviewed: 2026-09-14
       grants: []
   ```

   `email` must be the Google Workspace address: it is the Authentik identity, the Kubernetes
   username (`oidc:jane@webgrip.nl`) and the key everything joins on. `username` is what
   Authentik and every application will show. `forge` is the Forgejo handle.
2. Run `mise exec -- ./scripts/validate-access-model.sh` and commit. The pre-commit hook runs
   the same check.
3. Push.

### What the platform does with it

| System | What appears | When |
| --- | --- | --- |
| Authentik | The user, and every group their role projects onto | the broker's next interval (15m) |
| OpenBao | The `kubernetes-login` group membership, through the Authentik group | at their first `bao login` |
| Kubernetes | A RoleBinding to their tier in every namespace their projects own | the kubernetes root's next interval (15m) |
| Harbor | Membership of each registry project their projects own | the broker's next interval |
| Forgejo | The account, and the `Developers` or `Owners` team | at their first sign-in, re-checked every sign-in |
| Grafana, LiteLLM, Backstage, Vikunja | The account with the role their groups map to | at their first sign-in |
| Vikunja boards | Membership of the `Webgrip` team, which the shared boards are given to | at their first sign-in, re-checked every sign-in |

The `Developers` team itself is kept by the `developers-team-provisioner` CronJob in `forgejo`,
not by hand: Forgejo skips a mapped team that does not exist, silently.

The Vikunja side works the same way. Authentik emits a `vikunja_groups` claim for members of
`homelab-users`; Vikunja joins them to the team whose external id matches and drops them from it
when the claim stops naming it. The `vikunja-board-shares` CronJob in `vikunja` keeps that team
and its board shares: `SHARED_BOARDS` lists the Vikunja project ids, read and write. Adding a
board is adding its id there; removing it unshares it on the next hour.

### Verify against the live systems

```sh
mise exec -- kubectl -n security get terraform
mise exec -- kubectl get rolebindings -A -o json \
  | jq -r '.items[] | select(any(.subjects[]?; .name == "oidc:jane@webgrip.nl")) | "\(.metadata.namespace)/\(.roleRef.name)"'
mise exec -- kubectl auth can-i list pods -n erfbeeld --as oidc:jane@webgrip.nl
```

Both objects `Ready` with no pending plan, one binding per owned namespace, and `yes`. Then ask
them to sign in at Authentik; a refusal after Google means the email differs byte for byte.

### VPN devices

Each human may list `wireguard` devices: a `device` name and the device's WireGuard **public**
key, which the person generates and sends you ([Start here, step 0](../general/start-here.md#0-the-vpn-if-you-work-away-from-the-lan)).
The `wireguard-peers` CronJob in `security` reconciles them into the router every fifteen minutes
through the OPNsense API, as peers named `ap-<id>-<device>` on the one WireGuard instance:

- a new device gets the next free tunnel address and keeps it for its life, a rotated key keeps
  the address;
- a device, person or `status: suspended` that leaves the roster loses its peer on the next run;
- peers whose names do not start with `ap-` were made by hand and are never touched.

Then hand the person their tunnel settings, everything except the private key:

```sh
mise exec -- kubectl -n security get cm wireguard-peers -o jsonpath='{.data.ap-jane-laptop}'
```

The validator refuses a malformed key, the same key on two devices, a device declared twice and a
peer name over OPNsense's 64 characters.

#### One-time setup of the reconciler

The reconciler holds one credential: an OPNsense API key for a user that can do nothing but
WireGuard. It is the only thing created by hand, once.

1. OPNsense, **System → Access → Users**: add `access-plane` with a random password nobody keeps, no shell, and
   **Effective Privileges** `VPN: WireGuard: Configuration` only.
2. On that user, **API keys → +**. The browser downloads `key` and `secret`.
3. Store them, then delete the download:

   ```sh
   export BAO_ADDR=https://openbao.webgrip.dev
   mise exec -- bao login -method=oidc
   mise exec -- bao kv put secret/opnsense/wireguard-reconciler key=<key> secret=<secret>
   ```

4. Within the hour External Secrets writes `opnsense-wireguard-api` and the next run succeeds:
   `kubectl -n security logs job/<latest wireguard-peers job>`.

#### Symptom → cause

| Symptom | Cause | Fix |
| --- | --- | --- |
| Pod in `CreateContainerConfigError` | `opnsense-wireguard-api` does not exist yet | The one-time setup above |
| `public key does not match pinned public key` | OPNsense's web certificate was replaced with a new key | Pin the new key in `OPNSENSE_PINNED_PUBKEY` (command below) and commit |
| `OPNsense has 2 WireGuard instances` | A second instance was added | Set `WG_SERVER_NAME` on the CronJob |
| `401` from the API | The key was revoked or lacks the WireGuard privilege | Recreate it and store it again |
| `404` on `getServerInfo` | OPNsense older than the peer generator API | Upgrade OPNsense |

```sh
echo | openssl s_client -connect 10.0.0.1:443 2>/dev/null | openssl x509 -pubkey -noout \
  | openssl pkey -pubin -outform der | openssl dgst -sha256 -binary | base64
```

The web certificate is self-signed, so the CronJob pins its public key instead of trusting a CA;
it expires on 2027-01-08 and a renewal with a new key fails every run until the pin is updated.
`KubeJobFailed` fires on the first failure.

## Mover

Change `role:` or `projects:`. Bump `reviewed:` while you are there. A capability the person
no longer holds is removed from every group and binding on the next reconcile.

## One extra thing, for a while

A dated grant on the person:

```yaml
    grants:
      - capability: storage-admin
        until: 2026-12-31
        owner: ryan@webgrip.nl
        reason: Longhorn migration of the erfbeeld volumes
```

`until`, `owner` and `reason` are all required; together they are the audit trail. When `until`
passes the grant stops rendering on the next plan, with no edit and no reminder. The nightly
validator warns for the last thirty days. `until: none` is allowed only on a break-glass
capability.

## Leaver

Delete the entry. Do not mark it departed and leave it; the commit is the record. The next
reconcile deletes the Authentik user, every membership, and every binding. Their current tokens
run out on their own: an Authentik session within hours, an OpenBao token within eight hours,
a Kubernetes OIDC token within the hour.

Suspension while somebody is away is `status: suspended`: the entry stays, nothing renders.

## A new project

Add it to `projects.yaml` with the namespaces it owns. A namespace belongs to exactly one project;
the validator refuses a second claim. A namespace nobody owns gets no human binding at all,
which is the right default.

## A new capability

Add it to `capabilities.yaml` with a `summary`, a `risk`, an `owner`, what it `projects` onto,
and what it `escalates_to`, honestly. A capability that projects onto nothing grants nothing,
which is fine for one declared before its mechanism exists. Then grant it through a role or a
dated grant.

## Recertification

Every person and every project carries `reviewed:`. The nightly job fails when one is older
than a year; the fix is to look at the entry, decide it is still right, and bump the date in a
commit. That commit is the certification.

## Reading the result

The [access matrix](../general/access-matrix.md) is computed from the model on every docs
build: declared against reachable, per person, plus every routed surface and what authenticates
it. The live truth is `kubectl -n security get terraform` and the last applied plan.

## Symptom → cause

| Symptom | Cause | Fix |
| --- | --- | --- |
| Commit refused: `additionalProperties` | A field the schema does not know, usually a typo | Compare with the schema under `model/schema/` |
| Commit refused: `unknown capability` | A name that is not in `capabilities.yaml` | Add the capability or fix the name |
| Commit refused: `is scopable and needs scope` | A Kubernetes, registry or preview capability granted without `scope:` | Add `scope: project` or `scope: cluster` |
| Commit refused: `a role may not confer cluster scope` | `scope: cluster` inside `roles.yaml` | Move it to a dated grant on the person |
| New person cannot sign in | Broker has not reconciled yet, or the email differs from their Google account | `kubectl -n security get terraform access-broker`; compare the email byte for byte |
| Person signed in, application refuses | The application's gate group is not among their capabilities' projections | Grant the capability, or check the application's gate in the module |
| `Forbidden` on the Kubernetes API | No Kubernetes-projecting capability at that scope | Grant `k8s-read` or `k8s-operate` at `scope: project`, or a dated cluster grant |
