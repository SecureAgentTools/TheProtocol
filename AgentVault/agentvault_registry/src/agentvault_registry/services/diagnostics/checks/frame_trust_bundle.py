"""This registry's own trust bundle against its federation's frames (§MCPTEST30 V0562).

For every frame of the federation (the frame manifest's: this registry when it is a frame, and every ACTIVE peer the
manifest calls a frame), the bundle must hold a CA of that frame's trust domain, or cross-frame mTLS from it is refused
here; and the frame's NEWEST CA must have time left. SPIRE roots live 168 h and rotate near half-life (measured on EU,
ASIA and the sandbox pair 2026-10-03: the newest CA of each frame had 126 h left, the one before it 42 h), so the
newest one normally keeps at least ~84 h: under 60 h the rotation is late, under 24 h it has stopped. Reads the bundle
file only: no Docker socket, no SPIRE container.
"""

import time
from datetime import datetime, timezone

from ..schemas import CheckResult, RemediationHint

CHECK_ID = "frame-trust-bundle"
TITLE = "Trust bundle covers the federation"
DESCRIPTION = "This registry trusts a CA of every frame of its federation, and each frame's newest CA has time left."
CATEGORY = "spire"
COST_MS = 60

WARN_HOURS = 60
FAIL_HOURS = 24


def applies(target: dict) -> bool:
    return bool(target.get("self"))


async def _frames() -> list:
    """[(trust domain, display name)] of this federation's frames, from the frame manifest (None when unreadable)."""
    from agentvault_registry.core import federation_view as fv
    m = await fv.manifest_now()
    if not m:
        return None
    out, seen = [], set()
    for e in [m.get("self") or {}] + list(m.get("peers") or []):
        td = (e.get("trust_domain") or "").strip().lower()
        if e.get("role") == fv.ROLE_FRAME and td and td not in seen:
            seen.add(td)
            out.append((td, e.get("display_name") or e.get("name") or td))
    return out


async def run(target: dict, probe) -> CheckResult:
    from agentvault_registry.services import trust_bundle
    started = time.monotonic()

    def result(status, summary, **kw):
        return CheckResult(check_id=CHECK_ID, target=target["operator_id"], status=status,
                           latency_ms=int((time.monotonic() - started) * 1000), summary=summary, **kw)

    text, err = trust_bundle.read(trust_bundle.bundle_path())
    if text is None:
        return result("unknown", f"not measured: {err}")
    frames = await _frames()
    if frames is None:
        return result("unknown", "not measured: the frame manifest could not be read")
    if not frames:
        return result("unknown", "not measured: the frame manifest names no frame")
    expiry = trust_bundle.ca_expiry_by_trust_domain(text)
    now = datetime.now(timezone.utc)
    rows, missing, failing, late = [], [], [], []
    for td, name in frames:
        end = expiry.get(td)
        hours = None if end is None else round((end - now).total_seconds() / 3600, 1)
        rows.append({"frame": name, "trust_domain": td, "newest_ca_ends": end.isoformat() if end else None,
                     "hours_left": hours})
        if end is None:
            missing.append(name)
        elif hours < FAIL_HOURS:
            failing.append(f"{name} ({hours:g} h)")
        elif hours < WARN_HOURS:
            late.append(f"{name} ({hours:g} h)")
    details = {"frames": rows, "warn_below_hours": WARN_HOURS, "fail_below_hours": FAIL_HOURS}
    if missing or failing:
        parts = []
        if missing:
            parts.append(f"no CA of {', '.join(missing)}: cross-frame mTLS from it is refused here")
        if failing:
            parts.append(f"newest CA nearly over for {', '.join(failing)}: its rotation has stopped")
        return result("fail", "; ".join(parts), details=details, remediation=RemediationHint(
            action_id="manual-investigate",
            description="the frame's SPIRE server rotates its roots and the federation bundle endpoint carries them: "
                        "check that frame's SPIRE server and this frame's federation relationship with it",
            destructive=False))
    if late:
        return result("warn", f"the rotation is late for {', '.join(late)} (the newest CA normally keeps ~84 h)",
                      details=details)
    shortest = min(r["hours_left"] for r in rows)
    return result("ok", f"{len(rows)} frame(s) trusted; the newest CA of each keeps at least {shortest:g} h", details=details)
