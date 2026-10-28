#!/bin/sh
set -eu
base="https://huggingface.co/$MODEL_REPO/resolve/$MODEL_REVISION"
target="$MODEL_DIR/$MODEL_REVISION"
while read -r digest path source; do
  [ -n "$path" ] || continue
  source=${source:-$path}
  file="$target/$path"
  if [ -f "$file" ] && printf '%s  %s\n' "$digest" "$file" | sha256sum --check --status; then
    echo "verified $path"
    continue
  fi
  mkdir -p "$(dirname "$file")"
  curl --fail --silent --show-error --location --retry 5 --retry-all-errors --connect-timeout 20 --output "$file.partial" "$base/$source"
  printf '%s  %s\n' "$digest" "$file.partial" | sha256sum --check --status || { echo "sha256 mismatch for $source" >&2; rm -f "$file.partial"; exit 1; }
  mv "$file.partial" "$file"
  echo "fetched $source as $path"
done < /etc/tei/model.sha256
find "$MODEL_DIR" -mindepth 1 -maxdepth 1 -type d ! -name "$MODEL_REVISION" ! -name lost+found -exec rm -rf {} +
