---
status: accepted
date: 2026-10-18
---

# Admins prove a security key at Google, and the estate re-checks Google every twelve hours

Technical Story: [RFC: The access plane](../rfc/rfc-access-plane.md) and
[RFC: Security hardening](../rfc/rfc-security-hardening.md). Builds on
[ADR-0057](adr-0057-google-only-login-closed-enrolment.md) (Google is the only login, and its MFA
is the only MFA) and [ADR-0059](adr-0059-per-user-kubernetes-identity-via-google.md) (the
Kubernetes API trusts Google directly). Decided by Ryan Grippeling on 2026-10-18 ("fix it all").

## Context and Problem Statement

Membership of `homelab-admins` makes a person an administrator of OpenBao, Forgejo, Grafana,
LiteLLM and Unfold. The access-plane roster grants `cluster-admin` on the Kubernetes API the same
way. Admins must use strong MFA, meaning a factor that phishing cannot relay, and the question is
where that requirement lives without undoing ADR-0057's "one credential, MFA in one place".

What exists on 2026-10-18:

* Every interactive login goes to Google through the `webgrip-authentication` flow. Workspace
  enforces 2-step verification for all users, but any method satisfies it, including SMS and
  codes that a phishing proxy can relay.
* Google's ID token carries no `amr` or `acr` claim, so neither Authentik nor the API server can
  see which second factor was used. An authorization policy in Authentik that "checks the
  upstream amr" has nothing to read.
* After the Google step, the Google source runs Authentik's shipped
  `default-source-authentication` flow. Its login stage sets no session length, so the Authentik
  session lasts as long as the browser keeps it.
* OAuth providers keep Authentik's default 30-day refresh tokens, so an application that
  refreshes (Grafana, the gateway-protected dashboards) keeps an admin signed in for a month
  without asking Google again.
* OpenBao's OIDC role sets no token TTL, so an admin token lives until the mount maximum
  (OpenBao's default is 32 days).

## Decision Drivers

* Phishing-resistant MFA for every admin login, on every surface, including `kubectl`.
* One MFA enrolment per person, at Google (ADR-0057).
* A stolen session or token must expire within a working day, not a month.
* Declarative where the estate can be declarative; the Workspace console is the exception.

## Considered Options

* Enforce security keys at Google for admins, and bound how long one Google check lasts in the
  estate (chosen)
* Add an Authentik WebAuthn stage for `homelab-admins`
* Check the upstream `amr` claim in an Authentik authorization policy
* Leave it at Workspace-wide 2-step verification

## Decision Outcome

Chosen option: "Enforce security keys at Google for admins, and bound how long one Google check
lasts", because Google is the one place that sees the factor. Restricting the method there covers
the broker and the Kubernetes API alike, and the estate's part is to go back to Google often
enough for that check to count.

At Google (Workspace console, applied by the owner; the runbook has the clicks):

* 2-step verification for the admin roster is restricted to **Only security key**: a hardware key
  or a passkey, both bound to the origin, so a relayed login fails. Backup codes stay for
  recovery, printed and offline. OpenBao is no place for them, because reaching OpenBao needs
  the Google login they recover.
* Google web session length for the admin roster is **12 hours**, so the Google step re-prompts
  for the key at least daily.

In the estate (OpenTofu, `kubernetes/apps/security/access-plane/tofu/broker/`):

* The Google source runs a new flow, `webgrip-source-authentication`. Its login stage sets
  `session_duration = hours=12`, and an `ak_is_sso_flow` policy keeps the flow from being used
  outside a source login. The shipped `default-source-authentication` is left alone.
* The OAuth providers of the admin-granting applications (Grafana, Forgejo, OpenBao, Harbor,
  LiteLLM, Longhorn, Omnigraph Review) issue refresh tokens valid for 12 hours instead of 30 days.
  The rest keep the default.
* OpenBao's OIDC role issues tokens with an 8-hour TTL and a 12-hour maximum.
* Unchanged: one MFA enrolment per person, at Google. No Authentik authenticator for anyone but
  the break-glass `akadmin`, whose flow keeps its own factors.

### Consequences

* Good, because a phished Google password plus a relayed code no longer signs an admin in,
  anywhere: the broker and `kubectl` both stop at Google.
* Good, because the most a stolen Authentik session, refresh token or OpenBao token buys is half a
  day.
* Good, because ADR-0057 holds: one credential, MFA enforced and audited in one place.
* Bad, because the Google half lives in a console and not in Git. The runbook records the exact
  setting, and the confirmation below is a manual check until Workspace settings are managed as
  code.
* Bad, because the estate cannot verify the factor per login; it trusts the Workspace policy.
  Disabling that policy in the console would leave every check here green.
* Bad, because admins sign in again at least daily, and a lost key means recovery through backup
  codes or a second enrolled key. Enrol two keys.
* Bad, because `ploeg-mcp` keeps 30-day refresh tokens, so agent clients do not re-prompt daily.
  Its tokens are read-mostly, and ADR-0068's token work is where that lifetime is decided.

### Confirmation

1. Workspace: Security, Authentication, 2-Step Verification, for the admin roster, shows
   enforcement **On** and methods **Only security key**. Reporting, User reports, Security, shows
   at least one security key or passkey for every person in `homelab-admins`.
2. Workspace: Security, Access and data control, Google session control, shows 12 hours for the
   admin roster's organisational unit.
3. `GET /api/v3/sources/oauth/google/` names the `webgrip-source-authentication` flow, and
   `GET /api/v3/stages/user_login/?name=webgrip-source-login` shows `session_duration: hours=12`.
4. `GET /api/v3/providers/oauth2/?name=grafana-oidc` shows `refresh_token_validity: hours=12`.
5. `bao read auth/oidc/role/default` shows `token_ttl 28800` and `token_max_ttl 43200`.
6. A sign-in from a browser whose Google session has expired asks for the security key.

## Pros and Cons of the Options

### Authentik WebAuthn stage for `homelab-admins`

* Good, because the broker itself would hold a phishing-resistant factor that it can verify.
* Bad, because it is the second MFA enrolment ADR-0057 removed, with its own recovery story.
* Bad, because `kubectl` goes to Google directly (ADR-0059) and would not pass through it.

### Check the upstream `amr` claim

* Bad, because Google does not send one. The policy would have nothing to check.

### Workspace-wide 2-step verification only

* Good, because nothing changes.
* Bad, because SMS and authenticator codes are relayed by off-the-shelf phishing kits, and
  admin sessions last weeks.

## More Information

* Runbook: [Google OAuth clients](../runbooks/google-oauth-clients.md#1-confirm-the-workspace-posture)
  holds the Workspace steps; [The access plane](../runbooks/access-plane.md) the lifetimes.
* Revisit when Google emits `amr` in its ID tokens, or when Workspace settings can be managed as
  code in this estate.
* 2026-10-18 — accepted.
