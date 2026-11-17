"""A developer of a test's own, beside the frame's admin: for a flow that needs two PEOPLE (V0664, session-tester; the
pair proof on nt261115x1, session-lead seq 4287).

V0664's self-dealing gate refuses a Guild order, a bid or a sale between agents of ONE developer ("a Guild order is for
someone else's work"): a flow that made its poster and its worker as the same rig principal modelled one person paying
himself, and the pair's posture now refuses it (the gate is right). The second party is a developer registered here,
through the frame admin's adminRequest (the MCP authRegister wrapper drops `name`), with NO Terms acceptance
(session-lead seq 3281: nobody writes a legal acceptance for an account no person agreed for), force-verified by the
admin only where the frame verifies mail. A frame that requires a Terms acceptance leaves the flow NOT MEASURED.
`retire` sends each developer's own deletion request at the end.

The same steps test_chat_g1_federation._owner takes (V0662), here for any flow.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet

DELETE_CONFIRM = "DELETE MY ACCOUNT"


async def _rest(rig, method: str, endpoint: str, label: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    try:
        r = await rig.mcp(label).call("adminRequest", args, timeout=60)
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


async def _refused(rig, label: str, tool: str, args: Dict[str, Any]) -> Optional[str]:
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and set(r) == {"_text"}:
        return str(r["_text"])
    if isinstance(r, dict) and r.get("error"):
        return str(r["error"])
    return None


async def register(rig, label: str, admin_label: str, tag: str, owners: List[Tuple[str, str]]) -> str:
    """A developer of the flow's own on `label`'s frame; its rig label (`<label>~<marker>`). Appended to `owners`
    (label, password) at once, so `retire` reaches it even if a later step fails."""
    # V0664 (session-lead seq 4292): an account is written only where the target ITSELF states "sandbox" (its
    # registry-config's `environment`, exactly; earned_agent_public.sandbox_stated, the earned Guild lifecycle's rule):
    # the tester ships in production's image too, and a production frame never gets a suite's account
    from agentvault_registry.api_tests.contracts.earned_agent_public import sandbox_stated
    code, cfg = await _rest(rig, "GET", "/api/v1/public/registry-config", admin_label)
    stated, why = sandbox_stated(code == 200, code, cfg)
    if not stated:
        raise PreconditionUnmet(f"{label} is not a stated sandbox ({why}): this suite registers no developer there")
    marker = uuid.uuid4().hex[:10]
    name = f"{tag}-own-{marker}"
    email = f"{name}@fedsuite-probe.dev"
    password = f"FedSuiteOwn!{uuid.uuid4().hex}"
    code, resp = -1, None
    for _ in range(3):
        code, resp = await _rest(rig, "POST", "/api/v1/auth/register", admin_label,
                                 body={"name": name, "email": email, "password": password})
        if code != 429:
            break
        await asyncio.sleep(20.0)        # register is limited to 5 a minute per caller
    if code not in (200, 201):
        said = json.dumps(resp, default=str)[:200]
        if code == 422 and "Terms" in said:
            raise PreconditionUnmet(f"registration on {label} asks for a Terms acceptance (TOS_CONSENT_REQUIRED); this "
                                    f"suite accepts no Terms for an account no person agreed for, so the flow has no "
                                    f"second developer there")
        raise PreconditionUnmet(f"the flow's own developer could not be registered on {label}: HTTP {code} {said}")
    own = rig.add_principal(label, marker, email, password)
    owners.append((own, password))
    refused = await _refused(rig, own, "getMyDeveloperProfile", {})
    if refused:                          # a frame that verifies mail: the admin verifies its own throwaway, once
        found = await _rest(rig, "GET", f"/api/v1/admin/developers?search={name}", admin_label)
        devs = (found[1] or {}).get("developers") if isinstance(found[1], dict) else None
        row = next((d for d in (devs or []) if isinstance(d, dict) and d.get("email") == email), None)
        if row:
            await _rest(rig, "POST", f"/api/v1/admin/developers/{row['id']}/force-email-verify", admin_label,
                        body={"reason": "federation suite: a flow's second developer"})
            refused = await _refused(rig, own, "getMyDeveloperProfile", {})
        if refused:
            raise PreconditionUnmet(f"the flow's own developer on {label} cannot sign in: {refused[:160]}")
    return own


async def retire(rig, owners: List[Tuple[str, str]]) -> List[str]:
    """Each developer's own deletion request; the ones that could not be sent, named (never a password)."""
    left = []
    for own, password in owners or []:
        refused = await _refused(rig, own, "requestAccountDeletion",
                                 {"password": password, "confirmation": DELETE_CONFIRM})
        if refused:
            left.append(f"{own}: {refused[:120]}")
    return left
