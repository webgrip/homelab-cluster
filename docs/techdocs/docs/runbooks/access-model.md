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
3. Push. Within one reconcile interval the broker creates the user and puts them in the groups
   their role projects onto; the Kubernetes root binds them in the namespaces their projects own.
4. They sign in at `https://authentik.<domain>` with Google. There is no enrolment: the roster
   is the allow-list, so a person not in `people.yaml` is refused after Google succeeds.

Propagation: Authentik groups and OpenBao roles within the broker's interval (15m); Kubernetes
bindings within the kubernetes root's interval (15m); application roles at the next login.

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
