---
status: accepted
date: 2026-09-14
---

# Google Workspace is the only interactive login; enrolment is closed; the password door stays, unlisted

Technical Story: [RFC: The access plane](../rfc/rfc-access-plane.md) D1–D3. Closes the
"adopt Authentik" and "blueprint-as-code" candidate records of the
[Identity & SSO RFC](../rfc/rfc-identity-sso.md) by recording what the broker is *for*.

## Context and Problem Statement

Authentik is the estate's OIDC broker for twelve applications, and its only login is a
username-and-password form with TOTP or WebAuthn behind it (`homelab-authentication`). Every
person who uses this estate already has a Google Workspace account on `webgrip.nl`, with
2-step verification enforced there. So the Authentik password is a second credential nobody
rotates, the Authentik authenticator is a second MFA enrolment nobody keeps current, and the
login page trains the one habit credential phishing depends on: typing a company password into
a form that is not the company's identity provider.

The one human account was created by hand in the admin UI and placed in `homelab-users` and
`homelab-mfa` by hand. Nothing in Git says it exists. Removing a person means remembering to
open the admin UI.

The staging cluster of the sibling estate solved the same problem in ADR-0027 with a
Google-only flow and open enrolment gated on Google's Internal consent screen. Open enrolment is
right where the Workspace directory *is* the roster. Here the roster is smaller than the
directory could be, and may one day hold a client whose Google account is not on the company
domain.

## Decision Drivers

* One credential per person, with MFA enforced and audited in exactly one place.
* A login page that offers only the doors its users can walk through.
* Recovery that does not depend on the component most likely to have failed.
* A person exists in Git or does not exist at all; removal is deleting a line.
* The control must survive somebody clicking in the admin UI.

## Considered Options

* **Google source, a Google-only flow, closed enrolment from a roster, the password flow kept
  unlisted as break-glass**
* Google source with open enrolment gated on an Internal consent screen (staging's ADR-0027)
* Keycloak as the broker, with the same Google federation
* Keep Authentik passwords and add Google as a second button

## Decision Outcome

Chosen option: **Google source, Google-only flow, closed enrolment, unlisted password
break-glass**, because it gives every surface one door, makes the roster in Git the allow-list,
and leaves the recovery path exactly where it already works.

* A new flow `webgrip-authentication` carries one identification stage with `user_fields: []`
  and the Google source as its only option. The default brand points at it. Every
  unauthenticated entry point follows the brand, so there is no per-application setting.
* `homelab-authentication` keeps its password and MFA stages and is linked from nowhere. It is
  reachable by URL for `akadmin`, whose password is in OpenBao. A broken change to the new flow
  leaves the brand on the old one; a rotated Google client secret leaves the break-glass URL
  working.
* Every user is created from `people.yaml` by the access-plane module (ADR-0058) before they
  sign in. The Google source uses `email_link` matching and has **no enrollment flow**. A Google
  account that is not in the roster fails at Authentik and never obtains a session.
* MFA is Google's. The `homelab-mfa` group, its policy and its twelve bindings are deleted.
* The consent screen is **Internal** today, so only `webgrip.nl` accounts reach the source at
  all. Switching it to External is the one change needed to roster a client with a personal
  Google account, and is a separate decision.

### Consequences

* Good, because the page every person sees has one control, and no form exists into which a
  Google password can be typed.
* Good, because joining is one YAML entry and leaving is deleting it; the module removes the
  user and every membership on the next reconcile.
* Good, because recovery is unchanged: the same URL, the same account, the same OpenBao path.
* Good, because MFA has one owner and one audit trail, in the Workspace admin console.
* Bad, because password login still exists at a guessable URL on the LAN. Accepted: Authentik
  is on `envoy-internal` only, and the alternative removes the recovery path.
* Bad, because a person must exist in Git before they can sign in, so the first login of a new
  collaborator waits on a merge. That is the point.
* Bad, because the login flow now depends on Google being reachable from the browser. When it
  is not, the break-glass URL is the way in, and the runbook says so.

### Confirmation

1. `GET /api/v3/core/brands/` shows `flow_authentication` naming `webgrip-authentication`;
   `GET /api/v3/stages/identification/?name=webgrip-identification` shows `user_fields: []` and
   `password_stage: null`. Objects, never blueprint or plan status.
2. `https://authentik.${SECRET_DOMAIN}/` shows a single "Sign in with Google" control;
   `/if/flow/homelab-authentication/` still signs `akadmin` in.
3. A Workspace account absent from `people.yaml` is refused at Authentik after Google succeeds.
4. `GET /api/v3/core/groups/?name=homelab-mfa` returns no result.

## Pros and Cons of the Options

### Google-only flow, closed enrolment, unlisted break-glass

* Good, because the rollback is one field: point the brand back.
* Good, because the roster is the allow-list, independent of Google's consent-screen audience.
* Bad, because two flows and a brand pointer are more objects than one shipped default.

### Open enrolment gated on the Internal consent screen

* Good, because nobody has to be pre-created; the first login makes the account.
* Bad, because the allow-list is then "everyone in the Workspace", which is wider than the
  roster and cannot ever include a non-Workspace client.
* Bad, because it needs the shipped enrollment stage patched to write `internal` users.

### Keycloak as the broker

* Good, because it is the CNCF broker with the larger community.
* Bad, because it changes nothing about this decision: both brokers federate Google, emit a
  groups claim and have an official OpenTofu provider, and Keycloak costs a JVM and a migration
  of twelve clients. Recorded as a revisit trigger in the RFC, not chosen.

### Keep passwords, add Google as a second button

* Good, because it is one blueprint entry.
* Bad, because it leaves the wrong door on the most-linked page in the estate, which is the
  failure staging reported as user confusion within a day.

## More Information

* [RFC: The access plane](../rfc/rfc-access-plane.md) · [ADR-0058](adr-0058-access-plane-one-module-one-model.md)
  (the module that creates the users and groups) · [ADR-0059](adr-0059-per-user-kubernetes-identity-via-google.md)
  (why the API server trusts Google directly, not this broker)
* Runbooks: [Google OAuth clients](../runbooks/google-oauth-clients.md) ·
  [Authentik OIDC login failures](../runbooks/authentik-oidc-login.md)
* 2026-09-14 — proposed.
* 2026-09-14 — accepted: the brand on the Authentik host points at `webgrip-authentication`, the flow offers Google and no password field, the break-glass flow still answers, Forgejo and Grafana redirect to the broker. Confirmation 3 (a Workspace account outside the roster is refused) awaits a second account to try it with.
