"""§MCPTEST30 (V0558): the federation suite takes back what it says.

Every run composed four broadcasts per frame and retracted one; with the admin sweep's, 733 of the 736 active
broadcasts on Sandbox Alpha and 741 of 744 on Sandbox Beta were the tester's (measured 2026-10-03, V0559: a first count
that paged with a parameter the route ignores read one page forty times and said 1,880), and the newest scrolled across
the header of every sandbox console. A test that composes a
broadcast retracts it once its verdict is decided. Best effort: a failed retraction is recorded on the result, never
raised, because the verdict is already measured.
"""
from __future__ import annotations

from typing import Any, Optional


def composed_id(resp: Any) -> Optional[int]:
    """The id composeBroadcast answered, from any of the envelopes it has used."""
    if not isinstance(resp, dict):
        return None
    for v in (resp, resp.get("broadcast"), resp.get("data"), resp.get("result")):
        if isinstance(v, dict):
            bid = v.get("id") or v.get("broadcast_id")
            if bid:
                try:
                    return int(bid)
                except (TypeError, ValueError):
                    return None
    return None


async def retract_own(rig: Any, admin: str, bid: Optional[int], result: Any) -> Any:
    """Retract the broadcast this test composed on `admin`'s registry; note the outcome on the result's last_state."""
    if not bid:
        outcome = "not retracted: the compose answered no id"
    else:
        try:
            await rig.mcp(admin).call("retractBroadcast", {"broadcast_id": int(bid)})
            outcome = f"retracted #{int(bid)} on {admin}"
        except Exception as e:  # recorded, never raised: the verdict above is already measured
            outcome = f"not retracted: {type(e).__name__}: {str(e)[:120]}"
    try:
        if isinstance(result.last_state, dict):
            result.last_state["cleanup"] = outcome
        else:
            result.last_state = {"state": result.last_state, "cleanup": outcome}
    except AttributeError:
        pass
    return result
