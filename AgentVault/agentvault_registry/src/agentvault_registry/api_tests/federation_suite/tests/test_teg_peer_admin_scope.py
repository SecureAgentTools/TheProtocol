"""A peer frame's registry is an admin on this frame's TEG only where it has a designed use (§MCPTEST30, V0546).

The TEG grants its admin role by identity CLASS: core/internal_auth.is_internal_service_identity accepts
/service/*registry*, /service/teg-* and /operator/* of ANY trust domain in TRUSTED_SPIFFE_DOMAINS, and each frame's TEG
trusts its FX peer's domain for the cross-frame pool: the peer's registry reads /admin/fx/reserve and moves /admin/fx/move
(measured on production 2026-10-02: EU's TEG accepted ASIA's registry 893 and 29 times in 24 h, and the reverse).
nginx-teg forwards every /api/v1/ path with its proxy marker and holds no per-identity path rule. So the peer's registry
is an admin on EVERY admin route of this frame's TEG (treasury, fee collector, exchange moves, reward funding), where its
designed use is two routes (and the cross-TEG 2PC, a separate router). SCOPED since 2026-10-07 (his word "2. yes fix";
§TEGSCOPE, TEG agentvault2-teg-layer:adminscope1 on every frame: a peer keeps GET fx/reserve and POST fx/move only),
so this row is no longer an expected red: it is the regression guard, and a TEG without the scope fails it.

From inside sandbox-B's registry, with its own SVID and the frame's bundles, the flow reads three admin routes on
sandbox-A's TEG through sandbox-A's nginx-teg (the address sandbox-B's TEG_SIDECAR_MAP names): the designed one (the
control: it must answer, or the probe proved nothing) and two a peer has no use for. Read-only: three GETs, no value.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet, SANDBOX_REGISTRIES,
)
from agentvault_registry.api_tests.multiframe_helpers import exec_in_container

# the caller: sandbox-B's registry, with its own SVID (the rig names its container: API_TEST_FED_B_CONTAINER)
_PEER = "sandbox-B"
_HOME_TEG_KEY = "teg-layer-sandbox-alpha"   # how sandbox-B's TEG_SIDECAR_MAP names sandbox-A's TEG

# (name, path, designed): the designed route is the control
CALLS: List[Tuple[str, str, bool]] = [
    ("fx_reserve", "/api/v1/admin/fx/reserve", True),
    ("treasury_info", "/api/v1/admin/treasury/info", False),
    ("fee_collector_info", "/api/v1/admin/fee-collector/info", False),
]

# Runs INSIDE the peer's registry container: its own SVID, the frame's bundles, the sidecar its own map names. Prints one
# line per call: the status and the detail's first words; never a balance, the certificate or the key.
_PROBE = r'''
import glob, json, os, ssl, sys
import httpx
calls, key = json.loads(sys.argv[1]), sys.argv[2]
host = (json.loads(os.environ.get("TEG_SIDECAR_MAP") or "{}")).get(key)
if not host:
    print(json.dumps({"name": "_target", "error": "no sidecar", "msg": "TEG_SIDECAR_MAP names no " + key}))
    sys.exit(0)
target = host if host.startswith("https://") else "https://" + host + ":8443"
print(json.dumps({"name": "_target", "target": target}))
ctx = ssl.create_default_context()
ctx.check_hostname = False   # a SPIFFE certificate names a URI, not a host; the chain is what is verified
for pem in ["/certs/bundle.0.pem"] + sorted(glob.glob("/certs/federated_bundle.*.pem")):
    ctx.load_verify_locations(pem)
ctx.load_cert_chain("/certs/svid.0.pem", "/certs/svid.0.key")
with httpx.Client(verify=ctx, timeout=20) as c:
    for name, path, _designed in calls:
        try:
            r = c.get(target + path)
            try:
                b = r.json()
            except ValueError:
                b = None
            detail = b.get("detail") if isinstance(b, dict) else None
            print(json.dumps({"name": name, "status": r.status_code,
                              "detail": str(detail)[:160] if detail is not None else None}))
        except Exception as e:
            print(json.dumps({"name": name, "error": type(e).__name__, "msg": str(e)[:160]}))
'''


def read_answers(out: str) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for line in (out or "").splitlines():
        if line.startswith("{"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[str(r.get("name"))] = r
    return rows


def verdict(rows: Dict[str, Dict[str, Any]]) -> Tuple[bool, str, Dict[str, Any]]:
    """(passed, sentence, evidence). Raises PreconditionUnmet when the probe could not decide."""
    tgt = rows.get("_target") or {}
    if tgt.get("error") or not tgt.get("target"):
        raise PreconditionUnmet(f"the peer's sidecar address is unknown: {tgt.get('msg') or 'the probe printed none'}")
    ev = {n: {"status": (rows.get(n) or {}).get("status"), "detail": (rows.get(n) or {}).get("detail"),
              "error": (rows.get(n) or {}).get("error")} for n, _p, _d in CALLS}
    ev["target"] = tgt["target"]
    control = rows.get(CALLS[0][0]) or {}
    if control.get("status") != 200:
        raise PreconditionUnmet(
            f"the designed peer read ({CALLS[0][1]}) did not answer 200 to the peer's SVID "
            f"({control.get('status') or control.get('error')}: {control.get('detail') or control.get('msg')}): the probe "
            "cannot tell a scoped TEG from one it never reached")
    admitted = [p for n, p, designed in CALLS if not designed and (rows.get(n) or {}).get("status") == 200]
    unclear = [p for n, p, designed in CALLS if not designed and (rows.get(n) or {}).get("status") not in (200, 401, 403)]
    if admitted:
        return False, ("BUG-FIND: sandbox-B's registry is an admin on sandbox-A's TEG beyond its designed routes: "
                       + ", ".join(f"GET {p} answered 200" for p in admitted)
                       + " to the peer's SVID (the TEG grants admin by identity class, not by frame)"), ev
    if unclear:
        raise PreconditionUnmet(f"an undesigned admin route answered neither 200 nor a refusal: {unclear} ({ev})")
    return True, "the peer's SVID reads its designed route and is refused on the admin routes it has no use for", ev


@federation_test(
    name="teg_admin_is_scoped_for_a_peer_frame",
    category="federation_caller_binding",
    budget_sec=60.0,
    severity="high",
    requires=["sandbox-A", "sandbox-B"],
    tags=["federation", "security", "teg", "mtls", "read-only"],
)
async def test_teg_admin_scoped_for_a_peer(rig: FederationTestRig) -> AssertionResult:
    t0 = time.monotonic()
    peer = SANDBOX_REGISTRIES[_PEER].container
    rc, out = exec_in_container(peer, ["python", "-c", _PROBE, json.dumps(CALLS), _HOME_TEG_KEY],
                                timeout=90)
    rows = read_answers(out)
    if not rows:
        raise PreconditionUnmet(f"the probe ran nothing in {peer!r} (rc={rc}): {(out or '')[:200]}")
    passed, sentence, ev = verdict(rows)
    return AssertionResult(passed=passed, description=sentence, budget_sec=0.0,
                           elapsed_sec=time.monotonic() - t0, polling_attempts=1, last_state=ev,
                           failure_detail=None if passed else json.dumps(ev))
