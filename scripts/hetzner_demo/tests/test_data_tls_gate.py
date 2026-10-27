"""§MTLSHOPS T3 (2026-09-15, agentvault2-b5): the driver's data TLS gate, driven with a fake docker.

kit_data_tls_gate asks each database's pg_stat_ssl for certificate-verified TLS clients and no plain one, has each database
refuse a plain TCP client and a TLS client with no certificate, and asks the registry's Redis client for PING over TLS while
a plain and a certificate-less client get nothing. With every answer good it passes; with each bad answer it dies naming
what it saw. The lab (t3lab3) measures the same refusals against the rendered services themselves.
"""
import importlib.util
import json
import pathlib
import subprocess
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
GOOD_REDIS = {"tls_client": True, "plain_answered": False, "certless_tls_answered": False}
PLAIN_REFUSED = 'psql: error: FATAL:  pg_hba.conf rejects connection for host "127.0.0.1", user "u", database "d", no encryption\n'
CERTLESS_REFUSED = "psql: error: FATAL:  connection requires a valid client certificate\n"


class _Died(Exception):
    pass


@pytest.fixture()
def drv(monkeypatch):
    spec = importlib.util.spec_from_file_location("standup_driver_data_tls_gate", HERE / "standup_driver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    def died(msg, code=1):
        raise _Died(msg)

    monkeypatch.setattr(mod, "die", died)
    return mod


def _docker(monkeypatch, drv, stat="2|0", plain_rc=2, certless_rc=2, redis=None):
    calls = []

    def run(argv, **kw):
        calls.append(list(argv))
        if "psql" in argv and "pg_stat_ssl" in argv[-1]:
            return subprocess.CompletedProcess(argv, 0, stat + "\n", "")
        if "psql" in argv and any("sslmode=disable" in a for a in argv):
            return subprocess.CompletedProcess(argv, plain_rc, "", PLAIN_REFUSED if plain_rc else "")
        if "psql" in argv and any("sslmode=require" in a for a in argv):
            return subprocess.CompletedProcess(argv, certless_rc, "", CERTLESS_REFUSED if certless_rc else "")
        if "python" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(redis or GOOD_REDIS) + "\n", "")
        raise AssertionError(f"unexpected {argv}")

    fake = types.ModuleType("subprocess")
    fake.__dict__.update(subprocess.__dict__)
    fake.run = run
    monkeypatch.setattr(drv, "subprocess", fake)
    return calls


def _gate(drv):
    drv.kit_data_tls_gate(types.SimpleNamespace(), types.SimpleNamespace(name="f"))


def test_a_frame_whose_data_services_take_tls_only_passes(drv, monkeypatch):
    calls = _docker(monkeypatch, drv)
    lines = []
    monkeypatch.setattr(drv, "log", lines.append)
    _gate(drv)
    assert lines[-1].startswith("data tls: the three databases and Redis take TLS only")
    asked = [c[2] for c in calls if "psql" in c]
    assert {"f-db", "f-teg-db", "f-es-db"} <= set(asked)
    assert any(c[2] == "f-registry" and "python" in c for c in calls)


def test_a_database_that_accepts_a_plain_client_dies_naming_it(drv, monkeypatch):
    _docker(monkeypatch, drv, plain_rc=0)
    with pytest.raises(_Died) as died:
        _gate(drv)
    assert "f-db did not refuse a plain TCP client" in str(died.value)


def test_a_database_that_takes_a_client_with_no_certificate_dies_naming_it(drv, monkeypatch):
    _docker(monkeypatch, drv, certless_rc=0)
    with pytest.raises(_Died) as died:
        _gate(drv)
    assert "f-db did not refuse a TLS client with no certificate" in str(died.value)


def test_a_plain_client_in_pg_stat_ssl_dies_after_its_tries(drv, monkeypatch):
    _docker(monkeypatch, drv, stat="3|1")
    with pytest.raises(_Died) as died:
        _gate(drv)
    assert "f-db never showed a certificate-verified TLS client with no plain one" in str(died.value)
    assert "plain TCP clients 1" in str(died.value)


def test_redis_answering_a_plain_client_dies_naming_it(drv, monkeypatch):
    _docker(monkeypatch, drv, redis={**GOOD_REDIS, "plain_answered": True})
    with pytest.raises(_Died) as died:
        _gate(drv)
    assert "f-redis did not take TLS only" in str(died.value) and "plain_answered True" in str(died.value)
