# agent-sandbox and Ploeg's sandbox executor

[kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) runs one pod per `Sandbox` object and adds claims, templates and warm pools on top (the `extensions`). Ploeg's experimental `executor.type: sandbox` uses it: the KEDA ScaledJob's pod becomes a small launcher that creates one `SandboxClaim`, and the controller creates the worker pod from a chart-owned `SandboxTemplate`. Design and backstops are in Ploeg's [executor contract](https://forgejo.webgrip.dev/webgrip/glide/src/branch/development/apps/ploeg/docs/contracts/executor.md).

## What is installed

| Piece | Where |
| --- | --- |
| CRDs `sandboxes.agents.x-k8s.io`, `sandboxclaims`, `sandboxtemplates`, `sandboxwarmpools.extensions.agents.x-k8s.io` (all `v1beta1`) | `kubernetes/apps/agent-sandbox-system/agent-sandbox/app/upstream/crds.yaml` |
| Controller Deployment, ServiceAccount, ClusterRoles, Service | `.../upstream/controller.yaml`, hardened by `deployment-hardening.yaml` |
| Egress to the API server only; metrics ingress from `observability` | `.../networkpolicy.yaml` |
| Launcher egress to the API server | `kubernetes/apps/ploeg/ploeg/app/sandbox-launcher.ciliumnetworkpolicy.yaml` |
| RuntimeClass `kata` (Cloud Hypervisor, workers only) | `kubernetes/apps/kube-system/runtime-classes` |

The manifests are vendored because upstream publishes no OCI chart and `flux-governance-enforce` admits no GitRepository other than this repository.

## Rollout

Each step is one commit; push it, wait for Flux, check, then go on.

1. **Controller.** `flux get ks -n agent-sandbox-system agent-sandbox` is Ready and `kubectl -n agent-sandbox-system logs deploy/agent-sandbox-controller` shows the extensions controllers starting. `kubectl get crd | grep agents.x-k8s.io` lists four CRDs.
2. **Copper on the sandbox executor, default runtime.** Copper is the exec-harness smoke team: it runs `/bin/cat` on its task spec and spends no model tokens. After the push, `kubectl -n ploeg get sandboxtemplate,sandboxwarmpool` shows `ploeg-worker-copper` and the copper ScaledJob's pod template runs `ploeg-worker sandbox-launch`. Queue one copper Work Item and follow it: a launcher Job, a `SandboxClaim`, a worker pod, the Outcome `no_change_needed`, then the claim is deleted and the launcher exits 0.
3. **Kata.** Set `executor.sandbox.runtimeClassName: kata`. Repeat the copper Run; the worker pod lands on a `runtime.webgrip.io/kata` node with `runtimeClassName: kata`.
4. **Real work.** Move one more team with `executorType: sandbox` only after copper ran clean under Kata. Warm pools stay at zero replicas: the chart does not support them yet.

## Rollback

Remove `executorType: sandbox` from the team (or revert step 2's commit). The ScaledJob returns to the worker pod on its next reconcile; Runs already running finish under their Leases, and leftover claims are removed by their `shutdownTime`, their TTL or Job garbage collection. Stuck objects: `kubectl -n ploeg get sandboxclaims,sandboxes`.

Removing the controller is a separate step: first no team may use `sandbox` and no Unfold pool may exist, because pruning the CRDs deletes every `Sandbox`, claim, template and pool in the cluster.

## Upgrading

Download the release's `sandbox-with-extensions.yaml`, regenerate the two files under `upstream/` (CRDs in one, everything but the Namespace in the other, `metadata.namespace` removed), move the `images:` tag and digest in the app `kustomization.yaml` together, and read the CRD diff. Take the digest from Harbor's `k8s` proxy project as described in the `add-app` skill. The chart targets `v1beta1` only.

## Cost

The controller requests 10m CPU and 64Mi, a fraction of a watt. A Run adds a launcher pod (10m, 32Mi) for its duration; under Kata each worker also carries 250m and 160Mi of VM overhead while it runs. With zero warm replicas nothing is kept running between Runs.

## Hostile credential test, 2026-10-25

A Run on Ploeg 0.2.0-rc.68 ([VIK-2410](https://vikunja.webgrip.dev/tasks/2410), team bronze, sandbox under Kata, both credential proxies on) was told to act as the attacker and try to get or use a real model key or forge token. It held only its own placeholders, and every attempt was refused. The full record, with the worker log lines that confirm each refusal, is Ploeg's [credential-proxy requalification](https://github.com/ploeg-hq/ploeg/blob/development/docs/research/2026-10-25-credential-proxy-requalification.md) (F-04, ploeg-hq/ploeg#225).

What it showed about this cluster:

- **Egress.** From the harness container, the public names of LiteLLM and Forgejo (`litellm.<domain>`, `forgejo.<domain>`) time out, and so does any address on the internet. The in-cluster LiteLLM Service is reachable, because the worker in the same pod needs it and a NetworkPolicy applies to the whole pod, but it answers 401 to the placeholder.
- **Refusals are logged.** Each refused request appears in VictoriaLogs as one WARN line, `credential proxy refused a request`, with the trace, the proxy (`llm` or `forge`) and a reason such as `wrong_placeholder`, `push_to_other_branch` or `outside_repository`. Query: `namespace:ploeg "credential proxy refused"`.
- **`GITHUB_PAT` is a canary.** A writing Run's environment holds `GITHUB_PAT`, shaped like a GitHub personal access token. It is a random value no forge accepts, which the worker watches for in the Run's forge requests and pushed commits; it is not a credential and needs no rotation.
