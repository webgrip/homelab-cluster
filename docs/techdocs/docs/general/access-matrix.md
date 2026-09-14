# Access matrix

Who can do what, on every plane this cluster runs, computed at docs build time from the
access-plane model under `kubernetes/apps/security/access-plane/model/`. Nothing on this page
is a place to make a change: grants are edited in the model and reconciled by the access plane
([ADR-0058](../adr/adr-0058-access-plane-one-module-one-model.md)).

Two things are shown separately, and the distinction is the point of the page:

- **Declared**: what somebody was given, through a role or a dated grant.
- **Reachable**: what they can obtain without anybody granting it, following the escalation
  edges the capability catalogue declares. A platform engineer holds no Secret access and can
  read every Secret through `pods/exec`. Both facts are true; only one was a decision.

{{ access_matrix() }}
