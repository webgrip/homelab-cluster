#!/bin/sh
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
server_rel="kubernetes/apps/ai/brain-tools/app/server"
tests_rel="scripts/brain-tools"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fresh_copy() {
  rm -rf "$work/tree"
  mkdir -p "$work/tree/$server_rel" "$work/tree/$tests_rel"
  cp "$root/$server_rel"/*.ts "$root/$server_rel/package.json" "$work/tree/$server_rel/"
  cp "$root/$tests_rel"/*.ts "$root/$tests_rel/package.json" "$work/tree/$tests_rel/"
}

run_suite() {
  (cd "$work/tree" && node --test --test-reporter=dot "$tests_rel/brain_tools.test.ts" >"$work/out.log" 2>&1)
}

mutate() {
  node -e '
const fs = require("node:fs");
const [path, old, replacement] = process.argv.slice(1);
const text = fs.readFileSync(path, "utf8");
const count = text.split(old).length - 1;
if (count !== 1) {
  console.error(`mutation anchor found ${count} times in ${path}: ${JSON.stringify(old)}`);
  process.exit(2);
}
fs.writeFileSync(path, text.replace(old, () => replacement));
' "$work/tree/$server_rel/$1" "$2" "$3"
}

fresh_copy
if ! run_suite; then
  cat "$work/out.log"
  echo "FAIL the unmodified brain-tools must pass its suite" >&2
  exit 1
fi
echo "ok    unmodified brain-tools passes"

survivors=0
check() {
  local name="$1" file="$2" old="$3" new="$4"
  fresh_copy
  mutate "$file" "$old" "$new"
  if run_suite; then
    echo "SURVIVED $name"
    survivors=$((survivors + 1))
  else
    echo "killed   $name"
  fi
}

check "bot documents are not down-weighted" search.ts "export const BOT_WEIGHT = 0.3;" "export const BOT_WEIGHT = 1;"
check "Dutch keywords weigh as much as English" search.ts "nl: 0.6" "nl: 1.0"
check "no cap on chunks per document" search.ts "export const MAX_CHUNKS_PER_DOCUMENT = 2;" "export const MAX_CHUNKS_PER_DOCUMENT = 99;"
check "short chunks are kept" search.ts "const long = weighted.filter((source) => source.kind === 'capture' || source.text.trim().length > SHORT_CHUNK_CHARS);" "const long = weighted;"
check "the dedupe hash keeps numbers" text.ts ".replace(/\\p{N}+/gu, '#')" ""
check "dedupe keeps the first clone, not the newest" search.ts "const merged = newer(source, kept) ?" "const merged = false ?"
check "the snapshot is not sent" upstream.ts "const body = snapshot === null ? { params } : { params, snapshot };" "const body = { params };"
check "a pinned read uses the head bot cache" caches.ts "if (snapshot === null) return this.head ?? (await this.refreshHead());" "return this.head ?? (await this.refreshHead());"
check "the embedding contract is ignored" service.ts "contractOk: () => this.contractOk," "contractOk: () => true,"
check "stopwords reach the keyword legs" text.ts "if (ENGLISH.has(word) || DUTCH.has(word)) continue;" ""
check "search answers are not capped" render.ts "export const SEARCH_MAX_CHARS = 6000;" "export const SEARCH_MAX_CHARS = 60000;"
check "browser origins are admitted" mcp.ts "if (request.headers['origin'] !== undefined) {" "if (false) {"
check "the question is logged" service.ts "      profile: result.profile,
      mode: result.mode," "      profile: result.profile,
      question,
      mode: result.mode,"
check "p0 interleaves passages before notes" search.ts "interleave([noteSources, passageSources, topicSources])" "interleave([passageSources, noteSources, topicSources])"
check "the search deadline is ignored" service.ts "    const debug = surface === 'rest' && truthy(args['debug']);
    const signal = AbortSignal.timeout(this.deadlineMs);" "    const debug = surface === 'rest' && truthy(args['debug']);
    const signal = AbortSignal.timeout(60000);"
check "an unavailable brain is reported as a plain error" service.ts "if (error instanceof UpstreamError && (error.unavailable ||" "if (error instanceof UpstreamError && (false ||"
check "read ignores the neighbouring chunks" read.ts "lo: Math.max(0, focus - around), hi: focus + around" "lo: focus, hi: focus"
check "an Obsidian note reads the wrong artifact" read.ts 'return noteSlug.startsWith('"'"'obsidian/'"'"') ? `obsidian-file/${' 'return noteSlug.startsWith('"'"'obsidian/'"'"') ? `obsidian/${'
check "an embedding failure fails the search" search.ts "      if (signal.aborted) throw error;
      degraded = 'keyword-only';" "      throw error;"
check "readiness ignores missing queries" service.ts "return this.catalog.reachable && this.catalog.missing.length === 0;" "return this.catalog.reachable;"
check "the question vector is not normalised" upstream.ts "return l2Normalise(vector as number[]);" "return vector as number[];"
check "request bodies are unbounded" mcp.ts "export const MAX_BODY_BYTES = 16 * 1024;" "export const MAX_BODY_BYTES = 16 * 1024 * 1024;"

if [ "$survivors" -gt 0 ]; then
  echo "FAIL $survivors mutant(s) survived the brain-tools suite" >&2
  exit 1
fi
echo "PASS every brain-tools mutant was killed"
