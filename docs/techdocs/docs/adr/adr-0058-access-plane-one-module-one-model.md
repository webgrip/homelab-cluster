---
status: proposed
date: 2026-09-14
---

# The access plane is one OpenTofu module reconciled by tofu-controller, from a four-file model

Technical Story: [RFC: The access plane](../rfc/rfc-access-plane.md) D4–D6 and D8.

## Context and Problem Statement

Who may do what in this estate is decided in three systems that Kubernetes does not own:
Authentik (groups, sources, flows, OIDC clients), OpenBao (auth mounts, roles, policies,
identity groups) and the Kubernetes API's own RBAC. Today the first is twelve blueprints that
apply state and never withdraw it, the second is a shell script in a CronJob, and the third has
no human subjects at all.

The sibling estate's staging cluster built the full version of the alternative: a six-file
model validated by CUE, a 2,900-line Python renderer emitting nine generated artefacts, a bash
converger that PATCHed group membership every ten minutes, a membership ConfigMap, a metrics
exporter, five alerts and a dashboard. Three weeks later its ADR-0048 replaced the converger
with an OpenTofu module run by tofu-controller and deleted 3,900 lines. This estate has none of
the intermediate machinery yet, so the question is only which end state to build.

## Decision Drivers

* Withdrawing access is deleting the line that declares it, in every system, with no code that
  deletes.
* A change is shown as a plan before it is applied.
* No standing credential: the reconciler authenticates the way External Secrets already does.
* One place a person exists, and one mechanism that makes every system agree with it.
* As little of our own code as possible between the roster and the systems that enforce it.
* No comments in code, in any language, including HCL.

## Considered Options

* **One OpenTofu module (providers `authentik`, `vault`, `kubernetes`), two `Terraform` objects,
  run in-cluster by tofu-controller; the model as four YAML files with JSON Schema**
* A Python renderer plus CUE schema producing generated manifests and a converger CronJob
  (staging's first version)
* Crossplane compositions over provider-kubernetes and provider-terraform
* `tofu apply` from a Forgejo Actions job on `main`
* The model as Kubernetes custom resources with CEL validation

## Decision Outcome

Chosen option: **one OpenTofu module run by tofu-controller, from four YAML files**, because it
is the only option where the roster is read directly by the thing that enforces it, with
plan-before-apply and native deletion, and no generated file in between.

* **Model.** `kubernetes/apps/security/access-plane/model/`: `capabilities.yaml`, `roles.yaml`,
  `projects.yaml`, `people.yaml`, each under a JSON Schema 2020-12 file with closed objects.
  `check-jsonschema` runs in the `lint` job and the pre-commit hook; the editor validates
  through the `yaml-language-server` header. Cross-file rules and dates are one small validator
  in `scripts/`. A `configMapGenerator` ships the model in-cluster so it is readable with the
  break-glass certificate and no checkout.
* **Module.** `kubernetes/apps/security/access-plane/tofu/`, read by two `Terraform` objects
  from the same GitRepository Flux applies: `access-broker` (Authentik and OpenBao) and
  `access-kubernetes` (RBAC bindings only, so revocation on the API keeps working when the
  broker is down). The module `yamldecode`s the model; expiry is `timecmp` against
  `plantimestamp()`, so a lapsed grant is gone on the next interval with no edit.
* **Credentials.** The runner ServiceAccount logs in to OpenBao through the existing
  `kubernetes` auth mount as role `tofu`; the Authentik API token is an ephemeral read and never
  enters plan or state. The two providers that need OpenBao get nothing else.
* **State.** tofu-controller's default Kubernetes Secret backend in `security`, encrypted at
  rest by Talos like every other Secret that already holds these values. Loss is re-adoption
  through `import` blocks, not loss of access.
* **Adoption, not recreation.** Every object that exists today is imported by name or id; the
  first plan is approved by a person and must change nothing. Afterwards `approvePlan: auto`.
* **Intent lives in names and docs.** Staging's module is comment-heavy; this repository does
  not allow comments. Resource and local names carry the meaning; the RFC and the runbook carry
  the reasoning.
* **The matrix is a view.** `escalates_to` edges stay in the capability catalogue; the closure
  and the access matrix are a build-time macro in `docs/techdocs/main.py`, never a committed
  file.

### Consequences

* Good, because about 3,000 lines of renderer, schema and converger are never written, and the
  remaining code is HCL a platform engineer reads without knowing this repository's conventions.
* Good, because every grant change is a plan someone can read, and deleting a resource deletes
  the object.
* Good, because CUE leaves the toolchain; JSON Schema is validated in the editor, in CI and in
  the hook with tools already pinned or one `pipx` line away.
* Bad, because there is a controller to run and a state Secret to keep. tofu-controller is
  community-maintained under `flux-iac` (v0.16.5, 2026-08-06, monthly patches). The module is
  the investment and runs unchanged from a CI job if the controller has to go.
* Bad, because a provider destroys only what it manages. A group created by hand in Authentik
  survives every apply. The quarterly review lists live objects against the module.
* Bad, because the Google client secret and each OIDC client secret land in state, a third copy
  of values already held by Authentik and OpenBao. Recorded; state encryption with a transit
  key is the revisit.
* Bad, because the runner needs egress to the OpenTofu registry to fetch providers, which is a
  NetworkPolicy and an image-qualification exception until providers are baked into a runner
  image.

### Confirmation

1. `kubectl -n security get terraform` shows `access-broker` and `access-kubernetes` `Ready`,
   with no drift, and a forced reconcile plans no changes.
2. Removing a dated grant from `people.yaml` removes the binding and the group membership on
   the next reconcile with no other edit; a grant whose `until` has passed is gone after the
   next interval with no edit at all.
3. `check-jsonschema` fails the `lint` job on a misspelled field; the validator fails it on an
   unknown capability and on a review date older than a year. Both were made to fail once and
   pass once.
4. `kubectl -n security get cm access-plane-model -o yaml` shows the four files.

## Pros and Cons of the Options

### One OpenTofu module, tofu-controller

* Good, because it is Flux-shaped: a source, a path, an interval, deletion on removal.
* Good, because the roster is read directly; there is nothing to render and nothing to drift.
* Bad, because it is a controller, a runner image and a state file.

### Python renderer, CUE schema, converger CronJob

* Good, because it needs nothing new in the cluster.
* Bad, because every part of it is a partial reimplementation of a provider, and the estate
  that built it has already replaced it.

### Crossplane

* Good, because it is CNCF-graduated and Kubernetes-native.
* Bad, because no Authentik provider exists, so the Authentik half would be provider-terraform
  wrapping the same module: one more layer, same HCL.

### `tofu apply` from a Forgejo Actions job

* Good, because it is the dumbest possible runner.
* Bad, because a job needs a credential to OpenBao and reconciles only when a pipeline runs;
  revocation would wait for a push. It remains the fallback if the controller goes.

### The model as custom resources with CEL

* Good, because `kubectl` validates on admission and the objects are in-cluster by nature.
* Bad, because a CRD schema cannot express cross-file joins any better than JSON Schema, the
  files would still need `yamldecode` on the module side, and a CRD is a third representation
  of the same four files.

## More Information

* [RFC: The access plane](../rfc/rfc-access-plane.md) · [ADR-0057](adr-0057-google-only-login-closed-enrolment.md) ·
  [ADR-0059](adr-0059-per-user-kubernetes-identity-via-google.md) ·
  [ADR-0055](adr-0055-one-secrets-model-six-levels.md) (the secrets model the runner's
  credential follows)
* Sibling: code14 staging-cluster ADR-0028 and ADR-0048, RFC-0012, RFC-0017, RFC-0018.
* [tofu-controller](https://github.com/flux-iac/tofu-controller) ·
  [goauthentik/authentik provider](https://registry.terraform.io/providers/goauthentik/authentik)
  · [hashicorp/vault provider](https://registry.terraform.io/providers/hashicorp/vault)
* 2026-09-14 — proposed; lands across stages 1, 2 and 5 of the RFC rollout.
