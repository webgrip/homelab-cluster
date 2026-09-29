# Test Ploeg and Vloer together

Vloer is where a person starts and follows work. Ploeg records work handed to agents, controls its budget, and tracks whether it is still running. This deployment is a prerelease for testing.

## Open Vloer

Use the Vloer application in Authentik from the homelab network or VPN. Sign in with the existing homelab administrator account and complete MFA if requested. The application runs at the hostname declared in the [Vloer route](../../../../kubernetes/apps/ploeg/de-vloer/app/httproute.yaml).

The [deployment settings](../../../../kubernetes/apps/ploeg/de-vloer/app/helmrelease.yaml) allow one session at a time and a maximum of $0.25 per session. Model requests use the existing LiteLLM `deepseek-chat` connection. Gateway spending uses the provider's peak prices; off-peak estimates are conservative and are not a final provider invoice.

## Start from a ticket

1. Create a fresh ticket on the existing **Ploeg Test** board in Vikunja. Describe one small, verifiable change to the Ploeg repository.
2. Assign it to any team user, for example **bronze**. The board determines the repository: `webgrip/glide`, branch `development`, and it pins the work to the `vloer` team whatever the assignee.
3. In Vloer, select the **Ploeg Test** ticket source, preview the ticket, and import it.
4. Choose the model and budget, then start the work. Follow its activity and inspect the resulting changes and checks.

The [Ploeg settings](../../../../kubernetes/apps/ploeg/ploeg/app/helmrelease.yaml) pin the Ploeg Test board to the `vloer` team, and Vloer's operator consumer is scoped to that team alone. `vloer` is in the roster but not under `executor.teams`, so the chart renders no ScaledJob for it and no unattended worker can claim a Ploeg Test ticket before Vloer imports it. Bronze, silver and copper keep their unattended behavior on every other routed board. Previously executed tickets cannot be imported as fresh work. Create a new ticket for another trial.

## Exercise the controls

During a small session, disconnect and reopen Vloer to check that activity remains available. Pause the session and confirm that paid work stops before resuming it. Cancel another test and confirm that it stays cancelled. Review the actual diff, check results, and recorded spending before accepting the work.

The connection to Vikunja currently uses the existing shared service account on the workbench server. That credential is not supplied to an agent workspace. Personal Vikunja account linking is not implemented.

## Recorded checks

The first live test on 2026-09-11 reached a real DeepSeek request. Ploeg recorded an observed cost of $0.0004212, blocked the credential after workspace preparation failed, and released the execution lease. This uncovered a Kubernetes request-body framing defect, subsequently reproduced in a regression test. Treat this as failure-handling evidence, not a completed agent task.

## What this deployment can verify

The released workbench supports remote agent workspaces, a shared Ploeg execution record, model access limited by Ploeg, ordinary code checks, reviewer runs, durable activity, and downloadable changes. Its separate trusted delivery verifier currently requires Docker and is disabled on this Talos cluster. Automatic publication is disabled. A completed session does not imply that a change was merged or deployed.

## Storage and recovery

Vloer stores its database and encryption key under `/data/workbench` on its persistent volume. Retain both together. The subdirectory is deliberate: the application must own its data directory, while Kubernetes owns the volume root. Workspace volumes are separate and retained for recovery.

Desired deployment state lives in the manifests linked above and is applied by Flux. Diagnose the deployed image, application logs, HelmRelease status, and ExternalSecret readiness before changing configuration. Do not delete a populated credential Secret or a data volume to retry a deployment.
