#!/bin/sh
set -eu
STORE_DIR="${EVAL_STORE_DIR:-/store}"
WORK="${EVAL_WORK_DIR:-/work}"
SCRATCH="${TMPDIR:-/tmp}"
DEPLOY_KEY="${EVAL_DEPLOY_KEY_FILE:-/run/secrets/deploy-key/privateKey}"
STORE="$STORE_DIR/brain-eval.git"
MOVED="$STORE_DIR/moved-to-forgejo"
KIND_FILE="$WORK/store-kind"
PRIVACY_VERDICT="$WORK/privacy-store"
use_remote=no
if [ -s "$DEPLOY_KEY" ]; then
  cp "$DEPLOY_KEY" "$SCRATCH/deploy-key"
  chmod 0600 "$SCRATCH/deploy-key"
  export GIT_SSH_COMMAND="ssh -i $SCRATCH/deploy-key -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/brain-eval/known_hosts"
  if timeout 60 git ls-remote "$EVAL_REPO_URL" > "$SCRATCH/remote-refs" 2> "$SCRATCH/ls-remote.err"; then
    use_remote=yes
  fi
fi
if [ "$use_remote" = yes ]; then
  if [ "$(cat "$PRIVACY_VERDICT" 2> /dev/null || true)" != private ]; then
    echo "eval store: refusing the Forgejo repo: no anonymous read just before this proved it private" >&2
    exit 1
  fi
  if ! grep -q "refs/heads/main$" "$SCRATCH/remote-refs" && [ -d "$STORE" ] && git -C "$STORE" rev-parse -q --verify refs/heads/main > /dev/null; then
    git -C "$STORE" push -q "$EVAL_REPO_URL" "refs/heads/*:refs/heads/*"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$MOVED"
    echo "eval store: moved the provisional in-cluster store into the private Forgejo repo"
  fi
  if grep -q "refs/heads/main$" "$SCRATCH/remote-refs" || [ -f "$MOVED" ]; then
    timeout 180 git clone -q --single-branch --branch main "$EVAL_REPO_URL" "$WORK/repo"
  else
    git init -q -b main "$WORK/repo"
    git -C "$WORK/repo" remote add origin "$EVAL_REPO_URL"
  fi
  echo forgejo > "$KIND_FILE"
  echo "eval store: private Forgejo repo at commit $(git -C "$WORK/repo" rev-parse --short -q --verify HEAD || echo none)"
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
  git clone -q --single-branch --branch main "$STORE" "$WORK/repo"
else
  git init -q -b main "$WORK/repo"
  git -C "$WORK/repo" remote add origin "$STORE"
fi
echo provisional > "$KIND_FILE"
echo "eval store: the private Forgejo repo is not reachable yet; using the provisional in-cluster store at commit $(git -C "$WORK/repo" rev-parse --short -q --verify HEAD || echo none)"
