"""V0666 the games switch (order gwo_a01c49ec): one flag that turns the games off, routes, tools, loops and console views.

GAMES_ENABLED, default true (today's behaviour). Off, the registry mounts none of the six game routers (arena/mount.py),
lists and dispatches no game tool (mcp/tool_switches.py), and says games_enabled false in /api/v1/public/registry-config so
the console hides its doors. Read per call, so a flip takes effect on recreate. Parsed as core/legacy_surfaces.py parses
its surfaces: only an explicit off word ("0", "false", "no", "off") switches it off; an unknown value counts as ON, so a
typo never retires a running surface. Games move no value; the one money path near them (the arena bet) keeps its own
switch (ARENA_BETTING_ENABLED) and is unmounted with the rest when games are off.
"""
from __future__ import annotations

import os

_OFF = {"0", "false", "no", "off"}

OFF_SENTENCE = "The games are off on this registry (GAMES_ENABLED=false)."


def games_enabled() -> bool:
    v = (os.getenv("GAMES_ENABLED", "true") or "true").strip().lower()
    return v not in _OFF
