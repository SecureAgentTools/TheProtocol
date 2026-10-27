#!/usr/bin/env bash
# §FRAMEPROV P0 (2026-09-13, his word): a frame lifecycle script names its frame, and never a protected one.
#
# Sourced FIRST by teardown_hetzner_frame.sh and start_hetzner_frame.sh. Why it exists: the admin UI's Tear down
# posts no target (FrameManagement.vue -> frame_demo_launcher.start_teardown(None)), and both scripts used to fall
# back to the newest /opt/theprotocol/stack/hetzner-frame-* dir, which is the RETIRED Hetzner stack; both also fell
# back to the NAME hetzner-frame for a dir with no run meta. Those fallbacks are gone and this is the one rule both
# scripts ask. Plan: sessionlogs2026/PLAN_2026-09-13_FRAME_PROVISIONING.md. Tests: tests/test_frame_guard.py.
#
#   frame_guard <verb> <stack dir>   prints the frame's name on stdout and returns 0,
#                                    or prints "[<verb>] REFUSED: <sentence>" on stderr and returns 2.
#
# Refused: no argument (there is no default frame) · a path that is not a directory · a dir whose run meta
# (hetzner-demo-run.json) has no readable "name" · a PROTECTED frame. Protected = a name listed in
# FRAME_PROTECTED_LIST (default /etc/theprotocol/protected-frames.list: one name per line, '#' comments), compared
# with BOTH the meta's name and the dir's basename minus its -<digits> timestamp; either match refuses. A missing or
# unreadable list refuses too (fail closed; FRAME_PROTECTED_LIST=/dev/null declares an empty set). The one way past
# a protected name is FRAME_I_MEAN_IT=<that name>, set by a human at a terminal; the admin UI's launcher never sets it.

frame_guard_protected_names() {
  sed -e 's/#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$1" | awk 'NF'
}

frame_guard() {
  local verb="${1:?frame_guard needs a verb}" arg="${2:-}"
  local list="${FRAME_PROTECTED_LIST:-/etc/theprotocol/protected-frames.list}"
  local dir="" meta="" name="" base="" dir_name="" entry="" overridden=""
  if [ -z "$arg" ]; then
    echo "[$verb] REFUSED: name the frame's stack dir (/opt/theprotocol/stack/<name>-<ts>); there is no default frame" >&2
    return 2
  fi
  if [ ! -d "$arg" ]; then
    echo "[$verb] REFUSED: $arg is not a directory" >&2
    return 2
  fi
  dir="$(readlink -f "$arg")"
  meta="$dir/hetzner-demo-run.json"
  name="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["name"])' "$meta" 2>/dev/null || true)"
  if [ -z "$name" ]; then
    echo "[$verb] REFUSED: $dir has no run meta with a name ($meta); without one this script used to act on the name hetzner-frame. Remove an orphaned stack dir by hand." >&2
    return 2
  fi
  base="$(basename "$dir")"
  if [[ "$base" =~ ^(.+)-[0-9]+$ ]]; then dir_name="${BASH_REMATCH[1]}"; else dir_name="$base"; fi
  if [ ! -r "$list" ]; then
    echo "[$verb] REFUSED: the protected-frames list $list is missing or unreadable (fail closed; FRAME_PROTECTED_LIST=/dev/null declares none)" >&2
    return 2
  fi
  while IFS= read -r entry; do
    [ "$entry" = "$name" ] || [ "$entry" = "$dir_name" ] || continue
    if [ "${FRAME_I_MEAN_IT:-}" != "$entry" ]; then
      echo "[$verb] REFUSED: $entry is a protected frame ($list; dir $dir). A human who means it sets FRAME_I_MEAN_IT=$entry." >&2
      return 2
    fi
    overridden="$entry"
  done < <(frame_guard_protected_names "$list")
  if [ -n "$overridden" ]; then
    echo "[$verb] WARNING: $overridden is a protected frame; proceeding because FRAME_I_MEAN_IT=$overridden" >&2
  fi
  printf '%s\n' "$name"
}
