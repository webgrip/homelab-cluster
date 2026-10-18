---
status: accepted
date: 2026-10-18
decision-makers: Ryan Grippeling
---

# pods/exec, cluster-wide Secret reads, seccomp opt-outs and default-token opt-ins are denied; Secrets in env vars stay Audit

## Context and Problem Statement

Five controls added after the 2026-08-06 Kubescape baseline only reported:

* `restrict-pod-exec-verbs` and `restrict-secret-read-verbs` (ValidatingPolicies on Roles and
  ClusterRoles),
* `disallow-secrets-from-env-vars` (ValidatingPolicy on Pods and their controllers),
* `seccomp-default-mutate` and `sa-token-optout-mutate` (ClusterPolicies that *mutate*: they set
  `RuntimeDefault` and `automountServiceAccountToken: false` when nothing is declared, and have no
  Audit or Enforce mode to promote; they never refuse an explicit opt-out).

Which of these should refuse a request, and what does each refusal need first, so that the cluster
running Ploeg and Unfold stops at admission instead of in a report?

PolicyReports re-read on 2026-10-18 after Ploeg rc.31 and Unfold rc.91 went live, and a
`kyverno apply` sweep over a live dump of all 108 Roles and 171 ClusterRoles (PolicyReports do not
cover RBAC kinds reliably, per [ADR-0032](adr-0032-kyverno-enforce-promotion-policy.md)'s RFC):

| Control | Live failures | What they are |
| --- | --- | --- |
| `restrict-pod-exec-verbs` | 3 | `cloudnative-pg` operator, `human-operator`, `human-operator-actions` |
| `restrict-secret-read-verbs` | 33 | 27 operators that watch Secrets, 6 false positives |
| `disallow-secrets-from-env-vars` | 212 | 18 namespaces, including the `ploeg`, `unfold` and `ploeg-mcp` Deployments, Renovate jobs and the Forgejo provisioners |
| seccomp (all new Pods outside `forgejo`, `kube-system`, `longhorn-system`) | 0 | no running Pod or controller template declares `Unconfined` |
| default ServiceAccount token | 0 | no default or listed data-plane ServiceAccount, and no Pod on the default ServiceAccount, sets the token back on |

The 6 false positives were a rule bug: `resources: ["*"]` was counted as Secret access in any API
group, so `human-reader`, `human-reader-custom-resources`, `human-operator` (custom resources only),
`flux-view-flux-system`, `k8s-gateway` (Gateway API) and `sloth` failed without being able to read
a single Secret.

## Decision Drivers

* Never refuse something that runs today without fixing it or recording a reviewed exception.
* A refusal should close a real path to a credential or a shell, not restate a convention.
* Exceptions go through `exception-governance` (owner label, description, exact names).
* Every Deny policy gets a CLI test with a passing and a failing case.

## Considered Options

* Deny four controls with exact-name exceptions, fix the Secret-read rule first, keep env-var
  Secrets in Audit
* Deny all five, with exceptions for every current env-var Secret consumer
* Deny all five and rewrite the 212 env-var consumers to `envFrom` or files first
* Keep all five reporting

## Decision Outcome

Chosen option: "Deny four controls with exact-name exceptions, fix the Secret-read rule first, keep
env-var Secrets in Audit", because those four refuse real escalation paths with zero unexplained
breakage, while the fifth would cost 212 changes for no reduction in exposure.

1. **`restrict-pod-exec-verbs` denies.** Moved with the next control to
   [`rbac-exec-secret-read-enforce.yaml`](../../../../kubernetes/apps/kyverno/policies/app/rbac-exec-secret-read-enforce.yaml).
   [`exception-rbac-pod-exec-cel`](../../../../kubernetes/apps/kyverno/exceptions/app/exception-rbac-pod-exec-cel.yaml)
   waives exactly three ClusterRoles: the CloudNativePG operator's, and the access plane's
   `human-operator` with the `human-operator-actions` role it aggregates (the break-glass path of
   [ADR-0059](adr-0059-per-user-kubernetes-identity-via-google.md)). The existing CNPG drill and
   Unfold verifier exceptions keep covering their Roles.
2. **`restrict-secret-read-verbs` denies, after the rule fix.** A wildcard resource now counts only
   in the core API group (`""` or `*`), where Secrets live.
   [`exception-rbac-secret-read-cel`](../../../../kubernetes/apps/kyverno/exceptions/app/exception-rbac-secret-read-cel.yaml)
   waives the 27 operator ClusterRoles by exact name: Alloy, cert-manager, Cilium operator,
   CloudNativePG and its barman plugin, Flux (including the Flux Operator's unbound web UI roles
   `flux-web-user` and `flux-web-admin`), Envoy Gateway, External Secrets, grafana-operator, KEDA,
   kube-state-metrics, Longhorn, Reloader, renovate-operator, tofu-controller and the
   VictoriaMetrics operator. A new operator that lists Secrets is refused until someone adds it.
3. **seccomp opt-outs are denied.**
   [`workload-seccomp-enforce`](../../../../kubernetes/apps/kyverno/policies/app/workload-seccomp-enforce.yaml)
   refuses a new Pod whose containers run `Unconfined` or without a profile, in the same scope as
   `seccomp-default-mutate` (Pods with a privileged container, and the `forgejo`, `kube-system` and
   `longhorn-system` namespaces, are left alone). The mutation stays: it supplies the default, the
   new policy refuses opting out of it.
4. **Default-token opt-ins are denied.**
   [`sa-token-optout-enforce`](../../../../kubernetes/apps/kyverno/policies/app/sa-token-optout-enforce.yaml)
   refuses a `default` ServiceAccount, or one of the named data-plane ServiceAccounts the mutation
   covers, that declares `automountServiceAccountToken: true`, and a new Pod on the default
   ServiceAccount that asks for its token. The bootstrap namespaces the mutation skips are skipped.
5. **`disallow-secrets-from-env-vars` stays Audit.** An `env[].valueFrom.secretKeyRef` value is
   exposed exactly where an `envFrom.secretRef` value is: in the process environment, `/proc`,
   and crash dumps. `kubectl describe` shows the reference, not the value, for both. The estate's
   own convention (and Unfold's chart, by design) uses both forms, the policy deliberately allows
   `envFrom`, and denying one form would force 212 changes across 18 namespaces without removing
   a single exposure. The report stays as an inventory of where Secret values sit in process
   environments, for the file-mount work that would actually reduce it.

Promotion followed [ADR-0032](adr-0032-kyverno-enforce-promotion-policy.md): sweep, test, then flip.
It lands as one pull request after the ADR-0073 one, so the exceptions arrive with their policies.

### Consequences

* Good, because a new Role or ClusterRole granting a shell into Pods, or bulk Secret reads, is now
  refused at admission unless it is on a reviewed list.
* Good, because the Secret-read report stops showing six roles that cannot read Secrets, so its
  count means something.
* Good, because the two mutations become guarantees: a workload can no longer quietly opt back out.
* Bad, because a chart upgrade that renames an excepted ClusterRole, or a new operator that watches
  Secrets, fails its HelmRelease until the exception is updated. That is the review step, but it
  will surface as a failed reconcile.
* Bad, because policies apply before exceptions (`kyverno-exceptions` depends on
  `kyverno-policies`). For the seconds between the two reconciles, an update to an excepted
  ClusterRole would be refused. Flux retries on its next interval.
* Bad, because Secrets in environment variables remain allowed.

### Confirmation

* Live sweep (2026-10-18) with the new policies and all exceptions: `restrict-pod-exec-verbs`
  187 pass, 0 fail; `restrict-secret-read-verbs` 72 pass, 0 fail; without the exceptions, 44 fail.
  `workload-seccomp-enforce` and `sa-token-optout-enforce` over every live Pod and ServiceAccount:
  713 pass, 0 fail.
* [`tests/cli/admission-deny-promotions`](../../../../kubernetes/apps/kyverno/tests/cli/admission-deny-promotions/kyverno-test.yaml)
  asserts pass, fail and skip for each control, including the custom-API-group wildcard (pass) and
  the exceptions (skip). Removing the API-group fix or the exec exception turns the suite red
  (210 passed, 2 failed).
* After the merge, PolicyReports show 0 `fail` for the four Deny policies, and
  `disallow-secrets-from-env-vars` keeps reporting.

## Pros and Cons of the Options

### Deny four with exceptions, fix the rule, keep env-var Secrets in Audit

* Good, because every refusal is tested and every current holder is reviewed by name.
* Bad, because the exception list for Secret reads is long and must follow chart renames.

### Deny all five, excepting every env-var consumer

* Bad, because an exception list of 212 workloads waives the policy rather than enforcing it.

### Deny all five after rewriting the env-var consumers

* Bad, because the rewrite moves values from one environment form to another and reduces no
  exposure; the effort belongs in file mounts, if anywhere.

### Keep all five reporting

* Bad, because a shell or Secret-reading role can still be created without anyone deciding to.

## More Information

* Technical story: [RFC: Kyverno audit→enforce hardening](../rfc/rfc-kyverno-audit-enforce-hardening.md)
  (waves 16–19).
* Related: [ADR-0073](adr-0073-image-admission-signatures-enforced.md) (image admission, merged
  first), [ADR-0059](adr-0059-per-user-kubernetes-identity-via-google.md) (human operator role).
* Follow-up worth doing: the Flux Operator chart's `flux-web-user` and `flux-web-admin` roles grant
  read on every resource and are bound to nothing; drop them in chart values if the chart allows it,
  then remove them from the exception.
* 2026-10-18: accepted by Ryan Grippeling.
