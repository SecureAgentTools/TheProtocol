#!/bin/bash
# Build THE AUDITOR's dashboard (frontend-src) reproducibly, from a commit of this repository, into a directory of its own.
#
# The live auditor bind-mounts Agents/TheAuditor/frontend from the stack checkout, so a write there IS a deploy of the public
# dashboard. This script never writes there and never uses an installed node_modules: it exports the source with git archive
# into a fresh directory, installs the packages with npm ci from the lockfile of the commit named by --lock (default: the
# source commit itself), runs the package's own checks (vue-tsc, then vite build) into --out, prints every output file's
# sha256, and compares that set with the committed frontend/ of the commit named by --compare (default: the source commit).
#
# Why --lock exists: the dashboard committed at eb182e1b (2026-10-26, the one the auditor serves) was built in a worktree
# whose node_modules was a symlink to the shared checkout's install, which dated from 2026-03-18 and matched the lockfile
# from before da231a71 (the 2026-09-27 package update), not eb182e1b's own. A build of eb182e1b's source on its own lockfile
# therefore differs in its four JavaScript files (the two stylesheets match); on the earlier lockfile it reproduces all seven
# files byte for byte:
#   build_frontend.sh --src eb182e1b --lock 'da231a71^' --out <new dir>       -> exit 0, identical
# A build of master's source differs from the committed frontend/ (vite 6, the newer runtime packages) and is a new
# dashboard; putting it live is a deploy and needs its approval card.
#
#   build_frontend.sh [--src <commit>] [--lock <commit>] [--compare <commit>] --out <new or empty dir>
# Exit 0: the build equals the compared frontend/. Exit 3: it differs (the differing files are listed). Exit 2: refused
# before anything was built (bad arguments, --out inside the live frontend/ or not empty). Other: the build failed.
set -u
die() { echo "REFUSED: $*" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd) || die "cannot read the script's directory"
REPO=$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null) || die "$HERE is not inside a git checkout"
LIVE=$(cd "$HERE" && pwd)/frontend
SRC=HEAD; LOCK=; COMPARE=; OUT=
while [ $# -gt 0 ]; do
  case "$1" in
    --src) [ $# -ge 2 ] || die "--src needs a commit"; SRC=$2; shift 2 ;;
    --lock) [ $# -ge 2 ] || die "--lock needs a commit"; LOCK=$2; shift 2 ;;
    --compare) [ $# -ge 2 ] || die "--compare needs a commit"; COMPARE=$2; shift 2 ;;
    --out) [ $# -ge 2 ] || die "--out needs a directory"; OUT=$2; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) die "unknown argument '$1'" ;;
  esac
done
[ -n "$OUT" ] || die "--out <new or empty dir> is required (the build never goes into frontend/)"
# resolved before anything is created, so a path inside frontend/ (or a link to it) is refused without a write there
OUT=$(realpath -m -- "$OUT") || die "cannot resolve $OUT"
# the live dashboard is the directory the running auditor mounts, which need not be this checkout's frontend/ (a worktree's
# is not): refuse this checkout's, the one docker inspect reports for the running container, and the stack's default path
LIVE_DEFAULT=/opt/theprotocol/stack/Agentvault2/Agents/TheAuditor/frontend
LIVE_MOUNT=$(docker inspect "${AUDITOR_CONTAINER:-auditor-agent}" \
  --format '{{range .Mounts}}{{if eq .Destination "/app/frontend"}}{{.Source}}{{end}}{{end}}' 2>/dev/null) || LIVE_MOUNT=
for live in "$LIVE" "$LIVE_MOUNT" "$LIVE_DEFAULT"; do
  [ -n "$live" ] || continue
  LIVE_REAL=$(realpath -m -- "$live")
  case "$OUT/" in "$LIVE_REAL/"*) die "--out $OUT is inside the live dashboard ($LIVE_REAL): a write there is a deploy" ;; esac
done
mkdir -p -- "$OUT" 2>/dev/null || die "cannot create $OUT"
[ -z "$(ls -A "$OUT")" ] || die "--out $OUT is not empty"
: "${LOCK:=$SRC}"; : "${COMPARE:=$SRC}"
for c in "$SRC" "$LOCK" "$COMPARE"; do
  git -C "$REPO" rev-parse --verify --quiet "$c^{commit}" > /dev/null || die "'$c' is not a commit of $REPO"
done
command -v npm > /dev/null || die "npm is not installed"

BASE=${TMPDIR:-/tmp}
WORK=$(mktemp -d "$BASE/auditor-fe.XXXXXX") || die "cannot make a work directory under $BASE"
cleanup() { case "$WORK" in "$BASE"/auditor-fe.??????) rm -rf -- "$WORK" ;; esac; }
trap cleanup EXIT
P=Agents/TheAuditor
git -C "$REPO" archive "$SRC" "$P/frontend-src" | tar -x -C "$WORK" || { echo "FAILED: git archive of $SRC" >&2; exit 1; }
W=$WORK/$P/frontend-src
for f in package.json package-lock.json; do
  git -C "$REPO" show "$LOCK:$P/frontend-src/$f" > "$W/$f" || { echo "FAILED: $f at $LOCK" >&2; exit 1; }
done
echo "source $(git -C "$REPO" rev-parse --short=12 "$SRC"), packages from the lockfile at $(git -C "$REPO" rev-parse --short=12 "$LOCK"), node $(node -v), npm $(npm -v)"
( cd "$W" && npm ci --no-audit --no-fund --loglevel=error ) || { echo "FAILED: npm ci" >&2; exit 1; }
( cd "$W" && npm exec --offline -- vue-tsc --noEmit ) || { echo "FAILED: vue-tsc" >&2; exit 1; }
( cd "$W" && npm exec --offline -- vite build --outDir "$OUT" --emptyOutDir --logLevel warn ) || { echo "FAILED: vite build" >&2; exit 1; }

C=$WORK/compare
mkdir -p "$C"
git -C "$REPO" archive "$COMPARE" "$P/frontend" | tar -x -C "$C" || { echo "FAILED: git archive of frontend/ at $COMPARE" >&2; exit 1; }
sums() { (cd "$1" && find . -type f | LC_ALL=C sort | xargs -r sha256sum); }
sums "$OUT" > "$WORK/built.sha256"
sums "$C/$P/frontend" > "$WORK/committed.sha256"
echo "built ($OUT):"; sed 's/^/  /' "$WORK/built.sha256"
if cmp -s "$WORK/built.sha256" "$WORK/committed.sha256"; then
  echo "IDENTICAL: the build equals frontend/ as committed at $(git -C "$REPO" rev-parse --short=12 "$COMPARE") ($(wc -l < "$WORK/built.sha256") files)"
  exit 0
fi
echo "DIFFERS from frontend/ as committed at $(git -C "$REPO" rev-parse --short=12 "$COMPARE"):"
diff "$WORK/committed.sha256" "$WORK/built.sha256" | sed -n 's/^< /  only committed: /p; s/^> /  only built:     /p'
exit 3
