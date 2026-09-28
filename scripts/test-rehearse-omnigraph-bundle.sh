#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
app=kubernetes/apps/ai/omnigraph/app
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
wrong=0

tree() {
  local dir=$work/$1
  mkdir -p "$dir/kubernetes/apps/ai/omnigraph"
  cp -r "$root/$app" "$dir/$app"
  cp -r "$root/kubernetes/components" "$dir/kubernetes/components"
  cp "$root/.mise.toml" "$dir/.mise.toml"
  echo "$dir"
}

pristine=$(tree pristine)

add_query_file() {
  local dir=$1 file=$2 in_configmap=$3
  sed -i "s/^      - brain.topics.gq$/      - brain.topics.gq\n      - $file/" "$dir/$app/bundle/cluster.yaml"
  if [ "$in_configmap" = yes ]; then
    sed -i "s#^      - ./bundle/brain.topics.gq\$#      - ./bundle/brain.topics.gq\n      - ./bundle/$file#" "$dir/$app/kustomization.yaml"
  fi
  cat > "$dir/$app/bundle/$file"
}

expect() {
  local want=$1 label=$2 marker=$3 dir=$4 rc out verdict
  shift 4
  out=$(python3 "$root/scripts/omnigraph_rehearsal.py" rehearse --repo-root "$dir" --app-dir "$dir/$app" --base-app-dir "$pristine/$app" "$@" 2>&1)
  rc=$?
  verdict=WRONG
  case "$want:$rc" in
    pass:0) grep -q '^PASS' <<<"$out" && verdict=ok ;;
    fail:1) grep -qF -- "$marker" <<<"$out" && verdict=ok ;;
  esac
  [ "$verdict" = ok ] || wrong=$((wrong + 1))
  printf '%-5s expect=%-4s rc=%s  %s\n' "$verdict" "$want" "$rc" "$label"
  if [ "$verdict" = ok ]; then
    grep -E '^(FAIL|PASS|ERROR)' <<<"$out" | cut -c1-240 | sed 's/^/        /'
  else
    printf '%s\n' "$out" | tail -25 | sed 's/^/        /'
  fi
}

d=$(tree unchanged)
expect pass "unchanged bundle" "" "$d"

d=$(tree new-query-file)
add_query_file "$d" brain.rehearsal.gq yes <<'GQ'
query rt_probe_passages($v: Vector(384), $k: String) @description("Passages of Obsidian shadow artifacts ranked by meaning") {
  match {
    $p: Passage
    $p passageOf $a
    $a.slug starts_with "obsidian-file/"
    $n noteFromArtifact $a
  }
  return { $p.@id, $a.slug, $n.slug, $p.text }
  order { nearest($p.embedding, $v) }
  limit 40
}

query rt_probe_passages_bm25($k: String) @description("Passages ranked by keywords") {
  match {
    $p: Passage
    $p passageOf $a
    $a.slug starts_with "forge/"
  }
  return { $p.@id, $a.slug, $p.text }
  order { bm25($p.text, $k) desc }
  limit 40
}
GQ
expect pass "valid new query file" "" "$d"

d=$(tree drained-schema-change)
sed -i 's/^    content: String? @index$/    content: String? @index\n    mood: String?/' "$d/$app/bundle/brain.pg"
expect pass "schema change on a graph declared drained" "" "$d" --drained brain

d=$(tree schema-change-with-branch)
sed -i 's/^    content: String? @index$/    content: String? @index\n    mood: String?/' "$d/$app/bundle/brain.pg"
expect fail "schema change while brain has a branch" "bootstrap.sh of the working bundle exited" "$d"

d=$(tree missing-from-configmap)
add_query_file "$d" brain.rehearsal.gq no <<'GQ'
query probe($q: String) {
  match {
    $n: Note
  }
  return { $n.slug }
  order { bm25($n.content, $q) desc }
  limit 5
}
GQ
expect fail "query file in cluster.yaml but not in the configMapGenerator" "does not carry it" "$d"

d=$(tree stray-in-configmap)
sed -i "s#^      - ./bundle/brain.topics.gq\$#      - ./bundle/brain.topics.gq\n      - ./bundle/brain.rehearsal.gq#" "$d/$app/kustomization.yaml"
printf 'query probe() {\n  match {\n    $n: Note\n  }\n  return { $n.slug }\n  limit 5\n}\n' > "$d/$app/bundle/brain.rehearsal.gq"
expect fail "query file in the configMapGenerator but not in cluster.yaml" "cluster.yaml does not use it" "$d"

d=$(tree invoke-query-branch-scope)
sed -i '/^  - id: owners-read-and-write-everywhere$/,/branch_scope: any/ s/^        - change$/        - change\n        - invoke_query/' "$d/$app/bundle/brain.policy.yaml"
expect fail "invoke_query in a rule with branch_scope" "unsupported action 'invoke_query'" "$d"

d=$(tree anchor-first-rrf)
add_query_file "$d" brain.rehearsal.gq yes <<'GQ'
query anchored_recall($slug: String, $q: String) {
  match {
    $t: Topic { slug: $slug }
    $n noteAboutTopic $t
  }
  return { $n.slug, $n.name }
  order { rrf(nearest($n.embedding, $q), bm25($n.content, $q)) }
  limit 10
}
GQ
expect fail "anchor-first rrf" 'anchored_recall ranks $n but binds' "$d"

d=$(tree anchor-first-nearest-live)
add_query_file "$d" brain.rehearsal.gq yes <<'GQ'
query anchored_nearest($slug: String, $q: String) {
  match {
    $t: Topic { slug: $slug }
    $n noteAboutTopic $t
  }
  return { $n.slug, $n.name }
  order { nearest($n.embedding, $q) }
  limit 10
}
GQ
expect fail "anchor-first nearest, caught live with the lint off" "anchored_nearest answered HTTP" "$d" --no-lint

d=$(tree limit-parameter)
add_query_file "$d" brain.rehearsal.gq yes <<'GQ'
query paged_notes($q: String, $n: I32) {
  match {
    $x: Note
  }
  return { $x.slug }
  order { bm25($x.content, $q) desc }
  limit $n
}
GQ
expect fail "limit \$n" 'uses limit $n' "$d"

d=$(tree actor-before-token)
sed -i 's/^    - act-brain-agent$/    - act-brain-agent\n    - act-brain-reader/' "$d/$app/bundle/brain.policy.yaml"
expect fail "policy names an actor whose token is not deployed" "grants act-brain-reader" "$d"

d=$(tree version-drift)
sed -i 's#omnigraph-server:v0\.11\.0@#omnigraph-server:v0.11.1@#' "$d/$app/deployment.yaml"
expect fail "server image and mise pin disagree" "mise pins omnigraph" "$d"

d=$(tree uncapped-env)
sed -i '/OMNIGRAPH_BACKFILL_MAX_ROWS/,+1d' "$d/$app/deployment.yaml"
expect fail "init container without a backfill cap" "the startup backfill is unbounded" "$d"

d=$(tree uncapped-bootstrap)
sed -i 's/| head -n "\$backfill_max_rows" >/| cat >/' "$d/$app/bundle/bootstrap.sh"
expect fail "bootstrap.sh ignores the backfill cap" "expected 101 left" "$d"

d=$(tree broken-bootstrap)
sed -i 's/^backfill_deadline=0$/backfill_deadline=$OMNIGRAPH_UNDEFINED_SETTING/' "$d/$app/bundle/bootstrap.sh"
expect fail "bootstrap.sh crashes on an unset variable" "bootstrap.sh of the working bundle exited" "$d"

echo "wrong verdicts: $wrong"
[ "$wrong" -eq 0 ]
