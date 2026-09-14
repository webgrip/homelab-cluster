# Google OAuth clients for the access plane

Who this is for: whoever holds Google Workspace super-admin for `webgrip.nl` and can create a
Google Cloud project. About twenty minutes, once. Decisions:
[ADR-0057](../adr/adr-0057-google-only-login-closed-enrolment.md) (the broker signs people in
with Google) and [ADR-0059](../adr/adr-0059-per-user-kubernetes-identity-via-google.md) (the
Kubernetes API verifies Google tokens itself).

## Glossary

| Term | Meaning here |
| --- | --- |
| OAuth client | A record in Google Cloud that lets one application ask Google to sign a person in. It has a public client id and a client secret. |
| Consent screen | What Google shows the person on first sign-in. Its **audience** decides who may sign in at all. |
| Internal audience | Only accounts on the Workspace domain. No Google review, no "unverified app" warning. |
| Redirect URI | Where Google sends the browser after sign-in. Must match byte for byte, trailing slash included. |
| Broker | Authentik, at `authentik.<domain>`. It is the only thing that talks to Google for web logins. |

Two clients, never one. A browser session for a dashboard must not be replayable against the
cluster's API, so the API server gets its own client with only `localhost` redirect URIs.

## 1. Confirm the Workspace posture

1. Open `admin.google.com` → Security → Authentication → 2-Step Verification.
2. Enforcement must be **On** for all users. If it is not, turn it on. After this change Google's
   MFA is the only MFA in the estate; Authentik's own authenticators are retired.
3. Billing → Subscriptions: note the edition. Nothing here needs more than Business Starter.

## 2. Create the project

1. Open `console.cloud.google.com` signed in as a `webgrip.nl` account.
2. Create a project named `webgrip-identity`. It will hold only these OAuth clients; nothing
   else goes in it, so its IAM can stay small.
3. Left menu → **Google Auth platform** (older consoles: APIs & Services → OAuth consent screen).

## 3. Consent screen

1. Branding: app name `WebGrip`, support email `ryan@webgrip.nl`, developer contact the same.
2. Audience: **Internal**. This restricts sign-in to `webgrip.nl` accounts and avoids Google's
   verification process entirely. Switching to External is the change that would allow a client
   with a personal Google account; it is a separate decision.
3. Data access (scopes): leave empty. `openid`, `email` and `profile` are requested at runtime
   and are non-sensitive.

## 4. Client 1: the broker

1. Clients → Create client → type **Web application**, name `WebGrip broker (Authentik)`.
2. Authorized JavaScript origins: leave empty.
3. Authorized redirect URIs, exactly one, with the trailing slash:

   ```text
   https://authentik.webgrip.dev/source/oauth/callback/google/
   ```

4. Create. Copy the client id and the client secret.

## 5. Client 2: the Kubernetes API

1. Clients → Create client → type **Web application**, name `WebGrip Kubernetes API`.
2. Authorized redirect URIs, both, plain `http`, no trailing slash:

   ```text
   http://localhost:8000
   http://localhost:18000
   ```

   These are where `kubectl oidc-login` listens on the workstation. Nothing else may be added.
3. Create. Copy the client id and the client secret. This secret ships to every operator's
   workstation by design; Google does not treat it as confidential for a loopback client. The
   protection is the Google account, its MFA, and RBAC.

## 6. Put both in the vault

Vault level (ADR-0055): a person writes the provided values once, over OIDC. Paste the two
secrets when prompted; nothing is echoed.

```sh
cd ~/projects/webgrip/homelab-cluster
just bao-login

read -r -p 'Broker client id: ' BROKER_ID
read -r -s -p 'Broker client secret: ' BROKER_SECRET; echo
mise exec -- bao kv put secret/authentik/google-oauth \
  client_id="$BROKER_ID" client_secret="$BROKER_SECRET"

read -r -p 'Kubernetes API client id: ' KUBE_ID
read -r -s -p 'Kubernetes API client secret: ' KUBE_SECRET; echo
mise exec -- bao kv put secret/security/kubernetes-oidc \
  client_id="$KUBE_ID" client_secret="$KUBE_SECRET"

unset BROKER_SECRET KUBE_SECRET
mise exec -- bao kv get -field=client_id secret/security/kubernetes-oidc
```

The last line prints the Kubernetes client id. It is a public identifier and is committed into
`talos/patches/controller/cluster.yaml` as `oidc-client-id`; hand it to whoever is landing stage
4 of the RFC.

## 7. Verify

| Check | Expect |
| --- | --- |
| `bao kv get secret/authentik/google-oauth` | keys `client_id`, `client_secret` |
| `bao kv get secret/security/kubernetes-oidc` | keys `client_id`, `client_secret` |
| Consent screen → Audience | Internal |
| Client 1 redirect URIs | exactly one, ending in `/google/` |
| Client 2 redirect URIs | exactly `http://localhost:8000` and `http://localhost:18000` |

## When something goes wrong later

| Symptom | Cause | Fix |
| --- | --- | --- |
| Google shows `redirect_uri_mismatch` | The URI Authentik sent is not registered byte for byte | Compare the `redirect_uri` query parameter in the browser URL against the client; the trailing slash is the usual difference |
| Google shows `invalid_client` | Wrong client id or secret in OpenBao | Re-run step 6 for that client; the access-plane module picks it up on the next reconcile |
| Sign-in works, Authentik says the source is not configured for enrolment | The account is not in `people.yaml` | That is the allow-list working; add the person and merge |
| `kubectl` opens a browser, then `Unauthorized` | The token lacks `email`, or the API server's `oidc-client-id` does not match client 2 | `scripts/kube-oidc-setup.sh` sets the scopes; compare the id in the Talos patch with the console |
| A `webgrip.nl` account is refused by the API server | `oidc-required-claim: hd=webgrip.nl` and the account is on a secondary domain | Multi-domain Workspaces put the user's own domain in `hd`; add the domain or move the account |
