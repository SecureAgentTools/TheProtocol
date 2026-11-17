#!/bin/sh
# cut-gate.sh (session-release, 2026-11-15; order gwo_0b4f9a0f, session-lead seq 4516): may this run's jobs be skipped
# because its commit is already inside a release cut? 43% of the runner's hours on 2026-11-14/15 went to branches already
# merged into a cut (sessionlogs2026/FINDINGS_2026-11-15_CI_MERGED_RUNS.md); the cut's own run tests that code.
#   cut-gate.sh <branch> <sha> <cut-branch regex> <origin url>     prints the verdict; writes skip=true|false to $GITHUB_OUTPUT
# The rules, in order:
#   1. main and master ALWAYS run (skip=false); a branch matching the cut regex (a cut itself) ALWAYS runs.
#   2. skip=true ONLY when the commit is proven inside a cut branch (git merge-base --is-ancestor answered 0).
#   3. FAIL OPEN: anything the gate cannot tell (no sha, the branch list or a fetch failing, an unexpected answer) is
#      skip=false. An error never skips a test.
# POSIX sh (the runner's jobs run under dash). It reads the origin; it writes nothing there.
set -u
BRANCH=${1:-}; SHA=${2:-}; PAT=${3:-}; ORIGIN=${4:-}
OUT=${GITHUB_OUTPUT:-/dev/null}
verdict() { echo "skip=$1" >> "$OUT"; echo "cut-gate: skip=$1 ($2)"; exit 0; }

case "$BRANCH" in main|master) verdict false "$BRANCH always runs" ;; esac
[ -n "$BRANCH" ] && [ -n "$SHA" ] && [ -n "$PAT" ] && [ -n "$ORIGIN" ] || verdict false "a missing argument: fail open"
if printf '%s\n' "$BRANCH" | grep -Eq -- "$PAT"; then verdict false "a cut branch always runs"; fi

W=$(mktemp -d 2>/dev/null) || verdict false "no temporary directory: fail open"
trap 'rm -rf "$W"' EXIT
cd "$W" || verdict false "no temporary directory: fail open"
git init -q . 2>/dev/null || verdict false "git init failed: fail open"
HEADS=$(git ls-remote --heads "$ORIGIN" 2>/dev/null) || verdict false "the branch list could not be read: fail open"
CUTS=$(printf '%s\n' "$HEADS" | awk '{print $2}' | sed 's#^refs/heads/##' | grep -E -- "$PAT")
[ -n "$CUTS" ] || verdict false "no cut branch on the origin"
SPECS=""
for c in $CUTS; do SPECS="$SPECS +refs/heads/$c:refs/remotes/origin/$c"; done
# commits only (no trees, no blobs): ancestry needs nothing else; a server without partial clone gets a plain fetch
# shellcheck disable=SC2086
git fetch -q --filter=tree:0 "$ORIGIN" "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" $SPECS 2>/dev/null \
  || git fetch -q "$ORIGIN" "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" $SPECS 2>/dev/null \
  || verdict false "the fetch failed: fail open"
git cat-file -e "$SHA^{commit}" 2>/dev/null || verdict false "the commit $SHA is not in the fetch: fail open"
for c in $CUTS; do
  git merge-base --is-ancestor "$SHA" "refs/remotes/origin/$c" 2>/dev/null
  rc=$?
  case $rc in
    0) verdict true "$SHA is inside $c: the cut's own run tests it" ;;
    1) : ;;
    *) verdict false "the ancestry check for $c answered $rc: fail open" ;;
  esac
done
verdict false "not inside any cut"
