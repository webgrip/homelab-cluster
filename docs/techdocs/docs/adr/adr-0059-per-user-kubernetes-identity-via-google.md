---
status: accepted
date: 2026-09-14
---

# Humans reach the Kubernetes API as themselves, via Google directly

Technical Story: [RFC: The access plane](../rfc/rfc-access-plane.md) D7. Reopens the item the
[Identity & SSO RFC](../rfc/rfc-identity-sso.md) placed out of scope as "single-operator today".

## Context and Problem Statement

Every call to the Kubernetes API from a human, and from every Claude Code session on the
owner's machine, carries the Talos-issued admin certificate: `CN=admin, O=system:masters`. That
group short-circuits the authorizer before RBAC is consulted, the credential has no revocation
short of rotating the cluster CA, and the audit trail, if there were one, would attribute
everything to `admin`. There is no audit policy on the API server.

`kubernetes/` contains no RoleBinding or ClusterRoleBinding with a `User` or `Group` subject.
Human access is a property of who holds a file.

## Decision Drivers

* A person is a person on the API: revocable, attributable, expiring.
* Authentication must not depend on a component that runs on the cluster it protects.
* No reboot to turn it on or off; blast radius of the first change is zero.
* The break-glass credential survives, becomes deliberate to use, and is evidenced.
* One place a person exists (ADR-0058).

## Considered Options

* **OIDC flags on the API server pointing at Google directly; per-user bindings from the model;
  `kubectl oidc-login`**
* OIDC via the Authentik broker, binding groups
* Pinniped Supervisor and Concierge
* Per-person client certificates

## Decision Outcome

Chosen option: **Google directly, per-user bindings, `kubectl oidc-login`**, because Google is
the one identity provider that does not run on this cluster, and Talos applies `.cluster` flags
without a node reboot.

* `talos/patches/controller/cluster.yaml` gains `oidc-issuer-url: https://accounts.google.com`,
  `oidc-client-id` (a dedicated OAuth client, public identifier), `oidc-username-claim: email`,
  `oidc-username-prefix: "oidc:"`, `oidc-required-claim: hd=webgrip.nl`. No groups claim:
  Google emits none in ID tokens at any edition.
* The prefix is load-bearing: every legitimate principal is then `system:` or `oidc:`, so the
  break-glass alert is an exact negative match.
* Three static ClusterRoles land as plain manifests: `human-reader` (aggregates the built-in
  `view` plus cluster-scoped reads; no Secrets, no RBAC, no exec), `human-operator` (a strict
  superset adding restart, scale, exec, port-forward, Flux reconcile, cordon) and the built-in
  `cluster-admin`. Bindings are rendered from the model by the access-plane module.
* `kubectl oidc-login` (int128/kubelogin) is pinned in `.mise.toml`;
  `scripts/kube-oidc-setup.sh` writes the exec credential and switches the default context.
* The admin kubeconfig moves out of the working file into one that needs an explicit
  `--kubeconfig`. An API-server audit policy on the control planes ships through the existing
  Alloy agent into VictoriaLogs; `KubernetesBreakGlassCertificateUsed` fires on any authenticated
  username matching neither `^system:` nor `^oidc:`.
* A Kyverno policy, Audit first then Enforce, denies any binding with a `User` or `Group`
  subject that lacks the module's provenance label.
* Kubernetes' structured `AuthenticationConfiguration` is not used: Talos has no field for it
  and the file would need `machine.files`, which is boot-only.

### Consequences

* Good, because access is a dated line in `people.yaml`, revoked by deletion, and every call
  names the person.
* Good, because the first change authenticates everyone and authorizes nobody: the flags land
  with empty subject lists, and bindings follow in their own commit.
* Good, because an Authentik outage cannot lock the operator out of the cluster Authentik runs
  on.
* Bad, because Google emits no groups, so bindings name users and grow with the roster. The
  module renders them; nobody types them.
* Bad, because the admin certificate is unrevokable and stays. The alert is the control, and
  the record is not complete until the alert has fired on a test call.
* Bad, because the API-server change is applied by a human, one control plane at a time, and
  the flags are inert until then.
* Bad, because an audit pipeline is new here: a policy on Talos, a hostPath read by Alloy, a
  stream in VictoriaLogs. It is the price of "evidenced".

### Confirmation

1. `kubectl auth whoami` from the working kubeconfig returns `oidc:ryan@webgrip.nl` with groups
   `[system:authenticated]`; `kubectl auth can-i --list` matches the model.
2. One call with `--kubeconfig ~/.kube/homelab-break-glass.yaml` fires
   `KubernetesBreakGlassCertificateUsed` within ten minutes, the rule evaluating every five, and the alert stays quiet over a day of
   normal use.
3. `kubectl get clusterrolebinding -l access-plane.webgrip.io/managed=true` lists exactly the
   bindings the model implies; the Kyverno rule denies a hand-applied binding with a `User`
   subject and admits one from the module.
4. A token from a Google account outside `webgrip.nl` is rejected by the API server.

## Pros and Cons of the Options

### Google directly

* Good, because it is off-cluster, WebPKI-trusted, no CA file to distribute.
* Good, because flags apply without a reboot and can be removed the same way.
* Bad, because there is no groups claim, ever.

### Via the Authentik broker

* Good, because a groups claim would let bindings name groups.
* Bad, because the storage incident that takes Authentik down also takes down the credential
  needed to fix it. Staging recorded the same reasoning and deferred it identically.
* Bad, because the API server would need Authentik's certificate, which on Talos is a boot-only
  `machine.files` change.

### Pinniped

* Good, because it issues short-lived cluster credentials without touching the API server and
  spans clusters with one Supervisor.
* Bad, because it is two more components on the critical path for one human and one cluster.
  Revisit when a second cluster exists.

### Per-person client certificates

* Good, because it needs nothing new.
* Bad, because Kubernetes has no certificate revocation; it reproduces the flaw once per person.

## More Information

* [RFC: The access plane](../rfc/rfc-access-plane.md) · [ADR-0058](adr-0058-access-plane-one-module-one-model.md)
  · [ADR-0057](adr-0057-google-only-login-closed-enrolment.md)
* Runbooks: [Google OAuth clients](../runbooks/google-oauth-clients.md) ·
  [Kubeconfig setup](../general/kubeconfig-setup.md)
* Sibling: code14 staging-cluster ADR-0025, ADR-0033 and `runbooks/kubernetes-login.md`.
* 2026-09-14 — proposed; lands in stage 4 of the RFC rollout.
* 2026-09-15 — accepted. All three API servers carry the flags; `kubectl auth whoami` from the working kubeconfig is `oidc:ryan@webgrip.nl`; the admin credential lives in `~/.kube/homelab-break-glass.yaml`; `KubernetesBreakGlassCertificateUsed` fired at 05:40Z on the drain calls made with that credential and reached Alertmanager. Two things surfaced: the Alloy pipeline dropped every read, so a break-glass `get nodes` left no trace, and Talos itself updates nodes with the admin credential during an apply. Reads by anyone outside `system:` are kept now, and the rule excludes the Talos calls by source and user agent. Confirmation 3 waits for the Kyverno rule in Enforce; confirmation 4 has no account outside `webgrip.nl` to try, and rests on the `hd` claim being required.
