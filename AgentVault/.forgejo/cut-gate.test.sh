#!/bin/sh
# cut-gate.test.sh (session-release, 2026-11-15; session-lead seq 4516): cut-gate.sh against a fixture origin. Its four
# musts: a commit inside a cut is skipped (in seconds); one not in a cut runs; a cut branch runs; the lookup failing runs.
# Also: main and master run; a commit only in an OLDER cut is still skipped; an unexpected answer runs. POSIX sh.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
GATE="$HERE/cut-gate.sh"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
PAT='^v06[0-9][0-9]/cut'
fails=0
expect() {   # expect <name> <want skip> <branch> <sha> [origin]
  out=$(GITHUB_OUTPUT="$T/out" sh "$GATE" "$3" "$4" "$PAT" "${5:-$T/origin.git}" 2>&1)
  got=$(tail -1 "$T/out" 2>/dev/null); rm -f "$T/out"
  if [ "$got" = "skip=$2" ]; then echo "PASS $1: $out"; else echo "FAIL $1: want skip=$2, got [$got]: $out"; fails=$((fails + 1)); fi
}
g() { git -C "$T/w" "$@"; }
git init -q --bare "$T/origin.git"
git init -q "$T/w"; g config user.email t@t; g config user.name t; g config commit.gpgsign false
g remote add origin "$T/origin.git"
g commit -q --allow-empty -m base; g branch -M main
g checkout -q -b merged; g commit -q --allow-empty -m merged-work; MERGED=$(g rev-parse HEAD)
g checkout -q -b unmerged main; g commit -q --allow-empty -m unmerged-work; UNMERGED=$(g rev-parse HEAD)
g checkout -q -b old-only main; g commit -q --allow-empty -m old-cut-work; OLDONLY=$(g rev-parse HEAD)
g checkout -q -b v0664/cut main; g merge -q --no-ff --no-edit old-only
g checkout -q -b v0665/cut main; g merge -q --no-ff --no-edit merged; CUT=$(g rev-parse HEAD)
g checkout -q main; MAIN=$(g rev-parse HEAD)
g push -q origin main merged unmerged old-only v0664/cut v0665/cut 2>/dev/null

expect "a commit inside a cut is skipped" true merged "$MERGED"
expect "a commit not in any cut runs" false unmerged "$UNMERGED"
expect "a cut branch runs" false v0665/cut "$CUT"
expect "main runs" false main "$MAIN"
expect "master runs" false master "$MAIN"
expect "a commit only in an older cut is skipped" true old-only "$OLDONLY"
expect "the lookup failing (no such origin) runs" false merged "$MERGED" "$T/no-such-origin.git"
expect "a commit the fetch does not carry runs" false merged 0123456789abcdef0123456789abcdef01234567
expect "a missing sha runs" false merged ""
start=$(date +%s); expect "the skip is quick" true merged "$MERGED"; took=$(( $(date +%s) - start ))
if [ "$took" -le 10 ]; then echo "PASS the skip took ${took}s (<= 10 s)"; else echo "FAIL the skip took ${took}s"; fails=$((fails + 1)); fi
[ "$fails" = 0 ] && echo "cut-gate tests: all passed" || { echo "cut-gate tests: $fails FAILED"; exit 1; }
