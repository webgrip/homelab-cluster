# Runbook: Forgejo upgrades

Forgejo is single-replica with a `Recreate` rollout on an RWO volume, and it is the Flux source
([flux-source runbook](flux-source.md)). Every upgrade is a short outage of git, CI and GitOps, and
Forgejo database migrations cannot be reversed: an older binary refuses to start on a newer schema.

## What decides the running version

The HelmRelease (`kubernetes/apps/forgejo/forgejo/app/helmrelease.yaml`) pins `image.tag` and
`image.digest`. The chart renders `registry/repository:tag@digest`, and the **digest decides what
runs**. The chart's `appVersion` only fills the tag when `image.tag` is empty, so a chart bump alone
never upgrades Forgejo.

- `tag` must end in `-rootless` (the chart appends `-rootless` only when the tag does not already
  end with it) and must never contain `@sha256`.
- Renovate moves tag and digest together through the repo-local regex manager in `.renovaterc.json5`
  and holds them to the 15 LTS line (`allowedVersions: /^15\./`). helm-values cannot track this pin:
  it ignores `digest` and skips an image without `tag`, which kept Forgejo on 15.0.2 from 2026-07-15
  to 2026-10-10 while the Deployment read `15.0.7-rootless@<15.0.2 digest>`.
- Confirm the running version with `/api/v1/version` or the pod's `imageID`, never the manifest.

Look up a digest:

```sh
docker buildx imagetools inspect code.forgejo.org/forgejo/forgejo:15.0.9-rootless | grep -m1 Digest
```

## Lines and support

Forgejo 15 is LTS until 2027-07-15. Non-LTS majors live about three months. A major upgrade is a
planned ticket: read the release notes' breaking sections, check that a forgejo-helm chart targets
it, and re-verify the custom Actions UI (`app/custom/`), which depends on upstream templates (the
16.0 runs list wraps `.flex-item-title` around the link, so `wg-run-list.js` finds no rows).

## Upgrade-failure policy

The HelmRelease carries `helm.webgrip.io/fix-forward`, which exempts it from the root rollback patch
(`kubernetes/flux/cluster/ks.yaml`), and uses `upgrade.strategy: RetryOnFailure`. A failed or
timed-out upgrade is retried with the new image. It is never rolled back or uninstalled onto a
schema the old binary cannot read.

## Procedure

1. **Pre-checks.** `flux get hr -n forgejo forgejo` and the `flux-system` GitRepository are Ready;
   CNPG `forgejo-db` reports `ContinuousArchiving=True`. Prefer a quiet CI window: running jobs lose
   their connection during the restart and need a re-run (the Actions list's bulk Re-run does it).
2. **Backups.** These are imperative, so run them yourself (agent hooks block `kubectl` mutations):

   ```sh
   kubectl -n forgejo exec deploy/forgejo -- forgejo manager flush-queues
   cat <<'YAML' | kubectl create -f -
   apiVersion: postgresql.cnpg.io/v1
   kind: Backup
   metadata:
     name: forgejo-db-pre-upgrade-<version>
     namespace: forgejo
   spec:
     cluster:
       name: forgejo-db
     method: plugin
     pluginConfiguration:
       name: barman-cloud.cloudnative-pg.io
   YAML
   kubectl -n forgejo get backups.postgresql.cnpg.io forgejo-db-pre-upgrade-<version> -w
   ```

   Take an on-demand Longhorn backup of the `forgejo-data` volume from the Longhorn UI (Volume →
   Create Backup). Without these, continuous WAL archiving still allows point-in-time recovery of
   the database, and the daily 02:00 Longhorn backup covers the repositories up to that time.
3. **Change.** One commit setting `tag` and `digest` together; `./scripts/run-flux-local-test.sh`;
   push.
4. **Watch.** `flux get hr -n forgejo forgejo -w`; `kubectl -n forgejo logs deploy/forgejo -f` for
   migration lines; the old pod terminates before the new one starts.
5. **Verify.**
   - `/api/v1/version` reports the new version and the pod `imageID` carries the pinned digest.
   - `kubectl -n forgejo exec deploy/forgejo -- forgejo doctor check --all`.
   - The `flux-system` GitRepository fetches a new revision.
   - A CI job finishes on a runner, an SSH clone works, and Authentik login works.
   - The custom Actions UI renders (pipeline graph on a run, controls on the runs list).

## Rollback

- **Before the migration ran** (pod never became Ready on the new version): revert the commit. If
  Forgejo is down and Flux cannot fetch it, bridge-apply the reverted HelmRelease
  ([flux-source runbook](flux-source.md)) or break-glass to the GitHub mirror.
- **After the migration ran:** scale Forgejo to 0, restore `forgejo-db` from the pre-upgrade backup
  or by point-in-time recovery ([CNPG backups & restore](cnpg-backups.md)), restore `forgejo-data`
  from Longhorn, re-pin the previous tag and digest, scale back up.
