#!/bin/sh
set -eu
WORK="${EVAL_WORK_DIR:-/work}"
SCRATCH="${TMPDIR:-/tmp}"
DEPLOY_KEY="${EVAL_DEPLOY_KEY_FILE:-/run/secrets/deploy-key/privateKey}"
cd "$WORK/repo"
if [ "$(cat "$WORK/store-kind")" = forgejo ]; then
  if [ "$(cat "$WORK/privacy-publish" 2> /dev/null || true)" != private ]; then
    echo "eval publish: refusing to push to the Forgejo repo: no anonymous read just before this proved it private" >&2
    exit 1
  fi
  cp "$DEPLOY_KEY" "$SCRATCH/deploy-key"
  chmod 0600 "$SCRATCH/deploy-key"
  export GIT_SSH_COMMAND="ssh -i $SCRATCH/deploy-key -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/brain-eval/known_hosts"
fi
if [ ! -f "$WORK/out/commit-message" ]; then
  echo "eval publish: the run wrote no results"
  exit 0
fi
git add -A
if git diff --cached --quiet; then
  echo "eval publish: nothing changed"
  exit 0
fi
files=$(git diff --cached --name-only | wc -l | tr -d ' ')
git -c user.name=brain-eval -c user.email=brain-eval@homelab.invalid -c commit.gpgsign=false commit -q -F "$WORK/out/commit-message"
attempt=1
while [ "$attempt" -le 4 ]; do
  if timeout 120 git push -q origin HEAD:refs/heads/main; then
    echo "eval publish: commit $(git rev-parse --short HEAD) with $files files to the $(cat "$WORK/store-kind") store"
    exit 0
  fi
  if git rev-parse -q --verify refs/remotes/origin/main > /dev/null || git ls-remote --exit-code origin refs/heads/main > /dev/null 2>&1; then
    timeout 120 git pull -q --rebase origin main || { echo "eval publish: rebase onto the store failed" >&2; exit 1; }
  fi
  attempt=$((attempt + 1))
  sleep 5
done
echo "eval publish: the store refused the push four times" >&2
exit 1
