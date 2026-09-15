# Kubernetes login

How a person reaches the Kubernetes API as themselves, what each tier may do, and what the
admin certificate is still for. Decision: [ADR-0059](../adr/adr-0059-per-user-kubernetes-identity-via-google.md).

## Glossary

| Term | Meaning here |
| --- | --- |
| OIDC login | `kubectl` opens a browser, you sign in with Google, and the API server verifies Google's token itself. Your username on the API is `oidc:you@webgrip.nl`. |
| Tier | A ClusterRole the access plane binds you to: `human-reader`, `human-operator` or `cluster-admin`. Declared in `people.yaml`, never by hand. |
| Break-glass | The Talos-issued admin certificate. It bypasses RBAC and cannot be revoked. Kept for the day OIDC itself is broken, and alerted on every use. |
| kubelogin | The `kubectl oidc-login` plugin (int128), pinned in `.mise.toml`. |

## Set up your login, once per machine

```sh
cd ~/projects/webgrip/homelab-cluster
mise install
export BAO_ADDR="$(mise exec -- just bao-addr)"
mise exec -- bao login -method=oidc
KUBERNETES_OIDC_CLIENT_SECRET="$(mise exec -- bao kv get -field=client_secret secret/security/kubernetes-oidc)" \
  mise exec -- ./scripts/kube-oidc-setup.sh
mise exec -- kubectl auth whoami
```

Expect `Username: oidc:you@webgrip.nl` and `Groups: [system:authenticated]`. The script makes
`homelab-oidc` the default context in the repo's `kubeconfig`. `Forbidden` on everything is
normal until `people.yaml` grants you a tier; logging in grants nothing by itself.

The client secret is for a loopback OAuth client and ships to every operator by design; the
protection is your Google account, its 2-step verification, the `hd=webgrip.nl` claim the API
server requires, and RBAC.

## What each tier may do

| Tier | For | Notably cannot |
| --- | --- | --- |
| `human-reader` | Read anything except Secrets, in the namespaces your projects own | change anything; read Secrets; read RBAC |
| `human-operator` | Restart, scale, exec, port-forward, reconcile Flux, cordon, in the namespaces your projects own | read Secrets directly; change RBAC |
| `cluster-admin` | Everything, everywhere; a dated grant on a person, never on a role | |

`exec` is a real trust boundary: a shell in a pod reads whatever that pod's ServiceAccount and
mounted Secrets can. The reader tier's Secret exclusion does not survive an exec, which is why
`k8s-operate` carries that escalation edge in the model.

Check a subresource the right way:

```sh
kubectl auth can-i create pods --subresource=exec -n observability
```

## Move the admin certificate out of the way

After your OIDC context works, keep the break-glass credential in a file that takes a deliberate
`--kubeconfig`:

```sh
cd ~/projects/webgrip/homelab-cluster
mise exec -- kubectl config view --minify --flatten --context homelab > ~/.kube/homelab-break-glass.yaml
chmod 600 ~/.kube/homelab-break-glass.yaml
mise exec -- kubectl config delete-context homelab
mise exec -- kubectl config delete-user admin@kubernetes
mise exec -- kubectl config current-context
```

Expect `homelab-oidc`. Regenerating the kubeconfig with `talosctl kubeconfig` merges the admin
credential back in; check `current-context` afterwards and remove it again.

## Break-glass

Use it only when OIDC itself is broken: the API server rejects every token, Google is down, or
the OAuth client expired. Missing permissions are a change to `people.yaml`, not an emergency.

```sh
mise exec -- kubectl --kubeconfig ~/.kube/homelab-break-glass.yaml get nodes
```

Every call lands the `KubernetesBreakGlassCertificateUsed` alert, which is the control. Silence
it only with a dated Alertmanager silence, never by editing the rule. The API-server audit log
is on the control planes at `/var/log/audit/kube/kube-apiserver.log`, shipped by Alloy into the
`victorialogs-audit` instance with one year of retention.

## RBAC changed outside GitOps

`KubernetesRBACChangedOutsideGitOps` fires when anything but Flux, the access-plane runner, CNPG
or the aggregation controller writes an RBAC object. Read the audit event, delete the object if
Git does not declare it, or add the writer to the rule's allow-list if it is a legitimate new
controller.

## Anonymous request allowed

`KubernetesAnonymousRequestAllowed` fires when `system:anonymous` is allowed anything beyond the
health endpoints. List bindings whose subjects include `system:anonymous` or
`system:unauthenticated` and remove the grant.

## Symptom → cause

| Symptom | Cause | Fix |
| --- | --- | --- |
| Browser shows `redirect_uri_mismatch` | kubelogin's callback port is not registered on the Google client | Only `http://localhost:8000` and `http://localhost:18000` are allowed; stop whatever else holds the port |
| Browser login succeeds, `kubectl` says `Unauthorized` | Token lacks `email`, or the client id in the Talos patch differs from the client used | The setup script passes both scopes; compare `oidc-client-id` in `talos/patches/controller/cluster.yaml` with the console |
| `Unauthorized` for a `webgrip.nl` account on a secondary domain | `hd` carries the user's own domain | Add the domain to the required claim or move the account |
| `Forbidden` on everything | No tier granted | Add a grant in `people.yaml`; the access plane binds you on the next reconcile |
| `kubectl auth whoami` shows `admin` | The current context is the break-glass one | `kubectl config use-context homelab-oidc` and move the credential out as above |
| Browser reports nothing listening on the port | Something else (Docker Desktop) listens on `[::]:8000` and shadows the IPv4 callback | `lsof -nP -iTCP:8000 -sTCP:LISTEN`; stop it or let kubelogin use 18000 |
