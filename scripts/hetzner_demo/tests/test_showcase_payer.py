"""§SHOWCASEPAY (2026-09-26): a frame that runs showcase agents is born with its own funded payer.

Measured before: every call on EU from /services, the runner embedded in /blueprints, the landing page and /monetize
answered 402. The rail logs in as SHOWCASE_PPAO_CLIENT_ID / _SECRET, which no standup ever set (login 422, no token,
the agent refused), and its fallback relay named api.theprotocol.cloud, which since the apex moved is EU itself (502).
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
from decimal import Decimal

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import standup_extras as extras  # noqa: E402


def _driver():
    spec = importlib.util.spec_from_file_location("standup_driver_for_test", _HERE.parent / "standup_driver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_env_lines_name_the_payer_and_turn_the_self_relay_off():
    lines = dict(extras.showcase_payer_env_lines({"did": "did:x", "client_id": "cid", "client_secret": "sec"}))
    assert lines == {"SHOWCASE_PPAO_DID": "did:x", "SHOWCASE_PPAO_CLIENT_ID": "cid",
                     "SHOWCASE_PPAO_CLIENT_SECRET": "sec", "SHOWCASE_RELAY_URL": ""}


def test_mint_returns_the_credential_and_never_logs_it(monkeypatch, capsys):
    calls = []

    def fake_http(method, url, body=None, headers=None, timeout=30, form=False):
        calls.append((url, body, headers))
        if url.endswith("/bootstrap/request-token"):
            return 200, {"bootstrap_token": "bt"}
        return 200, {"agent_did": "did:theprotocol:eu.theprotocol.cloud:abcdef123456", "client_id": "cid-1",
                     "client_secret": "S3CRET-VALUE-xyz"}

    monkeypatch.setattr(extras, "http", fake_http)
    out = extras.mint_showcase_payer("http://127.0.0.1:8350", {"Authorization": "Bearer j"}, "eu", "ECU",
                                     public_url="https://eu.theprotocol.cloud")
    assert out == {"did": "did:theprotocol:eu.theprotocol.cloud:abcdef123456", "client_id": "cid-1",
                   "client_secret": "S3CRET-VALUE-xyz"}
    assert "S3CRET-VALUE-xyz" not in capsys.readouterr().out, "the one-time secret must never reach a log"
    card = calls[1][1]["agent_card"]
    assert card["url"] == "https://eu.theprotocol.cloud/api/v1/public/showcase/agents", "a served address (§CARDLINK)"
    assert calls[1][2] == {"Bootstrap-Token": "bt"}


def test_a_refused_mint_returns_nothing(monkeypatch):
    monkeypatch.setattr(extras, "http", lambda *a, **k: (403, {"detail": "no"}))
    assert extras.mint_showcase_payer("http://r", {}, "eu", "ECU") == {}


def test_funding_goes_in_pieces_with_one_key_each_and_stops_on_a_refusal(monkeypatch):
    seen = []

    def ok_http(method, url, body=None, headers=None, timeout=30, form=False):
        seen.append((body["amount"], headers["Idempotency-Key"]))
        return 200, {}

    monkeypatch.setattr(extras, "http", ok_http)
    assert extras.fund_agent_in_pieces("http://r", {"Authorization": "a"}, "did:x", "12", "5", "ref") == Decimal("12")
    assert [a for a, _ in seen] == ["5", "5", "2"] and len({k for _, k in seen}) == 3

    n = {"calls": 0}

    def refuse_second(method, url, body=None, headers=None, timeout=30, form=False):
        n["calls"] += 1
        return (200, {}) if n["calls"] == 1 else (403, {"detail": "no"})

    monkeypatch.setattr(extras, "http", refuse_second)
    assert extras.fund_agent_in_pieces("http://r", {}, "did:x", "12", "5", "ref") == Decimal("5")


def test_an_env_value_is_written_literally():
    """re.sub reads backslashes and group references in a replacement STRING; the upsert must not."""
    d = _driver()
    before = "A=1\nKEY=old\nB=2\n"
    after = d.upsert_env_line(before, "KEY", r"v\1\g<0>")
    assert "KEY=v\\1\\g<0>\n" in after and after.count("KEY=") == 1
