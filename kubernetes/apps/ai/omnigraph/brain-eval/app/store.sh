#!/bin/sh
set -eu
STORE=/store/brain-eval.git
MOVED=/store/moved-to-forgejo
KIND_FILE=/work/store-kind
use_remote=no
if [ -s /run/secrets/deploy-key/privateKey ]; then
  cp /run/secrets/deploy-key/privateKey /tmp/deploy-key
  chmod 0600 /tmp/deploy-key
  export GIT_SSH_COMMAND="ssh -i /tmp/deploy-key -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/brain-eval/known_hosts"
  if timeout 60 git ls-remote "$EVAL_REPO_URL" > /tmp/remote-refs 2> /tmp/ls-remote.err; then
    use_remote=yes
  fi
fi
if [ "$use_remote" = yes ]; then
  if ! grep -q "refs/heads/main$" /tmp/remote-refs && [ -d "$STORE" ] && git -C "$STORE" rev-parse -q --verify refs/heads/main > /dev/null; then
    git -C "$STORE" push -q "$EVAL_REPO_URL" "refs/heads/*:refs/heads/*"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$MOVED"
    echo "eval store: moved the provisional in-cluster store into the private Forgejo repo"
  fi
  if grep -q "refs/heads/main$" /tmp/remote-refs || [ -f "$MOVED" ]; then
    timeout 180 git clone -q --single-branch --branch main "$EVAL_REPO_URL" /work/repo
  else
    git init -q -b main /work/repo
    git -C /work/repo remote add origin "$EVAL_REPO_URL"
  fi
  echo forgejo > "$KIND_FILE"
  echo "eval store: private Forgejo repo at commit $(git -C /work/repo rev-parse --short -q --verify HEAD || echo none)"
  exit 0
fi
if [ -f "$MOVED" ]; then
  echo "eval repo not reachable although the store moved to Forgejo: check the deploy key on the repo and the forgejo-ssh path" >&2
  exit 1
fi
if [ ! -d "$STORE" ]; then
  git init -q --bare -b main "$STORE"
fi
if git -C "$STORE" rev-parse -q --verify refs/heads/main > /dev/null; then
  git clone -q --single-branch --branch main "$STORE" /work/repo
else
  git init -q -b main /work/repo
  git -C /work/repo remote add origin "$STORE"
fi
echo provisional > "$KIND_FILE"
echo "eval store: the private Forgejo repo is not reachable yet; using the provisional in-cluster store at commit $(git -C /work/repo rev-parse --short -q --verify HEAD || echo none)"
