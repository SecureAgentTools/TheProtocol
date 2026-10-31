"""§MCPTEST30 (V0650, tester batch 1 items 1c and 1d, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6): PHASE 8,
the tools that change the frame itself (its card's icon, the pair's own operators), run last and only on a target torn
down after its run, and adminDownloadOperatorBundle's answer, which named the bundle's first bytes.

Offline: a scripted pair answers as the routes do (routers/admin_registry_card, routers/operator_applications,
routers/operator_self_service's request-frame, routers/admin_email_preview's senders). RED on V0649's code: the module,
the flow's Phase 8 and the bundle's digest do not exist (the import fails; the tool answers encoded_preview_hex).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_ad_pair_last as pl
from agentvault_registry.api_tests.contracts.earned_fixtures import effect_name
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F

ICON_PATH = "/static/registry-cards/spiffe-sbx/icon.png"
HELD = pl.run_png("the frame's own")
TOKEN = "dpt_" + "7f" * 32                      # what a rotation hands out once; it must reach no row
PREVIEW = "1f8b0800" + "c0ffee" * 30            # the first bytes of a bundle, as V0649's tool sent them
ROWS = {t: effect_name(t) for t in (pl.ICON,) + pl.OWN_TOOLS + pl.OPERATOR_TOOLS}


def _body(obj: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                   "structuredContent": obj}}


def _parse(b: Dict[str, Any]) -> Any:
    try:
        return json.loads(b["result"]["content"][0]["text"])
    except Exception:                                                  # noqa: BLE001
        return {}


class _Pair:
    def __init__(self, *, smtp: Optional[bool] = False, held: bool = True, unreadable: bool = False,
                 card_stuck: bool = False, serves_other: bool = False, public_stale: bool = False,
                 put_back_fails: bool = False, preview: bool = False, prefix_stuck: bool = False,
                 suspend_stuck: bool = False, revoke_keeps_token: bool = False, notes_dropped: bool = False,
                 frame_lost: bool = False, operators: int = 1):
        self.smtp, self.card_stuck, self.serves_other, self.public_stale = smtp, card_stuck, serves_other, public_stale
        self.put_back_fails, self.preview, self.prefix_stuck = put_back_fails, preview, prefix_stuck
        self.suspend_stuck, self.revoke_keeps_token = suspend_stuck, revoke_keeps_token
        self.notes_dropped, self.frame_lost = notes_dropped, frame_lost
        self.files: Dict[str, bytes] = {ICON_PATH: (b"not the icon" if unreadable else HELD)} if held else {}
        self.visual: Dict[str, Any] = ({"icon_url": ICON_PATH, "icon_etag": pl.icon_etag(HELD),
                                        "icon_size_bytes": len(HELD)} if held else {})
        self.apps: Dict[str, Dict[str, Any]] = {}
        for i in range(operators):
            self.apps[f"op-{i}"] = {"id": f"op-{i}", "status": "approved", "cloud_hosted": True,
                                    "cloud_torn_down_at": None, "created_at": f"2026-10-31T0{i}:00:00",
                                    "docker_pull_token_prefix": "dpt_aaaa",
                                    "docker_pull_token_issued_at": "2026-10-31T00:00:00"}
        self.frames: Dict[str, Dict[str, Any]] = {}
        self.calls: List[Tuple[str, str]] = []

    def served_visual(self) -> Dict[str, Any]:
        """The visual block as a card serves it: v0.4 strips icon_etag and icon_size_bytes (registry_card_builder)."""
        return {k: v for k, v in self.visual.items() if k not in ("icon_etag", "icon_size_bytes")}

    # ── the admin bridge ─────────────────────────────────────────────────────────────────────────────────────────
    async def admin(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append(("admin", tool))
        ok = lambda obj, code="200": (True, _body(obj), code)        # noqa: E731
        no = lambda why, code="400": (False, _body({"error": f"HTTP {code}: {why}"}), code)   # noqa: E731
        if tool == pl.CARD:
            return ok({"visual": self.served_visual(), "identity": {"registry_name": "pair-a"}})
        if tool == pl.ICON:
            raw = base64.b64decode(args["icon_b64"])
            if self.put_back_fails and raw == HELD:
                return no("disk full", "500")
            if not self.card_stuck:
                self.visual = {"icon_url": ICON_PATH, "icon_etag": pl.icon_etag(raw), "icon_size_bytes": len(raw)}
            self.files[ICON_PATH] = b"some other bytes" if (self.serves_other and raw != HELD) else raw
            return ok({"icon_url": ICON_PATH, "icon_etag": pl.icon_etag(raw), "icon_size_bytes": len(raw),
                       "format": "png"})
        if tool == pl.ADMIN_REQUEST:
            m, ep = args["method"], args["endpoint"]
            if (m, ep) == ("GET", "/api/v1/admin/email/senders"):
                if self.smtp is None:
                    return ok({"status_code": 500, "ok": False, "response": {"detail": "boom"}})
                return ok({"status_code": 200, "ok": True, "response": {"senders": [], "smtp_configured": self.smtp}})
            if (m, ep) == ("POST", "/api/v1/operator-applications"):
                b = args["body"]
                assert b["accept_operator_terms"] is True and b["email"].endswith("@tester.theprotocol.cloud")
                self.apps["own"] = {"id": "own", "status": "pending", "cloud_hosted": False, "name": b["name"],
                                    "created_at": "2026-10-31T05:00:00"}
                return ok({"status_code": 200, "ok": True, "response": dict(self.apps["own"])})
            if m == "GET" and ep.startswith("/api/v1/admin/frame-requests/"):
                fr = self.frames.get(ep.rsplit("/", 1)[1])
                if fr is None or self.frame_lost:
                    return ok({"status_code": 404, "ok": False, "response": {"detail": "Frame request not found"}})
                return ok({"status_code": 200, "ok": True, "response": dict(fr)})
            raise AssertionError((m, ep))
        if tool == pl.APPLICATIONS:
            return ok({"applications": [dict(a) for a in self.apps.values() if a["status"] == args.get("status")],
                       "config": {}})
        a = self.apps.get(str(args.get("application_id")))
        if tool == pl.APPLICATION:
            return ok(dict(a)) if a else no("Application not found.", "404")
        if tool == pl.REJECT:
            a["status"], a["review_notes"] = "rejected", (None if self.notes_dropped else args.get("reason"))
            return ok(dict(a))
        if tool == pl.BUNDLE:
            ans = {"application_id": a["id"], "content_type": "application/gzip", "size_bytes": 4096}
            ans.update({"encoded_preview_hex": PREVIEW} if self.preview else {"sha256": "ab" * 32})
            return ok(ans)
        if tool == pl.ROTATE:
            if a["status"] != "approved":
                return no(f"Cannot rotate token for operator with status '{a['status']}'.")
            if not self.prefix_stuck:
                a["docker_pull_token_prefix"], a["docker_pull_token_issued_at"] = TOKEN[:8], "2026-10-31T05:00:00"
            return ok({"application_id": a["id"], "pull_token": TOKEN, "message": "shown once"})
        if tool == pl.SUSPEND:
            if not self.suspend_stuck:
                a["status"] = "suspended"
            return ok(dict(a))
        if tool == pl.REINSTATE:
            a["status"] = "approved"
            return ok(dict(a))
        if tool == pl.REVOKE:
            a["status"] = "revoked"
            if not self.revoke_keeps_token:
                a["docker_pull_token_prefix"] = None
            return ok(dict(a))
        raise AssertionError(tool)

    # ── the public bridge ────────────────────────────────────────────────────────────────────────────────────────
    async def public(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append(("public", tool))
        if tool == pl.PUBLIC_CARD:
            assert jwt, "the MCP endpoint answers 401 to a call without a token, a public tool's too"
            return True, _body({"visual": {"icon_url": "/static/registry-cards/spiffe-sbx/icon.jpg"} if self.public_stale
                                else self.served_visual()}), "200"
        if tool == pl.REQUEST_FRAME:
            d = args["request_data"]
            assert d["accept_terms"] is True and d["create_account"] is False
            self.frames["fr-1"] = {"id": "fr-1", "status": "pending", "contact_email": d["email"]}
            return True, _body({"submitted": True, "account_created": False, "magic_link_sent": False,
                                "receipt_sent": False, "request_id": "fr-1"}), "200"
        raise AssertionError(tool)

    async def b64(self, path: str) -> Tuple[str, str]:
        raw = self.files.get(path)
        return ("200", base64.b64encode(raw).decode()) if raw is not None else ("404", "")


def _run(p: _Pair, monkeypatch, *, ephemeral: bool = True, b64: bool = True) -> Dict[str, dict]:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    if ephemeral:
        monkeypatch.setenv(pl.EPHEMERAL_ENV, "true")
    else:
        monkeypatch.delenv(pl.EPHEMERAL_ENV, raising=False)

    async def fast(_s):
        return None
    monkeypatch.setattr(pl.asyncio, "sleep", fast)
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    bag.rpc_admin = p.admin                    # type: ignore[attr-defined]
    if b64:
        bag.http_b64_in_target = p.b64         # type: ignore[attr-defined]
    return asyncio.run(pl.run_last(p.public, _parse, bag))


def _ok(row: Optional[dict]) -> bool:
    return bool(row) and bool(row.get("healthy")) and not row.get("skip_reason") and not row.get("fail_reason")


def test_a_standing_frame_changes_nothing_and_says_why(monkeypatch):
    p = _Pair()
    rows = _run(p, monkeypatch, ephemeral=False)
    assert p.calls == []
    assert set(ROWS.values()) <= set(rows)
    assert all(pl.EPHEMERAL_ENV in str(rows[n].get("skip_reason")) for n in ROWS.values())


def test_a_pair_earns_all_eight_and_puts_the_icon_back(monkeypatch):
    p = _Pair()
    rows = _run(p, monkeypatch)
    for tool, name in ROWS.items():
        assert _ok(rows.get(name)), (tool, rows.get(name))
    assert p.visual["icon_url"] == ICON_PATH and p.files[ICON_PATH] == HELD   # the frame's icon is back, served
    admin_calls = [t for b, t in p.calls if b == "admin"]
    assert admin_calls.index(pl.REVOKE) > max(admin_calls.index(t) for t in (pl.BUNDLE, pl.ROTATE, pl.SUSPEND,
                                                                             pl.REINSTATE, pl.REJECT))
    assert p.apps["op-0"]["status"] == "revoked" and p.apps["own"]["status"] == "rejected"
    blob = json.dumps(rows, default=str)
    assert TOKEN not in blob and TOKEN[4:20] not in blob, "the rotated token reached a row"
    assert rows[ROWS[pl.BUNDLE]]["result_excerpt"]["bytes_kept"] == "none"


def test_only_where_the_target_mails_nobody(monkeypatch):
    for smtp, said in ((True, "smtp_configured true"), (None, "could not be read")):
        p = _Pair(smtp=smtp)
        rows = _run(p, monkeypatch)
        assert _ok(rows[ROWS[pl.ICON]])
        for tool in (pl.REQUEST_FRAME, pl.REJECT) + pl.OPERATOR_TOOLS:
            why = str(rows[ROWS[tool]].get("skip_reason"))
            assert "commander address" in why and said in why, (tool, why)
        assert not {t for _b, t in p.calls} & {pl.REQUEST_FRAME, pl.REJECT, pl.SUSPEND, pl.REVOKE, pl.ROTATE}


def test_no_operator_of_its_own_is_said(monkeypatch):
    rows = _run(_Pair(operators=0), monkeypatch)
    assert _ok(rows[ROWS[pl.REJECT]]) and _ok(rows[ROWS[pl.REQUEST_FRAME]])
    for tool in pl.OPERATOR_TOOLS:
        assert "no approved cloud-hosted operator" in str(rows[ROWS[tool]].get("skip_reason")), tool


@pytest.mark.parametrize("defect,tool,needle", [
    ({"card_stuck": True, "held": False}, pl.ICON, "admin card names no icon afterwards"),
    ({"serves_other": True}, pl.ICON, "other bytes, not the run's icon"),
    ({"public_stale": True}, pl.ICON, "public registry card names the icon at"),
    ({"put_back_fails": True}, pl.ICON, "did not come back"),
    ({"preview": True}, pl.BUNDLE, "first bytes (encoded_preview_hex)"),
    ({"prefix_stuck": True}, pl.ROTATE, "prefix did not move"),
    ({"suspend_stuck": True}, pl.SUSPEND, "not 'suspended'"),
    ({"revoke_keeps_token": True}, pl.REVOKE, "pull token still set"),
    ({"notes_dropped": True}, pl.REJECT, "review_notes=None"),
    ({"frame_lost": True}, pl.REQUEST_FRAME, "HTTP 404"),
])
def test_each_defect_is_a_finding_on_its_tool(monkeypatch, defect, tool, needle):
    rows = _run(_Pair(**defect), monkeypatch)
    row = rows[ROWS[tool]]
    assert not row["healthy"] and needle in str(row.get("fail_reason")), row
    assert PREVIEW not in json.dumps(rows, default=str), "a byte of the bundle reached a row"
    if defect == {"suspend_stuck": True}:
        assert "no suspended operator to reinstate" in str(rows[ROWS[pl.REINSTATE]].get("skip_reason"))


def test_an_icon_it_cannot_put_back_is_never_replaced(monkeypatch):
    p = _Pair(unreadable=True)
    rows = _run(p, monkeypatch)
    assert "could not be read whole" in str(rows[ROWS[pl.ICON]].get("skip_reason"))
    assert ("admin", pl.ICON) not in p.calls
    rows = _run(_Pair(), monkeypatch, b64=False)
    assert "bag.http_b64_in_target" in str(rows[ROWS[pl.ICON]].get("skip_reason"))


def test_a_card_without_an_icon_keeps_the_runs_and_says_so(monkeypatch):
    p = _Pair(held=False)
    rows = _run(p, monkeypatch)
    assert _ok(rows[ROWS[pl.ICON]]) and "no route removes one" in rows[ROWS[pl.ICON]]["result_excerpt"]["put_back"]


def test_two_runs_never_upload_the_same_icon():
    a, b = pl.run_png("1-aa"), pl.run_png("1-ab")
    assert a.startswith(pl.PNG_SIGNATURE) and b.startswith(pl.PNG_SIGNATURE) and pl.icon_etag(a) != pl.icon_etag(b)
    from agentvault_registry.core.image_sniff import sniff_image_format
    assert sniff_image_format(a) == "png"


def test_phase8_rows_keep_every_row_once_and_never_under_a_tool_name():
    rows = {effect_name(pl.ICON): {"healthy": True}, "refusal: requestFrame a body": {"healthy": False},
            "theprotocol_revokeOperatorAccess": {"healthy": False}, "admin_effect: suspendOperator": {}}
    kept = dict(pl.phase8_rows(rows, {"admin_effect: suspendOperator", "theprotocol_revokeOperatorAccess"}))
    assert set(kept) == {effect_name(pl.ICON), "refusal: requestFrame a body", effect_name(pl.REVOKE)}
    # both prefixes are kept by the runner and placed by the console (tests/test_mcp_row_prefixes.py)
    assert all(p in F._SYNTHETIC_ROW_PREFIXES for p in pl.PHASE8_PREFIXES)


def test_the_flow_runs_phase8_after_phase7_and_before_the_census():
    src = inspect.getsource(F)
    p7 = src.index("_phase7_enforcement_refusal(target, bag, dev_jwt)")
    p8 = src.index("_last.run_last(_rpc, _parse_rpc_result, bag)")
    census = src.index("_credential_census_close(outcomes, _census_token)")
    assert p7 < p8 < census
    assert "bag.http_b64_in_target = functools.partial(_http_get_b64_in_target" in inspect.getsource(F)


def test_no_cloud_operator_sweep_runs_them():
    from agentvault_registry.api_tests.contracts import mcp_lifecycles
    runners = {lc["runner"] for lc in mcp_lifecycles.LIFECYCLES}
    assert not runners & {lc["runner"] for lc in pl.LAST_LIFECYCLES}


def test_the_b64_transport_takes_a_plain_path_only():
    assert asyncio.run(F._http_get_b64_in_target("c", "/x'; rm -rf /")) == ("", "")


def test_the_bundle_tool_names_the_bundle_never_its_bytes(monkeypatch):
    from agentvault_registry.mcp import tools_admin as T
    content = bytes.fromhex(PREVIEW) * 3

    class _Resp:
        status_code, headers = 200, {"content-type": "application/gzip"}

        def __init__(self):
            self.content = content

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            assert url.endswith("/api/v1/admin/operator-applications/op-0/bundle")
            return _Resp()
    monkeypatch.setattr(T, "require_admin_auth", lambda auth: None)
    monkeypatch.setattr(T, "_get_effective_jwt", lambda auth: "jwt")
    monkeypatch.setattr(T, "get_httpx_verify", lambda: True)
    monkeypatch.setattr(T.httpx, "AsyncClient", _Client)
    ans = asyncio.run(T.admin_download_operator_bundle(None, "op-0"))
    assert ans == {"application_id": "op-0", "content_type": "application/gzip", "size_bytes": len(content),
                   "sha256": hashlib.sha256(content).hexdigest()}
    assert content[:16].hex() not in json.dumps(ans)


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
