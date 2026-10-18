# The access plane

How who-may-do-what is reconciled into Authentik, OpenBao and the Kubernetes API, and how to
operate the thing that does it. Decisions: [ADR-0058](../adr/adr-0058-access-plane-one-module-one-model.md);
design: [RFC: The access plane](../rfc/rfc-access-plane.md).

## Glossary

| Term | Meaning here |
| --- | --- |
| Model | Four YAML files under `kubernetes/apps/security/access-plane/model/`: capabilities, roles, projects, people. The only place a person exists. |
| Module | The OpenTofu code under `kubernetes/apps/security/access-plane/tofu/`. Reads the model, declares what each system must contain. |
| tofu-controller | A Flux controller in `flux-system`. For each `Terraform` object it starts a runner pod, plans, and applies. |
| Terraform object | A Kubernetes resource (`infra.contrib.fluxcd.io/v1alpha2`) naming a module path in the Git source. There are two: `access-broker` and `access-kubernetes`, both in `security`. |
| Runner | The short-lived pod that runs `tofu`. ServiceAccount `access-plane-runner`. |
| Plan | What the module would change. Stored in a ConfigMap in human-readable form. |
| State | The controller's record of what it created, a Secret named `tfstate-default-<object>` in `security`. |

## What runs where

```
flux-system/tofu-controller   watches Terraform objects in every namespace
security/access-broker        module tofu/broker      providers: authentik, vault
security/access-kubernetes    module tofu/kubernetes  provider: kubernetes
security/access-plane-runner  ServiceAccount both runners use
```

The runner logs in to OpenBao through the `kubernetes` auth mount as role `access-plane`
(policy `access-plane.hcl` in the OpenBao bootstrap floor). It is handed no other credential.
The Authentik API token is read from `secret/authentik/app` for the duration of the run.

## Read the state of the plane

```sh
cd ~/projects/webgrip/homelab-cluster
mise exec -- kubectl -n security get terraform
mise exec -- kubectl -n security describe terraform access-broker | sed -n '/Conditions/,$p'
```

`Ready=True` with reason `ReconciliationSucceeded` and no `Drifted` condition is the healthy
state. A plan awaiting approval shows `Ready=Unknown` and a message naming the plan id.

## Read a plan

```sh
mise exec -- kubectl -n security get cm tfplan-default-access-broker -o jsonpath='{.data.tfplan}'
```

Read every line. The plan is the authorisation record for a change to a grant; if it creates,
changes or destroys something the commit did not intend, fix the model rather than approving.

## Approve a plan

Only three plans in the rollout are approved by a person (stages 2, 3 and 5 of the RFC). Set
`spec.approvePlan` to the plan id from the object's status, commit, push. After the apply
succeeds, set it to `auto` in the next commit. Never approve by `kubectl patch`: the next Flux
reconcile reverts it and the plan stays pending.

## Force a reconcile

```sh
mise exec -- kubectl -n security annotate terraform access-broker \
  reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite
```

## Suspend before working locally

There is one writer. Suspend the object first, run locally, resume after.

```sh
mise exec -- flux -n security suspend terraform access-broker
cd kubernetes/apps/security/access-plane/tofu/broker
mise exec -- tofu init -backend=false
mise exec -- tofu fmt -check -recursive
mise exec -- tofu validate
mise exec -- flux -n security resume terraform access-broker
```

A local `plan` needs the live systems and the state Secret; the module is written so that
`validate` needs neither. Prefer a plan produced by the controller.

## Symptom → cause

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Ready=False`, message mentions `dial tcp` to `openbao.security.svc` | OpenBao sealed or the `access-plane` role missing | `bao status`; check the `openbao-config` CronJob ran after the role landed |
| Runner pod pending forever | No worker node with room, or the image not yet in Harbor | `kubectl -n security describe pod -l app.kubernetes.io/name=tf-runner` |
| `Ready=False`, message `permission denied` on an OpenBao path | The policy does not cover a path the module now touches | Extend `access-plane.hcl` in the bootstrap floor; the CronJob rewrites it |
| Controller logs `connection refused` to the runner on port 30000 | Ingress policy missing in `security` | `access-plane-allow-controller-to-runner` NetworkPolicy must exist |
| Plan pending for hours | The object has no `approvePlan` | That is the cutover posture; read the plan, approve it in Git |
| `Drifted` condition | Someone changed a managed object by hand | Let the next reconcile revert it; find who in the Authentik or OpenBao audit log |

## What else the broker reconciles

| Thing | Where it comes from | What to look at |
| --- | --- | --- |
| Harbor project membership | every held grant whose capability projects into Harbor with a scope; one Authentik group and one Harbor OIDC group per registry project and role, `harbor-<project>-<role>`, added to the project with that role | Harbor, Administration, Groups; the project's Members tab; the group in Authentik |
| Identity notifications | two notification rules on the broker's own events, delivered to ntfy over a webhook transport: a password login through the unlisted flow pages as critical, a user created outside the roster as a warning | Authentik, Events, Notification Rules; the phone |
| The Harbor credential | pushed from the Secret Harbor generated into the vault at `harbor/admin`, read by the runner | `kubectl -n harbor get pushsecret harbor-admin` |

Neither Harbor membership nor a notification rule has a hand-edit path: change the model or
the module and let the plan land. A group with no members is normal; it exists so the
membership is real the day a developer joins.

## How long a login lasts

[ADR-0077](../adr/adr-0077-admins-prove-a-security-key-at-google-and-sessions-end-in-twelve-hours.md)
bounds how long one Google check carries through the estate:

| What | Lifetime | Where it is set |
| --- | --- | --- |
| Google web session for admins | 12 hours | Workspace console, see [Google OAuth clients](google-oauth-clients.md#1-confirm-the-workspace-posture) |
| Authentik session after a Google login | 12 hours | `webgrip-source-login` stage in `tofu/broker/google.tf` |
| Refresh tokens for Grafana, Forgejo, OpenBao, Harbor, LiteLLM, Longhorn, Omnigraph Review | 12 hours | `refresh_token_validity` in `tofu/broker/applications.tf` |
| Refresh tokens for every other application | 30 days | Authentik default |
| OpenBao token from an OIDC login | 8 hours, renewable to 12 | `vault_jwt_auth_backend_role.default` in `tofu/broker/openbao.tf` |

A person who is asked to sign in again every morning is seeing this, not a fault. If Google
stops asking for the security key, the Workspace setting has changed. Authentik cannot see the
factor, so nothing here alerts on it.

## The audit dashboard

Grafana, folder Security, "Access / Kubernetes API audit". It reads the audit store directly:
who called the API, what people wrote, every admin-certificate call with its source and client,
Secret reads, RBAC writes, impersonation, anonymous requests, and the service accounts. The
same store feeds the audit alerts in `victoria-metrics/app/rules/vmrule-audit.yaml`.
