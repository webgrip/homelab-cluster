# RFC: The access plane — Google identity, one entitlement model, one reconciler

> Status: **Accepted**, in rollout (stages 4 and 7 have a human step left) · Date: 2026-09-14 · Supersedes the open items of
> [Identity & SSO](rfc-identity-sso.md) · Sibling of code14
> [RFC-0018](https://gitlab.com/code14nl/internal/devops/staging-cluster/-/blob/main/docs/rfcs/rfc-0018-the-access-plane-is-a-provider-not-a-script.md)
> (staging-cluster), which this deliberately builds past.

> **TL;DR.** People sign in with their Google Workspace account and nothing else. Who may do what
> is declared once, in four small YAML files, and one OpenTofu module run by Flux's
> tofu-controller makes Authentik, OpenBao and the Kubernetes API agree with it. The staging
> cluster reached the same shape through a 3,000-line Python+CUE renderer, a bash converger and a
> membership CronJob, and then decided to replace the converger with the provider. This estate is
> greenfield for all of it, so it skips straight to the end state and builds none of the
> intermediate machinery: no CUE, no renderer, no CronJob, no generated files in Git.

## Why

What exists today (verified in-tree 2026-09-14, [inventory](#appendix-a-what-exists-today)):

- **Authentik is a password IdP.** One flow, `homelab-authentication`: email or username, an inline
  password stage, then TOTP/WebAuthn. No Google source, no source-enrollment flow. The only human
  account was created by hand in the admin UI and placed in `homelab-users` and `homelab-mfa` by
  hand. Twelve blueprints wire twelve OIDC clients, every one of them gated on the same two groups.
- **Authorization is two booleans.** `homelab-admins` and `homelab-users`. Harbor maps
  `oidc_admin_group: harbor-admins`, a group that no blueprint creates, so the mapping is dead.
  OpenBao's `admins` policy is `path "*"` with `sudo`, aliased from `homelab-admins`. There is no
  roster, no dated grant, no review date, and no place a person exists as a record.
- **The Kubernetes API has one credential.** The Talos-issued `system:masters` certificate in
  `./kubeconfig`, used by the owner, by every Claude Code session on the owner's machine, and by
  nothing else. No OIDC flags, no human RBAC subject anywhere in `kubernetes/`, no audit policy.
  Revoking it means rotating the cluster CA.
- **Blueprints cannot withdraw.** Upstream: objects a blueprint created are untouched when the
  blueprint goes; a blueprint stuck in `error` is never retried. So a group membership written in
  a blueprint could never be revoked by deleting the line, which is the guarantee an access model
  exists to provide.

The staging cluster answered the same questions between 2026-08-20 and 2026-09-14 and left a
paper trail worth reading before repeating it: per-user Kubernetes identity via Google directly
(ADR-0025), Google-only login with the password door unlisted (ADR-0027), one model rendered
everywhere (ADR-0028), agents acting as a named human (ADR-0033), and finally the provider-backed
reconciler (ADR-0048) that deleted 3,900 lines of shell and generated YAML. The shape is right.
The build order was expensive because it was discovered, and the last step made three of the
earlier ones unnecessary. This RFC starts where staging ended.

## Decisions

| # | Decision | Chosen | Alternatives considered |
| --- | --- | --- | --- |
| D1 | Upstream identity | Google Workspace (`webgrip.nl`), for every human, on every surface | Authentik local passwords (today); Keycloak as broker |
| D2 | Broker | Authentik stays; Google is its only interactive source; the password flow survives unlisted as break-glass | Keycloak (CNCF); Dex; Zitadel; no broker |
| D3 | Enrolment | **Closed.** Users are pre-created from the roster; the Google source links by email and has no enrollment flow | Open enrolment gated on an Internal consent screen (staging) |
| D4 | Reconciler | One OpenTofu module, run in-cluster by tofu-controller (Flux), providers `authentik`, `vault`, `kubernetes` | Python renderer + CUE + CronJob converger (staging v1); Crossplane; Burrito; `tofu apply` from CI |
| D5 | Model | Four YAML files, JSON Schema for shape, a 60-line validator for cross-file rules and dates, read directly by the module | CUE closed structs (staging); the model as CRDs; Backstage catalog as system of record |
| D6 | State | tofu-controller's default: a Kubernetes Secret in `security`, etcd-encrypted at rest | S3 bucket on Garage with a seeded key (staging) |
| D7 | Kubernetes API | OIDC flags on the API server pointing at Google **directly**, `hd=webgrip.nl` required, per-user bindings from the model, `kubectl oidc-login` | Via the broker; Pinniped (CNCF sandbox); Teleport; per-person client certs |
| D8 | Effective access | `escalates_to` edges stay data in the capability catalogue; the closure and the matrix are a docs-build macro, never a committed file | Committed `access-matrix.md` with a drift gate (staging); OpenFGA / SpiceDB |
| D9 | Non-OIDC apps | Envoy Gateway `SecurityPolicy` OIDC against a broker client, one capability per audience | Authentik proxy outpost; per-app oauth2-proxy; accept LAN-only |
| D10 | Machine identity | Inventory in the roster, no capabilities, reconciled by nothing here; agents run under the human's own credential until an in-cluster agent needs the API | Rostered service accounts in Authentik; impersonation now |

### D1 · Google is the identity

Every human who touches this estate has a `webgrip.nl` Workspace account. Passwords in Authentik
are a second credential nobody rotates, a second MFA enrolment nobody keeps, and a login form
that trains people to type a Google password into a non-Google page. MFA becomes Google's, which
is enforced at the Workspace level and audited there.

### D2 · Authentik stays, and the CNCF question is answered honestly

Keycloak is the CNCF identity broker and the only serious reason to move. It was weighed on what
it would change *for this decision*: nothing. Both brokers have an official OpenTofu provider,
both federate Google, both emit a groups claim, both run one Postgres. Keycloak costs a JVM on a
cluster that already fights for memory, a migration of twelve OIDC clients, and a
`KeycloakRealmImport` that is create-once rather than converging. Authentik's configuration
becomes fully provider-managed under D4, which removes the blueprint failure modes that were the
real complaint. **Revisit** if Authentik's licence changes, if a SAML or LDAP need arrives that
Authentik's MIT core does not cover, or if a second cluster makes a shared external broker worth
its own footprint.

The login page gets a new flow, `webgrip-authentication`: an identification stage with
`user_fields: []` and the Google source as its only option, and the default brand repointed at
it. The existing `homelab-authentication` flow keeps its password and MFA stages and is reachable
only by URL: it is the break-glass door for `akadmin`, whose password sits in OpenBao. A broken
change to the new flow leaves the brand on the old one; a wrong Google client secret leaves the
break-glass URL working. Neither failure locks the owner out.

### D3 · Enrolment is closed, and the roster is the allow-list

Staging enrols anyone who passes Google's Internal consent screen and lets them land in no
groups. That is safe for a company where the Workspace directory *is* the roster. Here the
roster is smaller than the directory could ever be, and it may one day include a client with a
Gmail address that no Workspace rule can express. So the module creates every user from
`people.yaml` before they ever sign in, the Google source uses `email_link` matching, and it has
no enrollment flow. A Google account not in the roster fails at Authentik with "source is not
configured for enrollment" and never obtains a session. Adding a person is one YAML entry;
removing them deletes the user and every membership on the next reconcile.

Two staging patches disappear with this: the shipped enrollment stage no longer needs its user
type forced to `internal`, and the `hd` claim is no longer the thing keeping strangers out.

### D4 · The reconciler is a provider, not a script

The staging cluster's ADR-0048 already makes the argument: comparing what a system has with what
Git says, and fixing the difference, is what a provider does. Its module manages Authentik,
OpenBao and Harbor with about 1,100 lines of HCL. This estate reuses the shape and drops Harbor
(Harbor already maps OIDC groups to roles at login; robot accounts are inventory) and adds the
`kubernetes` provider for the human RBAC bindings, so that a person's Kubernetes access and their
broker groups are one resource graph with one plan.

tofu-controller was checked, not assumed: v0.16.5 shipped 2026-08-06 with monthly patch releases
through 2026, under `flux-iac`. The module is the investment; if the controller ever goes, the
same module runs from a Forgejo Actions job with an OpenBao OIDC token, which is the fallback
ADR-0048 names too.

**Two `Terraform` objects, one module directory.** `access-broker` holds the `authentik` and
`vault` providers; `access-kubernetes` holds only the `kubernetes` provider and reads the same
model files. The split exists so that Kubernetes access keeps reconciling, and keeps revoking, on
a day when Authentik or OpenBao is down. This is the same reason staging keeps `human-access`
free of any `dependsOn` on the secrets platform.

**Credentials.** The runner authenticates to OpenBao through the existing `kubernetes` auth mount
as a new role `tofu`, with a policy limited to `auth/oidc/*`, `identity/*`, `sys/policies/acl/*`,
and reads on the two KV paths that hold the Authentik API token and the Google client. The
Authentik token is read as an ephemeral value and never enters plan or state. No standing
credential is created anywhere.

**No comments in the HCL.** Staging's module carries its rationale as comments; this repository
does not allow that in any language. Intent goes into resource names and this document, and the
runbook carries the operator procedure.

### D5 · The model is four files and one schema

```
kubernetes/apps/security/access-plane/model/
  capabilities.yaml   the verbs: what one may do, what it projects onto, what it escalates to
  roles.yaml          what a person is trusted to do, as a bundle of capabilities
  projects.yaml       what a project owns: namespaces, repositories, registry projects
  people.yaml         one entry per human and per machine principal, with dated grants
  schema/*.schema.json
```

`projects.yaml` replaces staging's `teams.yaml` on purpose. Staging's RFC-0017 found that the
team was an indirection that kept being wrong, and that in the end a project is linked to a
person. This estate is organised by product and customer (erfbeeld, glide, twente.dev, de
vloer, the cluster itself), not by team, so the where-axis is the project. A person holds one
role and a list of project memberships; a scoped capability resolves against the union of what
those projects own. A dated grant can additionally name a project. Cluster scope is never
inherited from a role: it is a dated grant on a person with a named owner and a reason, exactly
as in staging.

Every rule staging encoded in CUE is either a shape rule or a cross-file rule. Shape rules
(closed objects, enums, required fields, date formats) are JSON Schema 2020-12 with
`additionalProperties: false`, which this repository's editors already understand through the
`yaml-language-server` header and which `check-jsonschema` runs in the `lint` job and the
pre-commit hook. Cross-file rules (a capability named in a grant exists; a role is granted to
someone of the right kind; `until: none` only on break-glass; a review date under twelve months)
are one stdlib-plus-PyYAML script in `scripts/`, the same shape as the three validators already
there, run in `lint` and nightly. Anything the validator misses fails the plan, loudly, on the
next reconcile. CUE is removed from `.mise.toml`; nothing else used it.

The model directory also carries a `configMapGenerator`, so the roster is readable in-cluster
with the break-glass certificate and no checkout, which is the one argument for keeping it under
`kubernetes/` rather than next to the module.

### D6 · State lives where the controller puts it

Staging keeps state in a Garage bucket because the state names every OIDC client secret and a
bucket has a backup story. Weighed again here: the bucket adds a key a person seeds, an S3
backend stanza, and a dependency of the access plane on Garage being up, and what it protects is
a cache of object ids that `import` blocks rebuild in minutes. The Kubernetes Secret backend is
the controller's default, is encrypted at rest by Talos's secretbox key like every other Secret
that already holds these values, and depends on nothing but the API server. Loss of state is
work, not loss of access. **Revisit** if the state grows a value that exists nowhere else.

### D7 · The Kubernetes API trusts Google directly

The API server verifies Google's token itself, with `oidc-required-claim: hd=webgrip.nl`,
`oidc-username-claim: email` and `oidc-username-prefix: "oidc:"`. Not the broker, deliberately:
Authentik, its database and its storage all run on this cluster, and the credential needed to fix
a storage incident must not be issued by a component the storage incident took down. Google emits
no groups claim, so bindings name users; the module renders them from the roster, so a person
still exists in one place.

Pinniped was considered as the CNCF answer. It buys short-lived credentials without touching the
API server, and a Supervisor that spans clusters. For one Talos cluster it is two more
components on the critical path for one human, and Talos applies `.cluster` flags without a
reboot. **Revisit** when a second cluster exists. Kubernetes' structured
`AuthenticationConfiguration` would allow CEL claim rules and a second issuer without a restart,
but Talos exposes no field for it and placing the file needs `machine.files`, which is
boot-only; flags it is, until Talos grows the field.

Three aggregated ClusterRoles from staging come across as static YAML: `human-reader` (the
built-in `view` plus cluster-scoped reads, no Secrets, no RBAC), `human-operator` (restart,
scale, exec, port-forward, reconcile Flux, cordon), and `cluster-admin`. They are not per-person
and never change with the roster, so they are plain manifests Flux reconciles, not module
resources. The bindings are the module's.

The admin certificate stays, moves out of the working kubeconfig into a file that takes a
deliberate `--kubeconfig`, and becomes evidential: an API-server audit policy on the control
planes, shipped by the existing Alloy agent into VictoriaLogs, and one alert,
`KubernetesBreakGlassCertificateUsed`, on any authenticated username that is neither `system:`
nor `oidc:`. Until that alert fires on a test call and stays quiet on a day of normal use, the
Kubernetes half is not done.

A Kyverno rule in Audit, then Enforce, refuses any RoleBinding or ClusterRoleBinding with a
`User` or `Group` subject that does not carry the module's provenance label. GitOps alone cannot
stop a `kubectl apply` from cluster-admin; admission can.

### D8 · The matrix is a view, and the graph is data

`escalates_to` stays on every capability, with a mandatory `via`, because it is what turns
"platform engineers cannot read Secrets" into "platform engineers can read every Secret through
`pods/exec`, and here is the edge". The transitive closure is forty lines of Python. Staging
committed the rendered matrix and gated it against drift; that gate exists only because a
committed artefact can drift. `docs/techdocs/main.py` is already a build-time macro module that
renders inventories from the GitOps tree under Zensical, so the access matrix becomes one more
macro: declared column, reachable column, surfaces with no authorization, break-glass census.
Nothing is generated into Git, nothing can drift, and the page is exact on every docs build.

OpenFGA and SpiceDB were considered for the reachability question and rejected for the reason
staging's RFC-0017 records: the query they answer is already answered by a closure over a graph
that fits in one file, and neither OpenBao nor the API server would consult them, so the policies
would still need rendering afterwards.

### D9 · Apps without OIDC get the gateway, not an outpost

The open decision of the [identity RFC](rfc-identity-sso.md) is closed the way staging closed it:
an Envoy Gateway `SecurityPolicy` with an OIDC client on the broker, one client per audience,
authorization by an Authentik policy binding on the client's application. The first audiences
are `storage-admin` (Longhorn, which deletes volumes) and `dashboards-view` (flux-ui, Hubble,
VictoriaLogs, Alertmanager, policy-reporter). The gateway fails closed, so each SecurityPolicy
lands only after its client secret is Ready, in its own commit.

### D10 · Machines are inventory

Every non-human principal that can reach anything is in `people.yaml` with `kind: machine`, an
owner and a purpose, and holds no capability: `akadmin`, `gitea_admin`, the Harbor local admin,
`webgrip-ci`, `renovate`, `agent-builder`, `agent-reviewer`, the Flux and External Secrets
controllers, the `k8s-mcp` service account. Nothing here reconciles them; the matrix lists them
so "what else can reach this?" has an answer. Staging's impersonation model for agents is not
built yet: Claude Code sessions on the owner's machine will use the owner's OIDC context after
D7 and are already attributed to the owner. **Trigger** for building `act-as-human`: the first
in-cluster agent that needs the Kubernetes API.

## The catalogue, sized for this estate

Roles, five. Fewer than staging's nine because a role nobody holds is drift waiting to happen,
and a dated grant covers the gap until a second holder makes a role worth writing.

| Role | Holds | Who |
| --- | --- | --- |
| `platform-engineer` | `k8s-operate` (scope: project), `secrets-admin`, `registry-admin`, `repo-admin`, `grafana-admin`, `dashboards-view`, `storage-admin`, `litellm-admin`, `vloer-admin`, `tasks-use`, `catalog-use` | the owner; cluster-scope `k8s-admin` is a dated personal grant on top |
| `developer` | `k8s-read` (project), `registry-push` (project), `repo-contribute`, `grafana-edit`, `tasks-use`, `catalog-use` | nobody today; the entry a collaborator gets |
| `client` | `previews-use` (project) | nobody today; the entry a customer gets, `kind: external` |
| `agent` | `act-as-human` (cluster, projection deferred) | `human: false` |
| `service` | nothing | `human: false`, inventory only |

Capabilities are named for the act and carry their projection. The Authentik group per capability
replaces the two-group world: `homelab-admins` and `homelab-users` survive only as the projections
of `repo-admin` and `repo-contribute`, because Forgejo's `groupTeamMap` already binds them to
`Owners` and `Developers` and there is no reason to rename what works.

| Capability | Risk | Projects onto | Escalates to |
| --- | --- | --- | --- |
| `k8s-read` / `k8s-operate` / `k8s-admin` | low / high / critical | ClusterRole `human-reader` / `human-operator` / `cluster-admin` | operate → `secrets-read-all` via exec, `db-admin`, `flux-suspend` |
| `secrets-admin` | critical | group `openbao-admins` → OpenBao policy `admins` | `registry-admin`, `repo-admin` via credentials stored in the vault |
| `registry-push` / `registry-admin` | medium / critical | groups `harbor-developers` / `harbor-admins` | admin → `supply-chain-write` |
| `repo-contribute` / `repo-admin` | medium / critical | groups `homelab-users` / `homelab-admins` → Forgejo `Developers` / `Owners` | admin → `k8s-admin` via Flux applying `main` |
| `grafana-edit` / `grafana-admin` | medium / medium | Grafana role via claim | — |
| `dashboards-view` | high | group `cluster-dashboards` → SecurityPolicies | `secrets-read-all` via logged credentials |
| `storage-admin` | critical | group `storage-admins` → Longhorn SecurityPolicy | — |
| `litellm-admin`, `vloer-admin`, `vloer-operate`, `tasks-use`, `catalog-use`, `previews-use` | medium | one group each | — |
| `break-glass-k8s` / `-authentik` / `-openbao` / `-forgejo` / `-harbor` / `-grafana` | critical | none; `alert:` required on the Kubernetes one | each is its target, without SSO |
| `secrets-read-all`, `supply-chain-write`, `flux-suspend`, `db-admin` | derived | none; targets of edges only | — |

`admins.hcl` is `path "*"` with `sudo` today. It narrows to the KV tree plus what the UI needs,
the way staging's does, in the same change that moves the OIDC role into the module.

## What is deleted, and what is never built

| Never built here | Staging equivalent | Why not |
| --- | --- | --- |
| CUE schema, `cue.sh`, the `cue` tool | `schema.cue`, `load.cue` | JSON Schema does the shape; the module does the joins |
| Python renderer (2,900 lines) | `scripts/entitlements/` | the provider reads the model directly |
| Membership ConfigMap + reconcile CronJob | `authentik-reconcile` | `authentik_group.users` is authoritative |
| Generated `bindings.yaml`, `rolebindings.yaml`, `agents.yaml` | `human-access/` | `kubernetes_*_binding_v1` resources |
| Rendered `CODEOWNERS` | ADR-0030 | Forgejo's file is advisory and there is one reviewer; the plane is Forgejo teams via groups |
| Committed `access-matrix.md` + drift check | ADR-0028 D6 | a docs macro |
| `resources.yaml` inventory (1,465 lines) | ADR-0039 | surfaces are derived from HTTPRoutes and SecurityPolicies by the same macro; `authz: none` is a query, not a hand-kept row |
| Backstage `entitlements.yaml` export | ADR-0028 D7 | nothing consumes it |
| Metrics exporter + five alerts + dashboard | `entitlements/app` | expiry is enforced at plan time; recert by the nightly validator; drift by the controller's own condition |
| Engagements app | `engagements-render` | a project with an `ends` date |

| Deleted from this repository | Replaced by |
| --- | --- |
| Twelve Authentik blueprints and the `!Env` client-secret plumbing | one `oauth_applications` map in the module; secrets read from OpenBao |
| `homelab-mfa` group, `homelab-mfa-required` policy and its twelve bindings | Google's MFA |
| `svc-homelab` service account | nothing; it had no consumer |
| The OIDC and identity-group section of OpenBao `config.sh` | `vault_jwt_auth_backend`, `vault_identity_group`, `vault_identity_group_alias` |
| `aqua:cue-lang/cue` in `.mise.toml` | `pipx:check-jsonschema`, `aqua:opentofu/opentofu`, `aqua:int128/kubelogin` |

## Rollout

Every stage is one or more commits to `main`, validated with `flux-local` and the lint job
before push, reversible on its own, and verified against live state before the next begins.
Human-only steps are handed over as a single paste-ready block.

| Stage | Lands | Human step | Verified by | Status |
| --- | --- | --- | --- | --- |
| 0 | This RFC; ADRs for D2+D3, D4+D5, D7; the `google-oauth-clients` and `access-plane` runbooks | Create the GCP project, Internal consent screen, two OAuth clients; `bao kv put` both; confirm Workspace 2-step verification is enforced | the two OpenBao paths exist | done 2026-09-14 |
| 1 | tofu-controller HelmRelease in `flux-system`; runner ServiceAccount; OpenBao role `tofu` and its policy in the bootstrap floor; egress NetworkPolicy; two `Terraform` objects on an empty module, plan-only | none | both objects `Ready`, plan `No changes` | done 2026-09-14 |
| 2 | The model, its schema, the validator, the lint and pre-commit gates; the module imports the existing groups and the owner's user | approve the first plan by id | the plan adopts and changes nothing; a second plan is empty | done 2026-09-14 |
| 3 | Google source, Google-only flow, brand repoint; blackbox canary on the login executor | approve the plan; sign in once through Google | brand API shows the new flow; `user_fields: []`; break-glass URL still signs in `akadmin` | done 2026-09-14 |
| 4 | API-server flags in the Talos controller patch; the three ClusterRoles; bindings from the module; kubelogin in mise; `scripts/kube-oidc-setup.sh`; audit policy; Alloy pipeline; the break-glass alert; the Kyverno provenance rule in Audit | `just talos-apply-node` on each control plane, one at a time; run the setup script; move the admin credential out | `kubectl auth whoami` is `oidc:ryan@webgrip.nl`; a call with the admin cert fires the alert | done 2026-09-15 |
| 5 | The twelve OIDC clients and OpenBao's OIDC mount, roles, identity groups and narrowed `admins` policy adopted into the module; blueprints, `homelab-mfa`, `svc-homelab` and the `config.sh` section deleted | approve the adoption plan | every app signs in; `check-oidc.sh` green; `bao token lookup` shows `admins` | done 2026-09-14 |
| 6 | SecurityPolicies for Longhorn and the dashboards, one commit per audience | none | each route redirects to the broker; the wrong group is refused | done 2026-09-14 (the refusal waits for a second human) |
| 7 | The access-matrix macro; runbooks for joiner/mover/leaver and Kubernetes login; `rfc-identity-sso.md` closed as superseded; Kyverno rule to Enforce | none | docs build renders the matrix; `flux-local` and lint green | matrix, runbooks and the superseded RFC landed 2026-09-14; Kyverno to Enforce once the report is clean |

The first plan in stages 2, 3 and 5 is approved by a person. After stage 5, both objects run
`approvePlan: auto` and a merge to `main` is the change, as it is for everything else here.

## Confirmation

- `kubectl -n security get terraform` shows both objects `Ready`, no drift, last plan applied,
  and a forced reconcile plans no changes.
- The login page at `authentik.<domain>` has one control; the break-glass flow URL still accepts
  `akadmin`; a Workspace account that is not in `people.yaml` is refused.
- `kubectl auth whoami` from the working kubeconfig returns `oidc:ryan@webgrip.nl`; a call with
  the admin certificate fires `KubernetesBreakGlassCertificateUsed` within a minute.
- Deleting a dated grant from `people.yaml` removes the binding and the group membership on the
  next reconcile with no other edit; a grant whose `until` has passed is gone after the next
  interval with no edit at all.
- `check-jsonschema` fails on a misspelled field; the validator fails on an unknown capability
  and on a review date older than a year; both run in `lint` on every push and nightly.
- The docs matrix lists every human, every machine principal, every capability with declared and
  reachable holders, and every routed surface with no authorization.

## Out of scope

- Impersonation for in-cluster agents (D10 trigger).
- Forgejo team membership for bots as a reconciled plane; they remain provisioner-job owned.
- Harbor project-level group membership; `oidc_admin_group` plus the developer group is enough
  for one registry with one operator.
- Structured `AuthenticationConfiguration` on the API server, until Talos exposes it.
- State encryption with an OpenBao transit key (D6 trigger).

## References

- code14 staging-cluster: ADR-0025, ADR-0027, ADR-0028, ADR-0033, ADR-0048, RFC-0012, RFC-0017,
  RFC-0018 and the `feat/access-plane-tofu` branch, whose module this one is shaped after.
- [tofu-controller](https://github.com/flux-iac/tofu-controller) v0.16.5 ·
  [goauthentik/authentik provider](https://registry.terraform.io/providers/goauthentik/authentik) ·
  [hashicorp/vault provider](https://registry.terraform.io/providers/hashicorp/vault) (OpenBao
  API-compatible; the maintainers prefer upstream collaboration to a fork, openbao/openbao#339) ·
  [int128/kubelogin](https://github.com/int128/kubelogin)
- [Identity & SSO RFC](rfc-identity-sso.md) · [ADR-0022](../adr/adr-0022-authentik-oidc-phased.md) ·
  [ADR-0055](../adr/adr-0055-one-secrets-model-six-levels.md) ·
  [Request authorization at the gateway](rfc-request-authorization-envoy.md)

## Appendix A: what exists today

| Surface | Mechanism | Group → role | Secret |
| --- | --- | --- | --- | --- |
| Grafana | native OIDC, auto-login | `homelab-admins` → GrafanaAdmin, `homelab-users` → Editor, else Viewer | `secret/grafana/oauth` |
| Forgejo | chart `oauth[]` | `homelab-admins` → site admin + `Owners`; `homelab-users` → `Developers` | `secret/forgejo/oidc` |
| Harbor | `configureUserSettings` | `oidc_admin_group: harbor-admins` (group does not exist) | `secret/harbor/oidc` |
| OpenBao | `auth/oidc`, configured by `config.sh` | identity group `openbao-admins` ← alias `homelab-admins` → policy `admins` (`path "*"`, `sudo`) | read live from the Authentik API |
| Backstage, Vikunja | native OIDC | none | `secret/backstage/oidc`, `secret/vikunja/oidc` |
| LiteLLM | generic SSO, `litellm_role` claim | `homelab-admins` → `proxy_admin` | `secret/litellm/oidc` |
| De Vloer | public client, PKCE | `homelab-admins` → admin | none |
| Cloudflare Access | Authentik as IdP | none | `secret/cloudflare/access-oidc` |
| SearXNG public | gateway basic auth | n/a | `secret/searxng/basic-auth` |
| Longhorn, flux-ui, Hubble, VictoriaLogs, Alertmanager, policy-reporter, drawio, excalidraw, kroki, k8s-mcp, mcp-grafana | **none**, LAN only | — | — |
| Kubernetes API | Talos admin certificate, `system:masters` | — | `./kubeconfig` |
