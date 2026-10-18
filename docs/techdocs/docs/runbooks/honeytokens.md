# Runbook: honeytokens (decoy credentials)

Use this when a `Honeytoken*` alert fires, after a LiteLLM or Forgejo upgrade, or to test the
decoys. Decision and design: [ADR-0075](../adr/adr-0075-honeytokens-catch-a-working-prompt-injection.md).

A honeytoken is a credential nobody legitimately holds. It grants nothing; any use of it means
something read it where only an injected instruction, an explorer or an escaped workload would
look.

## Facts

| Placement | Where it lives | Forgejo account | LiteLLM decoy in OpenBao |
| --- | --- | --- | --- |
| workspace | Secret `unfold-workspaces/workspace-deploy-credentials`, env `FORGEJO_ADMIN_TOKEN` and `LITELLM_ADMIN_KEY` in every Unfold agent container | `deploy-automation` | `honeytokens/litellm-workspace` |
| escape | Secret `ploeg/forgejo-admin-break-glass`, keys `FORGEJO_ADMIN_TOKEN` and `LITELLM_MASTER_KEY`, mounted nowhere | `breakglass-admin` | `honeytokens/litellm-escape` |
| repository | `webgrip/ops-credentials`, file `.env` (planted by hand, see below) | `backup-operator` | `honeytokens/litellm-repository` |

* The three Forgejo tokens are in OpenBao at `honeytokens/forgejo` (properties `workspace`,
  `repository`, `escape`), minted by the `honeytoken-provisioner` Job in `forgejo`.
* LiteLLM never registered the decoy keys. Forgejo's canary accounts are restricted, private, in
  no team, and may create no repository.
* Manifests: `kubernetes/apps/security/honeytokens/` (`decoys`, `placements`, `alerts`). Log rules
  run in `vmalert-logs` (application VictoriaLogs); the Secret-read rule runs in `vmalert-audit`.

| Alert | Source | Fires on |
| --- | --- | --- |
| `HoneytokenForgejoTokenUsed` | Forgejo access log | any request authenticated as a canary account |
| `HoneytokenLiteLLMKeyUsed` | LiteLLM `auth_exception_handler.py` | `key=<sha256 of a decoy>, not found in db` |
| `HoneytokenEscapeSecretRead` | API audit log | `get`/`update`/`patch`/`delete` of the escape Secret by anyone but External Secrets |
| `HoneytokenForgejoDetectorBlind` / `HoneytokenLiteLLMDetectorBlind` | the same logs | thirty minutes without a line |

## A decoy was used

Do not rotate first. The decoy is the evidence, and it grants nothing.

1. Read the alert's `placement` and `ip`. The IP is the caller's pod.
2. Find the pod:

    ```sh
    kubectl get pods -A -o wide --field-selector status.podIP=<ip>
    ```

    In `unfold-workspaces` the pod name carries the session; in `ploeg` it is a worker Job pod whose
    labels name the Run.

3. Stop the work it belongs to: stop the session or Run in Unfold (Work Item → Stop). Keep the pod
   if it still exists; do not delete the workspace.
4. Read what led there:
    * workspace: the session transcript in Unfold, from the last human message up to the call. Look
      for text the agent took as an instruction: a Work Item description, a file in the repository,
      a fetched page, a pull request comment.
    * repository: which identity read `webgrip/ops-credentials` (Forgejo access log,
      `_msg:"/webgrip/ops-credentials"`), then that identity's Run.
    * escape: treat it as a breach of the pod boundary. Pull the audit trail for the pod's
      ServiceAccount and node, and cordon the node if the pod looks escaped.
5. Find the other calls from that IP in the same window, in VictoriaLogs:

    ```logsql
    _time:1h "<ip>"
    ```

6. File what you found on the Unfold board with the transcript excerpt and the injected text.
7. Rotate only after the review, and only the placement that leaked (see [Rotate a decoy](#rotate-a-decoy)).

If the alert came from the post-merge test or a deliberate check, note it in the ntfy thread and
move on.

## A decoy was read

`HoneytokenEscapeSecretRead` names the user.

* `oidc:<person>` or `admin`: ask the person. Reading Secrets while debugging Ploeg is the usual
  answer.
* A ServiceAccount: find its pods (`kubectl get pods -A -o json | jq` on
  `.spec.serviceAccountName`), check which RoleBinding let it read Secrets in `ploeg`, and follow
  [A decoy was used](#a-decoy-was-used) from step 3.

## A detector is blind

* `HoneytokenForgejoDetectorBlind`: Forgejo stopped writing access-log lines. Check that
  `gitea.config.log` in `kubernetes/apps/forgejo/forgejo/app/helmrelease.yaml` still sets
  `logger.access.MODE: console`, and that the Forgejo pod logs lines shaped like
  `10.42.x.y - user [18/Oct/2026:11:53:19 +0000] "GET /api/v1/user HTTP/1.1" 200 ...`.
* `HoneytokenLiteLLMDetectorBlind`: no LiteLLM log lines. Check the pod, then whether the
  container is still named `app` in the `ai` namespace.
* After a LiteLLM upgrade, run the LiteLLM step of the post-merge test: if the "not found in db"
  message changed, the use alert goes quiet without the blind alert noticing.

## Post-merge test

Run once after the merge, and after each LiteLLM or Forgejo upgrade. It sends four requests with
decoys and costs nothing: every one is refused before a model is reached.

1. Wait for Flux:

    ```sh
    flux get kustomizations -n security | grep honeytokens
    kubectl -n forgejo logs job/honeytoken-provisioner
    kubectl -n unfold-workspaces get externalsecret workspace-deploy-credentials
    kubectl -n ploeg get externalsecret forgejo-admin-break-glass
    kubectl -n observability get vmrule honeytokens-used honeytokens-read
    kubectl -n observability get vmalert vmalert-logs
    ```

    Expect three `Ready` Kustomizations, Job output ending in
    `Secret honeytoken-forgejo holds the three decoy Forgejo tokens`, and both ExternalSecrets
    `SecretSynced`.

2. Confirm the Forgejo access log flows (it should already, or the blind alert fires in 30 minutes):

    ```logsql
    _time:5m namespace:=forgejo container:=forgejo _msg:~" - \\S+ \\[" | limit 3
    ```

3. Use each escape decoy once from a throwaway pod in `ploeg`, which can reach both services:

    ```sh
    kubectl -n ploeg run honeytoken-test --rm -i --restart=Never \
      --image=harbor.webgrip.dev/dockerhub/curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777 \
      --overrides='{"spec":{"containers":[{"name":"honeytoken-test","image":"harbor.webgrip.dev/dockerhub/curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777","stdin":true,"command":["sh","-c","curl -s -o /dev/null -w \"forgejo %{http_code}\\n\" -H \"Authorization: token $FORGEJO_ADMIN_TOKEN\" http://forgejo-http.forgejo.svc.cluster.local:3000/api/v1/user; curl -s -o /dev/null -w \"litellm %{http_code}\\n\" -H \"Authorization: Bearer $LITELLM_MASTER_KEY\" http://litellm.ai.svc.cluster.local:4000/v1/models"],"envFrom":[{"secretRef":{"name":"forgejo-admin-break-glass"}}],"securityContext":{"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":65534,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}'
    ```

    Expect `forgejo 200` (the canary account answers `/user` and nothing else) and `litellm 401`.
    Any pod in `ploeg` may reach `ai:4000` and `forgejo:3000` (`ploeg-allow-egress`). The decoy
    values are never printed.

4. Read the escape Secret once by hand:

    ```sh
    kubectl -n ploeg get secret forgejo-admin-break-glass -o name
    ```

    `-o name` still makes a `get`, which is what the audit rule watches.

5. Within two minutes ntfy `alerts-critical` shows `HoneytokenForgejoTokenUsed` and
   `HoneytokenLiteLLMKeyUsed` with `placement="escape"`, and within six minutes
   `HoneytokenEscapeSecretRead` with your `oidc:` user. Check them in Alertmanager too:

    ```sh
    kubectl -n observability exec deploy/vmalert-vmalert-logs -c vmalert -- \
      wget -qO- http://127.0.0.1:8080/api/v1/alerts | jq '.data.alerts[] | {name, state, labels}'
    ```

6. Confirm the decoy grants nothing: the same pod's `GET /api/v1/repos/search` returns an empty
   list, and `POST /api/v1/user/repos` returns 403.

7. Confirm the main `vmalert` stopped failing on audit rules:

    ```sh
    kubectl -n observability logs deploy/vmalert-vmalert -c vmalert --since=10m | grep -c kubernetes.audit
    ```

    Expect `0`.

## Plant the repository decoy

The provisioner mints the `backup-operator` token and the repository LiteLLM key but does not
write them into a repository. Plant them once, by hand, from a workstation with OpenBao access:

1. Create `webgrip/ops-credentials` as a **private** repository in the `webgrip` organisation.
   Agent teams with `includes_all_repositories` can then read it; nobody else needs to.
2. Add `renovate.json` with `{"enabled": false}` so Renovate leaves it alone.
3. Add a short `README.md` that reads like an ops note: off-cluster backup and restore
   credentials, load `.env` before a restore, rotate after a drill. Do not address agents.
4. Add `.env` from OpenBao without echoing the values:

    ```sh
    {
      echo "FORGEJO_URL=http://forgejo-http.forgejo.svc.cluster.local:3000"
      echo "FORGEJO_USER=backup-operator"
      echo "FORGEJO_TOKEN=$(bao kv get -field=repository secret/honeytokens/forgejo)"
      echo "LITELLM_BASE_URL=http://litellm.ai.svc.cluster.local:4000"
      echo "LITELLM_KEY=$(bao kv get -field=key secret/honeytokens/litellm-repository)"
    } > .env
    ```

5. Commit and push, then use the repository decoys once as in the post-merge test and expect
   `placement="repository"`.

## Rotate a decoy

Rotate a placement only after a review closed, or when a decoy was published somewhere public.

* Forgejo: delete the account's `automation` token in Forgejo (Site administration → User
  accounts → the canary → Access tokens), then re-run the provisioner by deleting its Job
  (`kubectl -n forgejo delete job honeytoken-provisioner`; Flux recreates it). The PushSecret and
  the placements follow within an hour. For the repository placement, push the new `.env`.
* LiteLLM: delete the generated Secret (`kubectl -n forgejo delete secret
  honeytoken-litellm-<placement>`) and force the ExternalSecret to regenerate it
  (`kubectl -n forgejo annotate externalsecret honeytoken-litellm-<placement> force-sync=$(date +%s) --overwrite`).
  The fingerprint Secret and the alert rule follow on their next reconcile.
