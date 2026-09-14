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
