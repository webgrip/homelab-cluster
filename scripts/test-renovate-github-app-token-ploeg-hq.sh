#!/bin/sh
set -eu
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
minter="$repo_root/kubernetes/apps/renovate/renovate-operator/jobs/github-app-token-ploeg-hq.mjs"
suite="$repo_root/scripts/test_renovate_github_app_token_ploeg_hq.mjs"
node="${NODE:-node}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> unmutated minter must pass"
MINT_SCRIPT="$minter" "$node" "$suite"

mutate() {
  name="$1"
  find="$2"
  replace="$3"
  test_name="$4"
  copy="$work/$name.mjs"
  "$node" -e '
    const fs = require("node:fs");
    const [source, target, find, replace] = process.argv.slice(1);
    const text = fs.readFileSync(source, "utf8");
    if (!text.includes(find)) { console.error("mutation anchor not found: " + find); process.exit(2); }
    fs.writeFileSync(target, text.replace(find, replace));
  ' "$minter" "$copy" "$find" "$replace"
  if MINT_SCRIPT="$copy" "$node" "$suite" "$test_name" >"$work/$name.log" 2>&1; then
    echo "MUTATION SURVIVED: $name ($test_name passed against the mutant)" >&2
    exit 1
  fi
  echo "killed: $name by $test_name"
}

mutate absent-is-failure \
  "      return 0;
    }
    throw error;" \
  "      return 1;
    }
    throw error;" \
  absent_credentials_exit_cleanly_and_mint_nothing
mutate unscoped-repositories \
  "{ repositories: env('GITHUB_REPOSITORIES').split(','), permissions" \
  "{ permissions" \
  present_credentials_write_a_scoped_token
mutate unscoped-permissions \
  ", permissions: JSON.parse(env('TOKEN_PERMISSIONS')) }" \
  " }" \
  present_credentials_write_a_scoped_token
mutate no-create-fallback \
  "if (response.status === 404) {
    response = await request('POST'" \
  "if (false) {
    response = await request('POST'" \
  a_missing_secret_is_created
mutate ignore-refused-token \
  "if (response.status !== 201 || !response.body?.token) {" \
  "if (false) {" \
  a_refused_token_fails_and_writes_nothing
mutate denied-read-is-absent \
  "throw new MintFailure('OpenBao denied reading secret/'" \
  "throw new AppCredentialsAbsent('OpenBao denied reading secret/'" \
  a_denied_openbao_read_fails
mutate log-the-token \
  "' written to Secret ' + target" \
  "' written to Secret ' + target + minted.token" \
  no_secret_value_reaches_the_log

echo "all mutations killed"
