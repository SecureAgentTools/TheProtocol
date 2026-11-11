"""V0659 (a): the proxy's spec. A secret is taken only by reference (env:NAME, file:/path, file:/path#KEY) and a literal
one is refused at load, naming its path, wherever the spec holds a credential; every problem is named with its path.
Red before V0659: theprotocol.proxy.spec does not exist.
"""
from __future__ import annotations

import pytest

import proxy_fake as F


@pytest.fixture(autouse=True)
def fake_plugins(monkeypatch):
    from theprotocol.proxy import plugins
    monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")
    monkeypatch.setitem(plugins.BUILTINS["sink"], "list_sink", "proxy_fake:ListSink")


def _parse(doc, tmp_path):
    from theprotocol.proxy.spec import parse
    return parse(doc, base=tmp_path)


def _problems(doc, tmp_path):
    from theprotocol.proxy.spec import SpecError
    with pytest.raises(SpecError) as e:
        _parse(doc, tmp_path)
    return e.value.problems


def test_a_spec_with_references_loads_and_resolves_them(tmp_path, monkeypatch):
    spec = _parse(F.spec_doc(tmp_path), tmp_path)
    assert spec.value(spec.identity["client_secret"]) == F.CLIENT_SECRET
    assert spec.value(spec.identity["client_id"]) == F.CLIENT_ID
    assert spec.value(spec.identity["agent_did"]) == F.DID          # a literal DID is not a secret
    monkeypatch.setenv("TP_TEST_SECRET", "from-the-env")
    (tmp_path / "token.txt").write_text("from-a-file\n")
    assert spec.secret("env:TP_TEST_SECRET") == "from-the-env"
    assert spec.secret("file:token.txt") == "from-a-file"
    assert sorted(spec.secret_values()) == sorted([F.CLIENT_ID, F.CLIENT_SECRET])
    assert [m.kind for m in spec.mappings] == ["action"]


def test_a_literal_client_secret_is_refused_at_load_naming_its_path(tmp_path):
    doc = F.spec_doc(tmp_path)
    doc["identity"]["client_secret"] = F.CLIENT_SECRET
    assert any(p.startswith("identity.client_secret") for p in _problems(doc, tmp_path))


def test_a_literal_in_a_plugins_secret_field_is_refused(tmp_path):
    doc = F.spec_doc(tmp_path, sources={"gate": {"type": "webhook", "config": {
        "listen": "127.0.0.1:8711", "path": "/in", "secret": "hmac-key-written-out"}}},
        mappings=[{"name": "m", "version": 1, "from": "gate", "to": "attest", "fields": {"a": "$.payload"}}])
    assert "sources.gate.config.secret" in _problems(doc, tmp_path)


def test_a_key_named_for_a_credential_is_refused_as_a_literal_in_any_plugin(tmp_path):
    doc = F.spec_doc(tmp_path)
    doc["sources"]["feed"]["config"].update({"db_password": "hunter22", "api_key": "abc123",
                                             "token_url": "https://idp.example/token"})
    problems = _problems(doc, tmp_path)
    assert "sources.feed.config.db_password" in problems and "sources.feed.config.api_key" in problems
    assert not any("token_url" in p for p in problems), "a key that only mentions one is not a credential"


def test_a_reference_to_what_is_not_there_is_named(tmp_path):
    from theprotocol.proxy.spec import SpecError, resolve
    with pytest.raises(SpecError, match="TP_NOT_SET_ANYWHERE"):
        resolve("env:TP_NOT_SET_ANYWHERE", environ={})
    (tmp_path / ".env.secret").write_text("A=1\n")
    with pytest.raises(SpecError, match="no line NOPE"):
        resolve("file:.env.secret#NOPE", base=tmp_path)
    with pytest.raises(SpecError, match="cannot be read"):
        resolve("file:missing.txt", base=tmp_path)


def test_a_dotenv_line_is_read_as_the_starter_writes_it(tmp_path):
    from theprotocol.proxy.spec import dotenv_value
    text = '# comment\nexport A=1\nB = "two words"\nC=\'3\'\nD=x=y\n'
    assert [dotenv_value(text, k) for k in "ABCD"] == ["1", "two words", "3", "x=y"]
    assert dotenv_value(text, "E") is None


def test_every_problem_is_named_with_its_path(tmp_path):
    doc = F.spec_doc(tmp_path)
    doc["sources"]["feed"]["type"] = "no_such_source"
    doc["mappings"].append({"name": "reading", "version": 1, "from": "nowhere", "to": "nothing", "fields": {}})
    problems = _problems(doc, tmp_path)
    assert any(p.startswith("sources.feed.type: no source plugin called 'no_such_source'") for p in problems)
    assert any("names another mapping too" in p for p in problems)
    assert any("no source called 'nowhere'" in p for p in problems)
    assert any("no action or sink called 'nothing'" in p for p in problems)


def test_the_core_schema_refuses_what_it_does_not_know(tmp_path):
    doc = F.spec_doc(tmp_path)
    doc["version"] = 2
    doc["surprise"] = True
    problems = _problems(doc, tmp_path)
    assert any(p.startswith("spec.version") for p in problems) and any("surprise" in p for p in problems)


def test_a_plugins_config_is_checked_against_its_own_schema(tmp_path):
    doc = F.spec_doc(tmp_path)
    doc["actions"]["attest"]["config"] = {"attestation_type": "", "colour": "red"}
    problems = _problems(doc, tmp_path)
    assert any(p.startswith("actions.attest.config") and "colour" in p for p in problems)
    assert any(p.startswith("actions.attest.config.attestation_type") for p in problems)


def test_a_mapping_may_deliver_to_a_sink_and_actions_and_sinks_share_one_namespace(tmp_path):
    doc = F.spec_doc(tmp_path, sinks={"erp": {"type": "list_sink"}},
                     mappings=[{"name": "out", "version": 1, "from": "feed", "to": "erp", "fields": {}}])
    assert _parse(doc, tmp_path).mappings[0].kind == "sink"
    doc["sinks"]["attest"] = {"type": "list_sink"}
    assert any("share one namespace" in p for p in _problems(doc, tmp_path))


def test_a_yaml_spec_is_read_from_its_folder(tmp_path):
    import yaml
    from theprotocol.proxy.spec import read
    doc = F.spec_doc(tmp_path)
    doc["state"] = "./state.db"
    (tmp_path / "proxy.yaml").write_text(yaml.safe_dump(doc))
    spec = read(str(tmp_path / "proxy.yaml"))
    assert spec.state_path == str(tmp_path.resolve() / "state.db")
    assert spec.value(spec.identity["client_secret"]) == F.CLIENT_SECRET


def test_the_shipped_example_spec_is_valid():
    from pathlib import Path
    from theprotocol.proxy.spec import read
    spec = read(str(Path(__file__).resolve().parent.parent / "proxy" / "proxy.example.yaml"))
    assert spec.name == "gate-scanner" and spec.sources["gate"].type == "webhook"
    assert spec.identity["client_secret"] == "env:CLIENT_SECRET" and spec.state_path == "/data/proxy-state.db"
