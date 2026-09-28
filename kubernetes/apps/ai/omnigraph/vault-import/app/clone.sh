#!/bin/sh
set -eu
if [ ! -s /run/secrets/vault-deploy-key/privateKey ]; then
  echo "vault repo not reachable: the omnigraph-vault-import-deploy-key Secret has no privateKey yet" >&2
  exit 1
fi
cp /run/secrets/vault-deploy-key/privateKey /tmp/deploy-key
chmod 0600 /tmp/deploy-key
export GIT_SSH_COMMAND="ssh -i /tmp/deploy-key -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/vault-import/known_hosts"
export GIT_LFS_SKIP_SMUDGE=1
if ! timeout 180 git -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false clone --quiet --depth 1 --single-branch "$VAULT_REPO_URL" /work/vault; then
  echo "vault repo not reachable: $VAULT_REPO_URL does not exist or does not carry the read-only deploy key from secret/omnigraph/vault-import-deploy-key" >&2
  exit 1
fi
echo "vault cloned at commit $(git -C /work/vault rev-parse --short HEAD)"
