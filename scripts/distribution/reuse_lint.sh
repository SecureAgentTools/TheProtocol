#!/bin/sh
# reuse_lint.sh <repository root>: check that every file of a TheProtocol checkout or export carries a licence and a
# copyright holder, and that every licence it names has its text in LICENSES/ (the REUSE specification,
# https://reuse.software; REUSE.toml holds the map). Runs the REUSE tool in a throwaway container, reading the tree only.
# Exit 0 = compliant. The kit build runs it on every export before publishing.
set -eu
ROOT=${1:?name the repository root}
[ -f "$ROOT/REUSE.toml" ] || { echo "reuse_lint: no REUSE.toml in $ROOT"; exit 2; }
docker run --rm --init -v "$(cd "$ROOT" && pwd):/repo:ro" -w /repo python:3.14-bookworm sh -c '
  pip install -q --disable-pip-version-check reuse >/dev/null 2>&1 || { echo "reuse_lint: could not install the REUSE tool"; exit 3; }
  git config --global --add safe.directory /repo
  reuse lint'
