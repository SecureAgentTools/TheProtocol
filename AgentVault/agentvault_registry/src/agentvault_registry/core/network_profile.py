"""
Network profile — ONE place that owns every money knob (§MONEY-M2).

WHY THIS EXISTS
---------------
Every sizing residue in the money inventory (R7 grant, R8 operator seed, R11
presence threshold, R12 prices/caps, R13 canary fires, R17 sim seeds, R27
correction ceilings, R29 showcase float) is the same defect wearing a different
number: an amount written for a billion-token supply, hardcoded or defaulted at
its call site. On a network whose whole supply is a few hundred thousand units,
a 100,000 operator seed is not a seed, it is the economy.

So the amounts move OUT of the call sites and into a profile file that a human
can read in one sitting, and every call site asks for its knob by name.

PRECEDENCE — deliberately "env wins", so shipping this file changes nothing
---------------------------------------------------------------------------
    1. os.environ[NAME]                      an operator's explicit choice
    2. the selected profile file             NETWORK_PROFILE=<path or name>
    3. the caller's fallback= argument       today's literal, unchanged

With NETWORK_PROFILE unset — which is the state of every node today — rule 3
applies and behaviour is byte-identical to the literals this replaced. That is
the property the canary proves: the mechanism ships dark.

A malformed or missing profile is NEVER fatal. It logs once and falls through to
the caller's fallback: a money rail must not stop working because a config file
is unreadable.
"""
from __future__ import annotations

import logging
import os
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Where profiles live when NETWORK_PROFILE names a profile rather than a path.
# Both the repo layout (config/ at the stack root) and the in-image layout
# (/app/config) are tried, so the same value works in a container and in a test.
def _repo_config_dir() -> Optional[Path]:
    """agentvault_registry/config when running from a source checkout.

    The profiles live INSIDE the registry package on purpose: the Dockerfile's
    `COPY ./agentvault_registry/ .` then lands them at /app/config with no
    Dockerfile change, which is the path this loader already searches.

    Guarded anyway: never index parents[] blind — a layout with fewer parents
    turns an unguarded index into an IndexError at import time, i.e. a registry
    that will not boot over a config convenience.
    """
    try:
        # src/agentvault_registry/core/this.py -> parents[3] == agentvault_registry/
        return Path(__file__).resolve().parents[3] / "config"
    except IndexError:
        return None


def find_config_file(name: str):
    """First existing `<dir>/<name>` across the same search dirs the profiles use
    (NETWORK_PROFILE_DIR, /app/config, the source checkout's agentvault_registry/config).
    Returns None when nothing exists — the caller decides what an absent file means
    (§BATCH3 item 1: the canary mTLS map ships as a config FILE the OSS export can drop)."""
    for d in _search_dirs():
        if d is None:
            continue
        candidate = d / name
        if candidate.is_file():
            return candidate
    return None


def _search_dirs():
    """Computed on every call, never frozen at import.

    An earlier version built this tuple at module scope. That worked in a
    container — the env is set before the import — and was quietly impossible to
    test or to re-read, which is how a config mechanism ends up with a knob
    nobody can prove works. Cheap to recompute; the parsed profile is what gets
    cached.
    """
    override = os.getenv("NETWORK_PROFILE_DIR", "").strip()
    return (
        Path(override) if override else None,
        Path("/app/config"),
        _repo_config_dir(),
    )

_lock = threading.Lock()
_cache: Optional[Dict[str, str]] = None
_cache_source: Optional[str] = None
_warned = False


def _candidate_paths(selector: str):
    p = Path(selector)
    if p.suffix or p.is_absolute() or "/" in selector:
        yield p
        return
    for d in _search_dirs():
        if d is None:
            continue
        yield d / f"network_profile.{selector}.env"


def _parse(text: str) -> Dict[str, str]:
    """Minimal, deliberate .env parse: KEY=VALUE, '#' comments, optional quotes.

    Inline comments are NOT stripped from unquoted values — a JSON knob such as
    FLARE_SHOP_PRICES can legitimately contain '#'. Comment your knobs on their
    own line.
    """
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if not k:
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        out[k] = v
    return out


def load(selector: Optional[str] = None) -> Dict[str, str]:
    """Return the selected profile's key/value map ({} when none is selected)."""
    global _cache, _cache_source, _warned
    sel = selector if selector is not None else os.getenv("NETWORK_PROFILE", "").strip()
    if not sel:
        return {}
    with _lock:
        if _cache is not None and _cache_source == sel:
            return _cache
        values: Dict[str, str] = {}
        found = None
        for path in _candidate_paths(sel):
            try:
                if path.is_file():
                    values = _parse(path.read_text(encoding="utf-8"))
                    found = str(path)
                    break
            except OSError:
                continue
        if found is None:
            if not _warned:
                logger.warning(
                    "[network_profile] NETWORK_PROFILE=%r selected but no profile file was found; "
                    "every knob falls back to its code default", sel
                )
                _warned = True
        else:
            logger.info("[network_profile] loaded %d knobs from %s", len(values), found)
        _cache, _cache_source = values, sel
        return values


def reset_cache() -> None:
    """Drop the cached profile (tests; a recreate is the production mechanism)."""
    global _cache, _cache_source, _warned
    with _lock:
        _cache, _cache_source, _warned = None, None, False


def knob_source(name: str) -> Optional[str]:
    """WHICH layer decides this knob on this node: "env", "profile", or None (the caller's
    fallback decides). The precedence above lives here once; `knob()` reads its answer, so a
    readout that asks who decided a value and the rail that applies it cannot disagree."""
    env = os.environ.get(name)
    if env is not None and env.strip() != "":
        return "env"
    prof = load().get(name)
    if prof is not None and prof.strip() != "":
        return "profile"
    return None


def knob(name: str, fallback: str) -> str:
    """The value of one knob as a string, honouring the precedence above."""
    source = knob_source(name)
    if source == "env":
        return os.environ[name]
    if source == "profile":
        return load()[name]
    return fallback


def money_knob(name: str, fallback: str) -> Decimal:
    """A knob that is an amount. A malformed value falls back rather than raising.

    Rails call this on the request path; a typo in a config file must not turn
    into a 500 on a transfer.
    """
    raw = knob(name, fallback)
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        logger.error(
            "[network_profile] knob %s=%r is not a number — using the code default %s",
            name, raw, fallback,
        )
        return Decimal(fallback)


def int_knob(name: str, fallback: int) -> int:
    raw = knob(name, str(fallback))
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        logger.error("[network_profile] knob %s=%r is not an integer — using %s", name, raw, fallback)
        return fallback


def bool_knob(name: str, fallback: bool) -> bool:
    raw = knob(name, "true" if fallback else "false")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")
