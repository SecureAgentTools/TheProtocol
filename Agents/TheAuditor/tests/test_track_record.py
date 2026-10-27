"""§MEMBERSHIP phase D1 (2026-10-02, agentvault2-33): the registry track record, measured from outside and signed here.

What these pin: each component counts only what it observed (an unreadable cycle is not a breach, an unreadable licence
read is not a bad day), the caps (public readings only; a breach open more than a day), the renormalisation when a
component has nothing measured, the provisional label, the operator's OWN licence (the `operator` block, not its frame's),
the signed chain `track_record:<registry>` with its prev_hash, the carrier as the only switch, and the line the design
draws: nothing held, locked or paid, and no peer verdict, ever reaches the score.
AUDITOR_TREE points the suite at another checkout of Agents/TheAuditor (a base run).
"""
import ast
import asyncio
import base64
import hashlib
import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture()
def main(tmp_path, monkeypatch):
    _purge()
    for k in list(os.environ):
        if k.endswith("_EVENT_STORE_URL") or k.endswith("_ES_DSN") or (k.startswith("AUDITOR_") and k != "AUDITOR_TREE"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONTEND_DIR", os.path.join(TREE, "frontend"))
    monkeypatch.setenv("AUDITOR_TRACK_RECORD_FILE", str(tmp_path / "track_record.json"))
    monkeypatch.syspath_prepend(TREE)
    module = importlib.import_module("src.auditor.main")
    asyncio.run(module.db.init_db())
    asyncio.run(module.track_record.init_db())
    yield module
    _purge()


@pytest.fixture()
def tr(main):
    return main.track_record


def P(ts, health=200, card=200, card_ok=1, signed_age_min=1.0, kid="k#1", commitments=None, licence_ok=1, locked_ok=1):
    t = ts if isinstance(ts, datetime) else NOW - timedelta(hours=ts)
    return {"ts": t.isoformat(), "health_status": health, "card_status": card, "card_ok": card_ok,
            "signed_at": (t - timedelta(minutes=signed_age_min)).isoformat(), "kid": kid,
            "commitments": json.dumps(commitments if commitments is not None else
                                      {"uptime_sla_pct": 99.0, "card_refresh_max_minutes": 5, "key_rotation_max_days": 90,
                                       "support_response_hours": 72}),
            "licence_ok": licence_ok, "locked_ok": locked_ok}


REG = {"name": "sbx-alpha", "kind": "frame", "base": "https://sandbox-a.example.test", "frame": "sbx-alpha",
       "issuer_base": "https://sandbox-a.example.test"}


# ── components ──────────────────────────────────────────────────────────────

def test_integrity_counts_only_readable_cycles_and_caps(tr):
    got = tr.integrity_component({"ok": 90, "breach": 10, "total": 130, "public_only": False}, False)
    assert got["value"] == 0.9 and got["unread_cycles"] == 30, "an unreadable cycle is not a breach"
    assert tr.integrity_component({"ok": 100, "breach": 0, "total": 100, "public_only": True}, False)["value"] == 0.5
    capped = tr.integrity_component({"ok": 100, "breach": 0, "total": 100, "public_only": False}, True)
    assert capped["value"] == 0.5 and "more than 24 hours" in capped["cap_reason"]
    assert tr.integrity_component({"ok": 0, "breach": 0, "total": 12, "public_only": False}, False)["value"] is None
    assert tr.integrity_component(None, False)["value"] is None


def test_availability_needs_both_answers_and_a_parsed_card(tr):
    probes = [P(1), P(2, health=503), P(3, card=500, card_ok=0), P(4, card_ok=0)]
    got = tr.availability_component(probes)
    assert got == {"value": 0.25, "probes": 4, "answered": 1}
    assert tr.availability_component([])["value"] is None


def test_promises_measure_what_can_be_measured_and_name_the_rest(tr):
    probes = [P(h) for h in range(1, 101)]
    got = tr.promises_component(probes, {"k#1": (NOW - timedelta(days=10)).isoformat()}, 1.0, NOW)
    by = {m["commitment"]: m for m in got["measured"]}
    assert set(by) == {"uptime_sla_pct", "card_refresh_max_minutes", "key_rotation_max_days"}
    assert all(m["held"] for m in by.values()) and got["value"] == 1.0
    assert got["not_measured"] == ["support_response_hours"]
    stale = [P(h, signed_age_min=30 if h <= 2 else 1) for h in range(1, 101)]          # 2 % stale reads
    got = tr.promises_component(stale, {"k#1": (NOW - timedelta(days=200)).isoformat()}, 0.98, NOW)
    by = {m["commitment"]: m for m in got["measured"]}
    assert not by["card_refresh_max_minutes"]["held"] and not by["key_rotation_max_days"]["held"]
    assert not by["uptime_sla_pct"]["held"] and got["value"] == 0.0
    assert tr.promises_component([P(1, card_ok=0)], {}, 1.0, NOW)["value"] is None, "no card read, nothing measured"


def test_conduct_counts_days_and_skips_what_could_not_be_read(tr):
    probes = [P(1), P(2), P(30, licence_ok=0), P(31), P(55, licence_ok=None, locked_ok=None), P(80, locked_ok=0)]
    got = tr.conduct_component(probes)
    assert got["days_counted"] == 3 and got["days_good"] == 1, got      # day 0 good; day -1 licence bad; day -3 drift
    assert got["licence_bad_days"] == 1 and got["locked_drift_days"] == 1 and got["value"] == round(1 / 3, 4)
    assert tr.conduct_component([P(1, licence_ok=None, locked_ok=None)])["value"] is None


def test_the_score_renormalises_over_what_was_measured_and_is_provisional_early(tr):
    probes = [P(h) for h in range(1, 49)]                                 # two days observed
    rec = tr.score_record(reg=REG, now=NOW, integrity_counts=None, long_breach=False, probes=probes,
                          kids={"k#1": (NOW - timedelta(days=3)).isoformat()})
    assert rec["components"]["integrity"]["value"] is None and rec["renormalised"] is True
    assert rec["score"] == 100.0 and rec["provisional"] is True and rec["observed_days"] == 3
    full = tr.score_record(reg=REG, now=NOW, integrity_counts={"ok": 50, "breach": 50, "total": 100, "public_only": False},
                           long_breach=False, probes=probes, kids={"k#1": (NOW - timedelta(days=3)).isoformat()})
    assert full["score"] == 80.0 and full["renormalised"] is False        # 40*0.5 + 30 + 20 + 10


def test_an_operator_is_judged_by_its_own_licence_not_its_frames(tr):
    listing = {"payload": {"licences": [{"hash": "aaaa" * 16, "state": "active", "exp": None},
                                        {"hash": "bbbb" * 16, "state": "revoked", "exp": None},
                                        {"hash": "cccc" * 16, "state": "active", "exp": "1000"}]}}
    frame_doc = {"hash": "aaaa" * 16, "state": "genesis"}
    op_doc = {"hash": "aaaa" * 16, "operator": {"hash": "bbbb" * 16, "state": "licensed"}}
    assert tr.licence_verdict("frame", frame_doc, listing, NOW) == (True, "listed active")
    assert tr.licence_verdict("operator", op_doc, listing, NOW) == (False, "listed revoked"), "the frame's licence does not cover it"
    assert tr.licence_verdict("operator", {"hash": "aaaa" * 16}, listing, NOW) == (False, "no licence published")
    assert tr.licence_verdict("frame", {"hash": "dddd" * 16}, listing, NOW) == (False, "not listed by its issuer")
    assert tr.licence_verdict("frame", {"hash": "cccc" * 16}, listing, NOW) == (False, "expired")
    assert tr.licence_verdict("frame", frame_doc, None, NOW) == (None, "unreadable")


# ── the carrier is the switch ───────────────────────────────────────────────

def test_the_carrier_is_the_only_switch(tr, tmp_path):
    path = tmp_path / "track_record.json"
    assert tr.load_carrier(path) == {}, "no file: off"
    path.write_text("{not json")
    assert tr.load_carrier(path) == {}, "an unparsable carrier applies nothing"
    path.write_text(json.dumps({"network_base": "https://root.example.test/", "registries": [
        {"name": "a", "base": "https://a.example.test/"}, {"name": "a", "base": "https://dup.example.test"},
        {"name": "plain", "base": "http://plain.example.test"}, {"name": "op", "kind": "operator",
                                                                  "base": "https://op.example.test", "frame": "a",
                                                                  "issuer_base": "https://a.example.test"}]}))
    cfg = tr.load_carrier(path)
    assert [r["name"] for r in cfg["registries"]] == ["a", "op"], "duplicates and plain http are refused"
    assert cfg["registries"][0]["issuer_base"] == "https://root.example.test" and cfg["probe_seconds"] == 300
    assert cfg["registries"][1]["kind"] == "operator" and cfg["registries"][1]["frame"] == "a"


# ── observation, through a real client against a fake network ──────────────

def _network(routes):
    def handler(request):
        got = routes.get(str(request.url))
        if got is None:
            return httpx.Response(404, json={"detail": "Not Found"})
        status, body = got
        return httpx.Response(status, json=body) if not isinstance(body, str) else httpx.Response(status, text=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_a_probe_records_what_it_saw(main, tr):
    base = "https://op.example.test"
    card = {"identity": {"registry_name": "op"}, "signature": {"signed_at": NOW.isoformat(), "kid": "spiffe://x/registry/op#1"},
            "commitments": {"uptime_sla_pct": 99.0}, "policy": {"locked_params_hash": "sha256:L"}}
    routes = {
        "https://root.example.test/.well-known/registry-card.json": (200, {**card, "policy": {"locked_params_hash": "sha256:L"}}),
        "https://issuer.example.test/.well-known/federation-licences.json": (200, {"payload": {"licences": [
            {"hash": "e" * 64, "state": "active", "exp": None}]}}),
        f"{base}/health": (200, {"status": "ok"}),
        f"{base}/.well-known/registry-card.json": (200, card),
        f"{base}/.well-known/federation-licence.json": (200, {"hash": "f" * 64, "operator": {"hash": "e" * 64}}),
    }
    cfg = {"network_base": "https://root.example.test", "registries": [
        {"name": "op", "kind": "operator", "base": base, "frame": "sbx-beta", "issuer_base": "https://issuer.example.test"}]}

    async def go():
        async with _network(routes) as client:
            return await tr.probe_all(cfg, client)
    row = asyncio.run(go())[0]
    assert row["health_status"] == 200 and row["card_ok"] == 1 and row["kid"].endswith("#1")
    assert row["licence_ok"] == 1 and row["licence_detail"] == "listed active" and row["locked_ok"] == 1
    routes[f"{base}/.well-known/registry-card.json"] = (200, "<html>the app</html>")
    routes[f"{base}/health"] = (502, {"detail": "bad gateway"})

    async def go2():
        async with _network(routes) as client:
            return await tr.probe_all(cfg, client)
    row = asyncio.run(go2())[0]
    assert row["health_status"] == 502 and row["card_ok"] == 0 and row["locked_ok"] is None
    stored = asyncio.run(tr._window_probes("op", (NOW - timedelta(days=400)).isoformat()))
    assert len(stored) == 2


def test_each_registry_is_compared_with_its_own_network_root(main, tr, tmp_path):
    """§MEMBERSHIP (2026-10-03): the sandbox and production share one carrier; a registry's locked parameters are compared
    with ITS network root's, never the file's other network (both hashed the same that day, so only a test sees it)."""
    path = tmp_path / "track_record.json"
    path.write_text(json.dumps({"network_base": "https://sbx-root.example.test", "registries": [
        {"name": "sbx", "base": "https://sbx.example.test"},
        {"name": "prod", "base": "https://prod.example.test", "network_base": "https://prod-root.example.test/"}]}))
    cfg = tr.load_carrier(path)
    assert [r["network_base"] for r in cfg["registries"]] == ["https://sbx-root.example.test", "https://prod-root.example.test"]

    def card(h):
        return {"identity": {"registry_name": "x"}, "signature": {"signed_at": NOW.isoformat(), "kid": "spiffe://x/registry/x#1"},
                "commitments": {}, "policy": {"locked_params_hash": h}}
    routes = {
        "https://sbx-root.example.test/.well-known/registry-card.json": (200, card("sha256:SBX")),
        "https://prod-root.example.test/.well-known/registry-card.json": (200, card("sha256:PROD")),
        "https://sbx.example.test/health": (200, {"status": "ok"}),
        "https://sbx.example.test/.well-known/registry-card.json": (200, card("sha256:SBX")),
        "https://prod.example.test/health": (200, {"status": "ok"}),
        "https://prod.example.test/.well-known/registry-card.json": (200, card("sha256:PROD")),
    }

    async def go():
        async with _network(routes) as client:
            return await tr.probe_all(cfg, client)
    rows = {r["registry"]: r for r in asyncio.run(go())}
    assert rows["sbx"]["locked_ok"] == 1 and rows["prod"]["locked_ok"] == 1, "each against its own root"
    routes["https://prod.example.test/.well-known/registry-card.json"] = (200, card("sha256:SBX"))
    rows = {r["registry"]: r for r in asyncio.run(go())}
    assert rows["prod"]["locked_ok"] == 0, "the production registry drifted from its OWN root, even though it equals the other's"


# ── signed, chained, kept ───────────────────────────────────────────────────

def _insert_audits(main, frame, rows):
    import sqlite3
    c = sqlite3.connect(str(main.db.DB_PATH))
    for ts, status, atomic, maint, source in rows:
        c.execute("INSERT INTO audit_history (timestamp, tokens_issued, total_circulating, delta, status, response_ms, frame, "
                  "atomic_status, maintenance, source) VALUES (?, 0, 0, 0, ?, 1, ?, ?, ?, ?)",
                  (ts.isoformat(), status, frame, atomic, maint, source))
    c.commit()
    c.close()


def test_a_record_is_signed_into_its_own_chain(main, tr, tmp_path):
    now = datetime.now(timezone.utc)
    _insert_audits(main, "sbx-alpha", [(now - timedelta(hours=1), "OK", "OK", 0, "audit"),
                                       (now - timedelta(hours=2), "ERROR", None, 0, "audit"),
                                       (now - timedelta(hours=3), "BREACH", "BREACH", 0, "audit"),
                                       (now - timedelta(days=40), "BREACH", "BREACH", 0, "audit")])   # outside the window
    for h in (1, 2):
        row = {"registry": "sbx-alpha", **P(now - timedelta(hours=h))}
        asyncio.run(tr._store_probe(row))
    key = main.attest.load_or_create(tmp_path)
    lock = asyncio.Lock()

    async def twice():
        return (await tr.compute_and_record(REG, key, lock, "test"), await tr.compute_and_record(REG, key, lock, "test"))
    first, second = asyncio.run(twice())
    integ = first["components"]["integrity"]
    assert (integ["ok_cycles"], integ["breach_cycles"], integ["unread_cycles"], integ["value"]) == (1, 1, 1, 0.5)
    rows = asyncio.run(main.db.get_attestations(frame="track_record:sbx-alpha"))
    assert [r["kind"] for r in rows] == ["track_record", "track_record"]
    newest, oldest = rows
    assert oldest["prev_hash"] == "" and newest["prev_hash"] == oldest["digest"], "the chain links"
    for r in rows:
        assert hashlib.sha256(r["payload"].encode()).hexdigest() == r["digest"]
        sig = base64.urlsafe_b64decode(r["signature"] + "=" * (-len(r["signature"]) % 4))
        Ed25519PublicKey.from_public_bytes(key.pub_raw).verify(sig, r["payload"].encode())
    body = json.loads(newest["payload"])
    assert body["kind"] == "track_record" and body["registry"] == "sbx-alpha" and body["formula_version"] == "tr-1"
    assert asyncio.run(main.db.get_attestations(frame="sbx-alpha")) == [], "a frame's own audit chain is untouched"
    view = asyncio.run(tr.latest_view())
    assert [r["attestation_id"] for r in view["records"]] == [second["attestation_id"]] and view["enabled"] is False
    assert len(asyncio.run(tr.history_view("sbx-alpha", 30))["records"]) == 2


def test_the_admin_compute_route_is_gated_and_off_without_a_carrier(main, monkeypatch, tmp_path):
    assert asyncio.run(main.api_track_record_compute(x_auditor_admin=None)).status_code == 503
    monkeypatch.setattr(main, "AUDITOR_ADMIN_TOKEN", "t" * 32)
    assert asyncio.run(main.api_track_record_compute(x_auditor_admin="wrong")).status_code == 401
    resp = asyncio.run(main.api_track_record_compute(x_auditor_admin="t" * 32))
    assert resp.status_code == 409 and b"the track record is off" in resp.body
    routes = [r.path for r in main.app.routes]
    assert routes.index("/api/auditor/track-record") < routes.index("/{full_path:path}"), "above the SPA catch-all"


def test_a_failed_cycle_never_ends_the_loop(tr, monkeypatch):
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("carrier exploded")
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError
    monkeypatch.setattr(tr, "load_carrier", boom)
    monkeypatch.setattr(tr.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tr.run_forever(None, asyncio.Lock(), "test"))
    assert calls["n"] == 2 and sleeps == [20, 300, 300], "it failed twice and kept going"


# ── the line: nothing held, locked or paid, and no peer verdict ─────────────

FORBIDDEN = {"staked_balance", "liquid_balance", "token_balance", "locked_balance", "total_circulating",
             "bayesian_discount", "disputes_lost_with", "agora", "share_positions", "voting_power"}


def _violations(src):
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN:
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
            found.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            low = node.value.lower()
            if "select " in low and " from " in low:        # SQL, not prose: a docstring may say "from outside"
                found += [f"sql:{w}" for w in FORBIDDEN if w in low]
    return found


def test_the_score_reads_nothing_held_and_no_peer_verdict():
    src = open(os.path.join(TREE, "src", "auditor", "track_record.py"), encoding="utf-8").read()
    assert _violations(src) == [], _violations(src)
    for planted in ("x = row.staked_balance\n", "q = 'SELECT bayesian_discount FROM federation_operators'\n"):
        assert _violations(planted), planted
