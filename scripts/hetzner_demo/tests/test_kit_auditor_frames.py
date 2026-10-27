"""§SOVKIT (2026-09-14) — the solo auditor's frames file is written from the rendered env, on the read-only role.

The driver writes <stack>/kit/auditor/frames/frames.json before compose up (one entry: the frame itself, its store read
through the mTLS sidecar with no key (§MTLSHOPS T2), three DSNs on `auditor_ro`), and creates that role once the
databases are healthy. Pinned here: the shape of the entry, that the role is the auditor's (never the owner), and that a
missing password refuses.
"""
import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("standup_driver", os.path.join(HERE, "standup_driver.py"))
drv = importlib.util.module_from_spec(spec)
sys.argv = ["standup_driver.py"]
spec.loader.exec_module(drv)

ENV = """# rendered
FT_FRAME_CURRENCY=KIT
FT_DB_POSTGRES_DB=frame_test_registry
FT_DB_POSTGRES_USER=registry
FT_TEGDB_POSTGRES_DB=frame_test_teg
FT_TEGDB_POSTGRES_USER=teg
FT_ESDB_POSTGRES_DB=frame_test_events
FT_ESDB_POSTGRES_USER=events
EVENT_STORE_INTERNAL_API_KEY=0123456789abcdef0123456789abcdef
AUDITOR_RO_PASSWORD=fedcba9876543210fedcba9876543210
FT_REG_FX_ROUTER_DID=did:theprotocol:router-1
"""


def _ctx(tmp_path):
    return types.SimpleNamespace(stack_dir_container=str(tmp_path))


def test_the_frames_file_names_this_frame_on_the_read_only_role(tmp_path, monkeypatch):
    monkeypatch.setattr(drv, "log", lambda *a, **k: None)
    args = types.SimpleNamespace(name="kitproof", frame_label="Kit Proof")
    drv.kit_write_auditor_frames(_ctx(tmp_path), ENV, args)
    p = tmp_path / "kit" / "auditor" / "frames" / "frames.json"
    entries = json.loads(p.read_text())
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == "kitproof" and e["name"] == "Kit Proof" and e["mode"] == "prod" and e["currency"] == "KIT"
    # §MTLSHOPS T2 (S4, 2026-09-15): the store's mTLS sidecar, read with the auditor's own SVID; no store key is written
    assert e["url"] == "https://kitproof-nginx-event-store:8443" and "key" not in e
    assert "0123456789abcdef0123456789abcdef" not in p.read_text()
    assert e["dsn"] == "postgresql://auditor_ro:fedcba9876543210fedcba9876543210@kitproof-es-db:5432/frame_test_events"
    assert e["reg_dsn"].startswith("postgresql://auditor_ro:") and e["reg_dsn"].endswith("@kitproof-db:5432/frame_test_registry")
    assert e["teg_dsn"].endswith("@kitproof-teg-db:5432/frame_test_teg")
    assert e["fx_router_did"] == "did:theprotocol:router-1"
    for k in ("dsn", "reg_dsn", "teg_dsn"):
        assert "registry:" not in e[k] and "events:" not in e[k] and "teg:" not in e[k], "the auditor must never log in as an owner"


def test_the_store_key_is_no_longer_required(tmp_path, monkeypatch):
    monkeypatch.setattr(drv, "log", lambda *a, **k: None)
    args = types.SimpleNamespace(name="kitproof", frame_label="Kit Proof")
    env = ENV.replace("EVENT_STORE_INTERNAL_API_KEY=0123456789abcdef0123456789abcdef\n", "")
    drv.kit_write_auditor_frames(_ctx(tmp_path), env, args)
    e = json.loads((tmp_path / "kit" / "auditor" / "frames" / "frames.json").read_text())[0]
    assert e["url"] == "https://kitproof-nginx-event-store:8443" and "key" not in e


def test_a_missing_password_refuses_the_standup(tmp_path, monkeypatch):
    monkeypatch.setattr(drv, "log", lambda *a, **k: None)
    died = {}

    def _die(msg):
        died["msg"] = msg
        raise SystemExit(2)
    monkeypatch.setattr(drv, "die", _die)
    args = types.SimpleNamespace(name="kitproof", frame_label="Kit Proof")
    try:
        drv.kit_write_auditor_frames(_ctx(tmp_path), ENV.replace("AUDITOR_RO_PASSWORD=fedcba9876543210fedcba9876543210\n", ""), args)
    except SystemExit:
        pass
    assert "AUDITOR_RO_PASSWORD" in died.get("msg", "")
    assert not (tmp_path / "kit" / "auditor" / "frames" / "frames.json").exists()


def test_the_auditors_live_read_error_is_read_from_the_row_not_its_status():
    f = drv.auditor_live_read_error
    assert f(None, "kitproof") is None and f({"message": "No audit results yet"}, "kitproof") is None
    ok = {"kitproof": {"status": "OK", "extra_data": {"live_delta": 0.0}}}
    lost = {"kitproof": {"status": "OK", "extra_data": {"live_error": "ConnectError: certificate verify failed"}}}
    assert f(ok, "kitproof") == ""
    assert f(lost, "kitproof") == "ConnectError: certificate verify failed", "a status that mirrors the atomic read must not hide it"
    assert f({"kitproof": {"status": "OK", "extra_data": json.dumps({"live_error": "502"})}}, "kitproof") == "502"
    assert f({"kitproof": {"status": "ERROR", "live_error": "timeout", "extra_data": None}}, "kitproof") == "timeout"
    assert f(lost, "another") is None


def test_env_kv_takes_the_first_definition_and_strips_quotes():
    kv = drv._env_kv("A=1\nB='two'\nA=3\n# C=4\nD=\"x\"\n")
    assert kv == {"A": "1", "B": "two", "D": "x"}


def test_a_skipped_live_read_is_not_a_read_that_succeeded():
    """§MTLSHOPS (a) (2026-09-15, agentvault2-85): the kit gate passes only on a live read that ran. A row whose read the
    auditor skipped (extra_data.live_skipped) returns the recorded reason, so the probe refuses it; red on master's driver,
    which read that row as a clean read."""
    f = drv.auditor_live_read_error
    why = "not read: this extra slot carries no store key, is not a public read, and this auditor presents no certificate"
    skipped = {"kitproof": {"status": "OK", "extra_data": {"live_skipped": why}}}
    assert f(skipped, "kitproof") == f"the live read did not run: {why}"
    assert f({"kitproof": {"status": "OK", "extra_data": json.dumps({"live_skipped": why})}}, "kitproof").endswith(why)
    assert f({"kitproof": {"status": "OK", "extra_data": {}}}, "kitproof") == ""

