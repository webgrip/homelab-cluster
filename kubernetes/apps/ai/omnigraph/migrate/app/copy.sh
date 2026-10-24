#!/bin/sh
set -eu
for graph in $OMNIGRAPH_GRAPHS; do
  rm -rf "/work/$graph.omni"
  cp -a "/source/graphs/$graph.omni" "/work/$graph.omni"
  omnigraph snapshot --store "file:///work/$graph.omni" > /dev/null
  echo "copied $graph and settled it with 0.11"
done
