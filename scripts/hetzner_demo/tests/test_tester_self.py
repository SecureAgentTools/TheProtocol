"""§TESTBED (2026-09-19): `--tester-self` makes a SANDBOX run the MCP/API tester against itself.

The suite executes inside the registry that receives test-flow and reaches its subject containers by docker exec, so the
sandbox's registry carries the fixture accounts' passwords, the reset secret, the proxy key, its own container names and
store, and the socket. A production posture refuses it; a pair shares one fixture secret set (a file frame-sandbox writes).
"""
import importlib.util
import json
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("standup_driver_tself", HERE.parent / "standup_driver.py")
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

BASE = ["--name", "nwsbx", "--frame-label", "Nw Sandbox", "--trust-domain", "sandbox.nw.example.org",
        "--public-url", "https://sandbox.nw.example.org", "--es-public-url", "https://sandbox.nw.example.org:28555",
        "--ticker", "SBX", "--registry-image", "theprotocol/registry:1.0.0-beta.6",
        "--teg-image", "theprotocol/teg-layer:1.0.0-beta.6"]


def test_fresh_secrets_have_every_key_and_a_policy_shape():
    fx = drv.new_tester_fixture_secrets()
    assert set(fx) == set(drv.TESTER_FIXTURE_SECRET_KEYS)
    for k in ("SANDBOX_ADMIN_PASSWORD", "SANDBOX_DEVELOPER_PASSWORD", "SANDBOX_TUTORIAL_PASSWORD", "SANDBOX_NON_ADMIN_PASSWORD"):
        v = fx[k]
        assert len(v) >= 24 and any(c.isupper() for c in v) and any(c.islower() for c in v) and any(c.isdigit() for c in v)
        assert "-" in v and not set(v) & set("$#'\"`\\ ")
    assert len(fx["API_TEST_PROXY_INTERNAL_KEY"]) >= 32 and len(fx["SANDBOX_RESET_SECRET"]) >= 32
    assert fx != drv.new_tester_fixture_secrets()


def test_a_shared_set_must_be_whole(tmp_path):
    p = tmp_path / "fx.json"
    fx = drv.new_tester_fixture_secrets()
    p.write_text(json.dumps(fx))
    assert drv.load_tester_fixture_secrets(str(p)) == fx
    del fx["API_TEST_PROXY_INTERNAL_KEY"]
    p.write_text(json.dumps(fx))
    with pytest.raises(ValueError, match="API_TEST_PROXY_INTERNAL_KEY"):
        drv.load_tester_fixture_secrets(str(p))


def test_the_env_names_this_frame_and_its_store():
    fx = drv.new_tester_fixture_secrets()
    env = dict(drv.tester_self_env("nwsbx", "k" * 40, fx))
    assert env["API_TEST_TGT_A_REGISTRY"] == "nwsbx-registry" and env["API_TEST_REG_DB_CONTAINER"] == "nwsbx-db"
    assert env["API_TEST_TGT_A_ES"] == "nwsbx-event-store" and env["API_TEST_TGT_A_ES_DB"] == "nwsbx-es-db"
    assert env["API_TEST_EVENT_STORE_URL"] == "https://nwsbx-nginx-event-store:8443" and env["API_TEST_EVENT_STORE_API_KEY"] == "k" * 40
    assert env["API_TEST_ES_MTLS_GATEWAY_A"] == "https://nwsbx-nginx-event-store:8443"   # the handshake is measured, not skipped
    assert env["SEED_TEST_ACCOUNTS"] == "true" and env["SANDBOX_ADMIN_PASSWORD"] == fx["SANDBOX_ADMIN_PASSWORD"]
    assert not any(k.startswith("API_TEST_TGT_B_") for k in env)   # the peer is named by frame-sandbox, after both exist


def test_production_refuses_and_a_second_target_refuses():
    a = drv.build_parser().parse_args(BASE + ["--posture", "production", "--tester-self"])
    assert any("--tester-self mounts the docker socket" in r for r in drv.validate_args(a))
    b = drv.build_parser().parse_args(BASE + ["--posture", "sandbox", "--tester-self", "--tester-console", "http://x-registry:8000"])
    assert any("two different targets" in r for r in drv.validate_args(b))


def test_sandbox_tester_self_implies_the_fixtures():
    a = drv.build_parser().parse_args(BASE + ["--posture", "sandbox", "--tester-self"])
    refusals = drv.validate_args(a)
    assert not any("tester-self" in r for r in refusals), refusals
    assert a.tester_fixtures is True
