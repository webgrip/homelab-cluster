#!/bin/sh
set -eu
cd /work/repo
if [ "$(cat /work/store-kind)" = forgejo ]; then
  cp /run/secrets/deploy-key/privateKey /tmp/deploy-key
  chmod 0600 /tmp/deploy-key
  export GIT_SSH_COMMAND="ssh -i /tmp/deploy-key -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/brain-eval/known_hosts"
fi
if [ ! -f /work/out/commit-message ]; then
  echo "eval publish: the run wrote no results"
  exit 0
fi
git add -A
if git diff --cached --quiet; then
  echo "eval publish: nothing changed"
  exit 0
fi
files=$(git diff --cached --name-only | wc -l | tr -d ' ')
git -c user.name=brain-eval -c user.email=brain-eval@homelab.invalid -c commit.gpgsign=false commit -q -F /work/out/commit-message
attempt=1
while [ "$attempt" -le 4 ]; do
  if timeout 120 git push -q origin HEAD:refs/heads/main; then
    echo "eval publish: commit $(git rev-parse --short HEAD) with $files files to the $(cat /work/store-kind) store"
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
