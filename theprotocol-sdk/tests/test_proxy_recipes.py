"""V0659 (d), the proxy's eight recipes (sessionlogs2026/DESIGN_2026-11-07_PROXY_LIBRARY.md, "Recipes"): MERIDIAN, HANSA,
DYNAMO, BAZAAR, SCRIVENER, LYCEUM, KEYSTONE and TRUNK, each a ready proxy.yaml in proxy/recipes/<name>/ with a fake of
its legacy system in fake/.

Offline, no network: every recipe parses with its plugins checked (stub credentials); the recipes whose source can run
here (a file drop, an SQLite table) are run through the real runtime in a DRY run over what their fake writes, and the
requests it would make are read back; the recipes whose source needs a server (a webhook sender, an MQTT broker, an
SFTP server) have their mappings applied to records shaped as those sources build them, from their fakes' own events.
Each recipe's end-to-end drive on the sandbox is the other half (scratchpad's drives, named in the hand-in).
Red before V0659 (d): proxy/recipes does not exist.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import socket
import sqlite3
import sys

import pytest
import yaml

from theprotocol.proxy import mapping as M
from theprotocol.proxy.plugins import Record
from theprotocol.proxy.spec import parse

RECIPES = pathlib.Path(__file__).resolve().parent.parent / "proxy" / "recipes"
NAMES = ["meridian", "hansa", "dynamo", "bazaar", "scrivener", "lyceum", "keystone", "trunk"]
ENV = {"AGENT_DID": "did:theprotocol:recipe-test", "CLIENT_ID": "agent_client_recipe", "CLIENT_SECRET": "x" * 32,
       "GATE_HMAC": "g" * 32, "ERP_HMAC": "e" * 32, "SHOP_HMAC": "s" * 32, "TP_WEBHOOK_SECRET": "t" * 32,
       "WMS_HMAC": "w" * 32, "PMS_HMAC": "p" * 32}
PARTNER = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-00000000c0de"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


def _doc(name: str) -> dict:
    return yaml.safe_load((RECIPES / name / "proxy.yaml").read_text())


def _fake(name: str, module: str):
    path = RECIPES / name / "fake" / f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"recipe_{name}_{module}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mapping(doc: dict, name: str) -> dict:
    return next(m for m in doc["mappings"] if m["name"] == name)


def _run(doc: dict, tmp: pathlib.Path) -> list:
    """The real runtime, in a DRY run, until every source has finished: what it would have sent."""
    from theprotocol.proxy.runtime import Proxy
    reports: list = []
    p = Proxy(parse(doc, base=tmp), dry_run=True, service=False, poll_s=0.01, report=reports.append)
    asyncio.run(asyncio.wait_for(p.run(until_idle=True), 60))
    return reports


# ── every recipe ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_there_are_the_eight_recipes():
    assert sorted(p.name for p in RECIPES.iterdir() if p.is_dir()) == sorted(NAMES)
    assert (RECIPES / "README.md").is_file()


@pytest.mark.parametrize("name", NAMES)
def test_a_recipe_parses_with_its_plugins_checked_and_carries_its_fake(name):
    spec = parse(_doc(name), base=RECIPES / name)
    assert spec.registry == "https://api.theprotocol.cloud" and spec.mappings
    fakes = list((RECIPES / name / "fake").glob("*.py"))
    assert fakes, f"{name} has no fake of its legacy system"
    assert (RECIPES / name / "README.md").is_file(), f"{name} has no README"
    text = (RECIPES / name / "proxy.yaml").read_text()
    for secret_word in ("password:", "client_secret: \"", "secret: \"", "private_key: \""):
        assert secret_word not in text, f"{name}'s spec writes a secret literally ({secret_word})"


# ── run through the runtime, dry, over what the fake writes ───────────────────────────────────────────────────────────

def _evidence_key(tmp: pathlib.Path) -> str:
    from theprotocol.proxy.evidence import keygen
    keygen(str(tmp / "evidence.pem"))
    return "file:" + str(tmp / "evidence.pem")


@pytest.mark.parametrize("recipe,source", [("meridian", "oms"), ("lyceum", "sis")])
def test_the_two_file_drop_recipes_keep_watching_their_folder(recipe, source):
    """Both are continuous flows: a file the legacy system drops while the proxy runs must be read, so the folder is listed again."""
    assert _doc(recipe)["sources"][source]["config"]["poll_seconds"] == 30


def test_meridian_attests_released_intents_and_exports_their_evidence(tmp_path):
    fake = _fake("meridian", "fake_oms")
    out = tmp_path / "oms-out"
    out.mkdir()
    intents = list(fake.intents(7, 5))
    (out / "intents-0007.json").write_text(__import__("json").dumps(intents))
    doc = _doc("meridian")
    doc["state"] = str(tmp_path / "state.db")
    doc["sources"]["oms"]["config"].update(path=str(out), settle_seconds=0, poll_seconds=0)   # 0: read once and finish
    doc["sinks"]["erp"]["config"].update(dir=str(tmp_path / "erp-in"), signing_key=_evidence_key(tmp_path))
    reports = _run(doc, tmp_path)
    released = [i for i in intents if i["status"] == "RELEASED"]
    attests = [r for r in reports if r["mapping"] == "intent"]
    evidence = [r for r in reports if r["mapping"] == "intent-evidence"]
    assert len(attests) == len(released) == len(evidence) == 4          # the HELD intent is neither attested nor exported
    assert all(r["status"] == "dry_run" for r in reports)
    sent = {r["data"]["request"]["attestation_data"]["claim"]["intent"] for r in attests}
    assert sent == {i["intent_id"] for i in released}


def test_lyceum_attests_each_awarded_credential_and_leaves_the_revoked_one(tmp_path):
    fake = _fake("lyceum", "fake_sis")
    out = tmp_path / "sis-out"
    sys_argv = sys.argv
    try:
        sys.argv = ["fake_sis.py", str(out), "--count", "5", "--run", "T1"]
        fake.main()
    finally:
        sys.argv = sys_argv
    doc = _doc("lyceum")
    doc["state"] = str(tmp_path / "state.db")
    doc["sources"]["sis"]["config"].update(path=str(out), settle_seconds=0, poll_seconds=0)   # 0: read once and finish
    reports = _run(doc, tmp_path)
    assert len(reports) == 4 and all(r["mapping"] == "credential" for r in reports)
    data = [r["data"]["request"]["attestation_data"]["claim"] for r in reports]
    assert {d["award"] for d in data} == {f"AW-T1-{i:03d}" for i in range(4)}
    assert all(d["institution"] == "LYCEUM-DEMO" and d["holder"].startswith("stu-") for d in data)


def test_trunk_pays_each_rated_event_and_not_a_disputed_one(tmp_path):
    fake = _fake("trunk", "fake_mediation")
    db = tmp_path / "mediation.db"
    sys_argv = sys.argv
    try:
        sys.argv = ["fake_mediation.py", str(db), "--partner-did", PARTNER, "--count", "5"]
        fake.main()
    finally:
        sys.argv = sys_argv
    rows = sqlite3.connect(db).execute("SELECT event_id, charge, status FROM settlement_events").fetchall()
    doc = _doc("trunk")
    doc["state"] = str(tmp_path / "state.db")
    doc["sources"]["mediation"]["config"].update(path=str(db), poll_seconds=0)   # 0: read once and finish
    doc["sinks"]["finance"]["config"].update(dir=str(tmp_path / "journal"))
    doc["sources"].pop("theprotocol")      # the registry's webhook receiver: a server; its mapping is read below
    doc["mappings"] = [m for m in doc["mappings"] if m["from"] == "mediation"]
    reports = _run(doc, tmp_path)
    rated = {e: c for e, c, s in rows if s == "RATED"}
    pays = [r for r in reports if r["mapping"] == "settle-event"]
    assert len(pays) == len(rated) == 4 and len(reports) == 4     # the mediation rows pay; they book nothing
    for r in pays:
        req = r["data"]["request"]
        assert req["target_agent_did"] == PARTNER and r["data"]["headers"]["X-Liability-Mandate"] == "lm_yourmandate"
    assert sorted(r["data"]["request"]["amount"] for r in pays) == sorted(rated.values())


def test_trunk_books_only_what_settled_from_the_registrys_payment_settled_notice():
    """Measured on the sandbox drive: a rated event over max_amount went to the dead letters and was still booked when
    the journal booked the mediation row. The journal books TheProtocol's payment.settled notice instead: a payment
    that did not settle has no line, and each line names its settlement."""
    doc = _doc("trunk")
    src = doc["sources"]["theprotocol"]
    assert src["type"] == "theprotocol_events" and src["config"]["events"] == ["payment.settled"]
    book = _mapping(doc, "book-settled")
    assert book["from"] == "theprotocol" and book["to"] == "finance"
    assert not [m for m in doc["mappings"] if m["from"] == "mediation" and m["to"] == "finance"]
    me = book["when"]["equals"]
    settled = {"token_id": "t-1", "caller_did": me, "target_agent_did": PARTNER, "amount": "1.230000",
               "currency": "ECU", "status": "settled", "settlement_tx_id": "tx-9", "task_id": "tpx-abc"}
    assert _take(doc, "book-settled", settled) == {"amount": "1.230000", "direction": "debit", "currency": "ECU",
                                                    "counterparty": PARTNER, "text": "tx-9"}
    assert _take(doc, "book-settled", dict(settled, caller_did="did:theprotocol:another-agent-of-the-owner")) is None


# ── a server's source: the mappings over records shaped as the source builds them ─────────────────────────────────────

def _take(doc: dict, mapping: str, payload: dict) -> dict | None:
    m = _mapping(doc, mapping)
    rec = Record(record_id="r", payload=payload, meta={})
    return M.apply(m["fields"], rec) if M.takes(m.get("when"), rec) else None


def test_hansa_attests_gate_outs_and_sends_them_to_the_erp_but_not_gate_ins():
    doc, evs = _doc("hansa"), list(_fake("hansa", "fake_tos").events(6, "T"))
    outs = [e for e in evs if e["status"] == "OUT"]
    attested = [x for x in (_take(doc, "gate-out", e) for e in evs) if x]
    to_erp = [x for x in (_take(doc, "gate-out-to-erp", e) for e in evs) if x]
    assert len(attested) == len(to_erp) == len(outs) == 4
    assert {a["container"] for a in attested} == {e["container_id"] for e in outs}
    assert all(a["terminal"] == "HAM-CTA" and a["seal"].startswith("SL") for a in attested)


def test_dynamo_attests_every_reading_with_its_meter_from_the_topic():
    doc = _doc("dynamo")
    readings = list(_fake("dynamo", "fake_meters").readings(2, 3))
    got = [_take(doc, "reading", {"topic": t, "levels": t.split("/"), "data": b, "encoding": "json"})
           for t, b in readings]
    assert len(got) == 6 and {g["meter"] for g in got} == {"MTR-0001", "MTR-0002"}
    assert all(g["reading"].startswith(g["meter"]) and g["kwh"] > 1200 for g in got)


def test_bazaar_attests_inventory_and_releases_fulfilment_only_from_a_received_payment():
    doc = _doc("bazaar")
    inv = [x for x in (_take(doc, "inventory", e) for e in _fake("bazaar", "fake_shop").events(4, "T")) if x]
    assert len(inv) == 4 and all(i["warehouse"] == "WH-NORTH" for i in inv)
    # TheProtocol's payment.received, as the registry's webhook carries it (the theprotocol_events source's payload)
    shop = _mapping(doc, "paid-release")["when"]["equals"]
    paid = {"agent_did": shop, "amount": "12.5", "currency": "ECU", "from_did": PARTNER,
            "sender_known": True, "via": "transfer", "ledger_kind": "transfer", "ledger_txid": "tx-1", "teg": "eu"}
    rel = _take(doc, "paid-release", paid)
    assert rel == {"seller_agent": shop, "payer": PARTNER, "amount": "12.5", "currency": "ECU", "ledger_tx": "tx-1"}
    # the owner's webhook carries the income of every agent the owner has: only the shop's own releases goods
    assert _take(doc, "paid-release", dict(paid, agent_did="did:theprotocol:another-agent-of-the-owner")) is None
    assert set(_doc("bazaar")["sources"]["theprotocol"]["config"]["events"]) == {"payment.received"}


def test_scrivener_attests_a_matters_life_and_exports_it_to_the_dms():
    doc, evs = _doc("scrivener"), list(_fake("scrivener", "fake_pms").events("M-1"))
    att = [_take(doc, "matter-event", e) for e in evs]
    exp = [_take(doc, "matter-evidence", e) for e in evs]
    assert [a["event"] for a in att] == ["opened", "filing", "deadline_met", "closed"] and all(exp)
    assert att[1]["document"] and len(att[1]["document"]) == 64 and att[0]["document"] is None


def test_keystone_delivers_only_a_passed_runs_acceptance_as_milestone_evidence():
    doc, fake = _doc("keystone"), _fake("keystone", "fake_logger")
    # the SFTP source's payload: the file, its digest, the row's index and the row itself under data
    # (a CSV row is text: every value a string, as the SFTP source reads it)
    wrap = lambda r, i: {"file": "runs.csv", "sha256": "0" * 64, "row": i, "data": {k: str(v) for k, v in r.items()}}  # noqa: E731
    passed = [_take(doc, "acceptance", wrap(r, i)) for i, r in enumerate(fake.rows("42", 1, 41.5, "R1"))]
    failed = [_take(doc, "acceptance", wrap(r, i)) for i, r in enumerate(fake.rows("42", 1, 30.0, "R2"))]
    assert [p for p in passed if p] == [{"contract_id": "42", "seq": "1", "test": "cube_strength_28d", "result": "PASS",
                                         "measured": "41.5", "limit": "35", "unit": "MPa", "run": "R1",
                                         "at": [p for p in passed if p][0]["at"]}]
    assert not any(failed)
