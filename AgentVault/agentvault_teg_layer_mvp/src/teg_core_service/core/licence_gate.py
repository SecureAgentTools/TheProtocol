"""§FEDLICENCE (2026-09-28, his word "cross-teg cut off also approved on revoke"): the TEG refuses a federated frame whose
network licence its own registry refuses.

A cross-registry transfer runs registry -> its own TEG -> the peer's TEG (/api/v1/cross-teg/*, through the peer's
nginx-teg), and a TEG accepted any certificate of a domain in TRUSTED_SPIFFE_DOMAINS. So after a licence revoke the
registry lanes refused the frame while the TEG legs still passed (DESIGN_2026-09-28_FEDERATION_LICENCE.md § 10 point 3).

The TEG never evaluates a certificate itself. It copies its registry's verdicts (GET /api/v1/federation/licence/verdicts
on REGISTRY_URL, every TEG_LICENCE_REFRESH_SECONDS) and refuses, in extract_spiffe_from_request, a FOREIGN trust domain
the registry lists as refused while the mode is enforce. The registry's rules hold here too: this TEG's own trust domain
is never checked, a peer the registry could not verify or has not evaluated passes, a failed read keeps the last copy,
and before the first copy nobody is refused (a registry outage must never partition the TEGs).

TEG_FEDERATION_LICENCE_MODE: follow (default, the registry's mode) | off | observe | enforce.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

VERDICTS_PATH = "/api/v1/federation/licence/verdicts"
_MODES = ("off", "observe", "enforce")
_WARN_WINDOW = 600.0

_STATE: Dict[str, Any] = {
    "mode": "off",           # the registry's mode, as last read
    "local": "",             # the registry's own trust domain, as last read
    "refused": frozenset(),  # the trust domains the registry refuses
    "verdicts": {},          # trust domain -> verdict, for the log line and the status block
    "loaded_at": 0.0,        # monotonic time of the last good read (0 = never)
    "last_error": "",
}
_WARNED: Dict[str, float] = {}

try:
    from prometheus_client import Counter as _Counter

    TEG_LICENCE_CROSSINGS_TOTAL = _Counter(
        "teg_federation_licence_crossings_total",
        "Foreign-domain identities seen by the TEG's certificate reader, by the registry's licence verdict and what the "
        "TEG's mode did with them",
        labelnames=["verdict", "outcome"],
    )
except Exception:  # pragma: no cover  (no metrics library: no counter)
    TEG_LICENCE_CROSSINGS_TOTAL = None


def _norm_td(value: Any) -> str:
    return str(value or "").strip().lower().removeprefix("spiffe://").strip("/")


def refresh_seconds() -> float:
    try:
        return max(5.0, float(os.getenv("TEG_LICENCE_REFRESH_SECONDS", "60")))
    except ValueError:
        return 60.0


def effective_mode() -> str:
    """The mode this TEG acts in: TEG_FEDERATION_LICENCE_MODE when it names one, else the registry's (off until read)."""
    override = (os.getenv("TEG_FEDERATION_LICENCE_MODE", "follow") or "follow").strip().lower()
    if override in _MODES:
        return override
    return _STATE["mode"] if _STATE["loaded_at"] else "off"


def apply_payload(payload: Any, *, now: float) -> bool:
    """Take the registry's answer. A payload of the wrong shape changes nothing and says so (False)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("verdicts"), dict) \
            or not isinstance(payload.get("refused"), list):
        _STATE["last_error"] = "the registry's answer has no verdicts/refused"
        return False
    mode = str(payload.get("mode") or "off").strip().lower()
    _STATE["mode"] = mode if mode in _MODES else "off"
    _STATE["local"] = _norm_td(payload.get("local_trust_domain"))
    _STATE["refused"] = frozenset(td for td in (_norm_td(x) for x in payload["refused"]) if td)
    _STATE["verdicts"] = {_norm_td(k): str(v) for k, v in payload["verdicts"].items() if _norm_td(k)}
    _STATE["loaded_at"] = now
    _STATE["last_error"] = ""
    return True


def refusal(spiffe_id: Optional[str]) -> Optional[str]:
    """None when this identity may cross, else why not (enforce only). Observe names the crossing and refuses nothing.
    Never raises: a fault here must not decide a money leg."""
    try:
        m = str(spiffe_id or "")
        if not m.startswith("spiffe://"):
            return None
        td = _norm_td(m[len("spiffe://"):].split("/", 1)[0])
        own = {_norm_td(os.getenv("SPIRE_TRUST_DOMAIN")), _STATE["local"]} - {""}
        if not td or td in own:
            return None
        mode = effective_mode()
        if mode not in ("observe", "enforce"):
            return None
        verdict = _STATE["verdicts"].get(td) or "unevaluated"
        refused = td in _STATE["refused"]
        outcome = ("refused" if mode == "enforce" else "would_refuse") if refused else "allowed"
        if TEG_LICENCE_CROSSINGS_TOTAL is not None:
            try:
                TEG_LICENCE_CROSSINGS_TOTAL.labels(verdict=verdict, outcome=outcome).inc()
            except Exception:  # noqa: BLE001  (a metric never decides a request)
                pass
        if not refused:
            return None
        t = time.monotonic()
        if t - _WARNED.get(td, -1e9) > _WARN_WINDOW:
            _WARNED[td] = t
            logger.warning(f"[TEG-LICENCE] {outcome.upper()}: {m} (trust domain {td}, the registry's licence verdict "
                           f"{verdict}, mode {mode})")
        return f"{td} ({verdict})" if mode == "enforce" else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[TEG-LICENCE] check failed, the crossing is not refused by it: {type(exc).__name__}: {exc}")
        return None


def status() -> Dict[str, Any]:
    """What the TEG holds, for /health and the proofs (no secrets: trust domains and states only)."""
    return {
        "mode": effective_mode(),
        "registry_mode": _STATE["mode"],
        "override": (os.getenv("TEG_FEDERATION_LICENCE_MODE", "follow") or "follow").strip().lower(),
        "refused": sorted(_STATE["refused"]),
        "peers": len(_STATE["verdicts"]),
        "loaded_seconds_ago": round(time.monotonic() - _STATE["loaded_at"], 1) if _STATE["loaded_at"] else None,
        "last_error": _STATE["last_error"] or None,
    }


async def _fetch_payload() -> Any:
    import aiohttp
    base = (os.getenv("REGISTRY_URL", "http://registry-a:8000") or "").rstrip("/")
    ctx = None
    if base.startswith("https://"):
        try:
            from ..event_emitter import _svid_ssl_context  # the TEG's one client context toward its registry
            ctx, _ = _svid_ssl_context()
        except Exception:  # noqa: BLE001
            ctx = None
    connector = aiohttp.TCPConnector(ssl=ctx) if ctx is not None else None
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(f"{base}{VERDICTS_PATH}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"the registry answered {resp.status}")
            return await resp.json()


async def refresh_once(*, fetch=_fetch_payload, now=time.monotonic) -> bool:
    """One read. A failure keeps the last copy and is logged at most once per window."""
    try:
        return apply_payload(await fetch(), now=now())
    except Exception as exc:  # noqa: BLE001
        _STATE["last_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        t = time.monotonic()
        if t - _WARNED.get("_fetch", -1e9) > _WARN_WINDOW:
            _WARNED["_fetch"] = t
            logger.warning(f"[TEG-LICENCE] verdicts not refreshed, keeping the last copy "
                           f"({'none yet' if not _STATE['loaded_at'] else 'mode ' + _STATE['mode']}): {_STATE['last_error']}")
        return False


async def refresh_loop() -> None:
    first = True
    while True:
        try:
            ok = await refresh_once()
            if first and ok:
                logger.info(f"[TEG-LICENCE] verdicts loaded from the registry: mode {_STATE['mode']}, "
                            f"{len(_STATE['verdicts'])} peers, refused {sorted(_STATE['refused']) or 'none'}")
                first = False
            await asyncio.sleep(refresh_seconds())
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001  (the loop outlives any one cycle)
            logger.warning(f"[TEG-LICENCE] refresh loop error: {type(exc).__name__}: {exc}")
            await asyncio.sleep(refresh_seconds())
