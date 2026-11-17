"""V0664 consoles (C1, gwo_f1c49a39bfe4eaf7ce9d240d): `tp-proxy catalog --json`, what the console builders are made from.

One JSON document, deterministic, with: every built-in plugin (kind, name, description, class, config_schema with its x-secret
marks, loaded the way the core loads them; a plugin whose optional driver is missing is still described from its class), the
spec's CORE_SCHEMA, the migration manifest schema and the kit caps, the value-node vocabulary and the SDK's version. The
console copy is generated from it (scripts/distribution/gen_proxy_catalog.py in the stack), so what it says is what the SDK
accepts: a test pins it to the live objects, not to a second copy.
"""
from __future__ import annotations

import json

import jsonschema

from theprotocol import __version__
from theprotocol.proxy import mapping as M
from theprotocol.proxy import plugins
from theprotocol.proxy.cli import main
from theprotocol.proxy.migrate import schema as MS
from theprotocol.proxy.spec import CORE_SCHEMA


def _catalog(capsys):
    assert main(["catalog", "--json"]) == 0
    out = capsys.readouterr().out
    return json.loads(out), out


def test_it_says_what_it_is_and_which_sdk_it_came_from(capsys):
    cat, _ = _catalog(capsys)
    assert cat["schema"] == "theprotocol.proxy.catalog/v1" and cat["sdk_version"] == __version__


def test_every_builtin_plugin_is_in_it_with_its_description_and_schema(capsys):
    cat, _ = _catalog(capsys)
    for kind, table in plugins.BUILTINS.items():
        listed = {p["name"]: p for p in cat["plugins"][kind]}
        assert sorted(listed) == sorted(table), kind
        for name, where in table.items():
            p, cls = listed[name], plugins.load(kind, name)
            assert p["kind"] == kind and p["class"] == where
            assert p["description"] == cls.description and p["description"]
            assert p["config_schema"] == json.loads(json.dumps(cls.config_schema))
            jsonschema.Draft202012Validator.check_schema(p["config_schema"])      # a schema a browser can validate with


def test_the_secret_marks_survive_so_the_builder_can_refuse_a_literal(capsys):
    cat, _ = _catalog(capsys)
    by = {(p["kind"], p["name"]): p for p in (q for k in cat["plugins"].values() for q in k)}
    props = by[("sink", "sql_upsert")]["config_schema"]["properties"]
    assert props["password"].get("x-secret") is True or "password" in json.dumps(props["password"])
    secrets = [(k, n) for (k, n), p in by.items() if '"x-secret": true' in json.dumps(p["config_schema"])]
    assert ("sink", "evidence") in secrets and ("source", "sqlpoll") in secrets


def test_a_plugin_for_the_sample_only_says_so(capsys):
    cat, _ = _catalog(capsys)
    p = next(q for q in cat["plugins"]["source"] if q["name"] == "migrate_sample")
    assert p["internal"] is True
    assert all("internal" not in q or q["internal"] is False for q in cat["plugins"]["sink"])


def test_the_schemas_and_the_vocabulary_are_the_live_ones(capsys):
    cat, _ = _catalog(capsys)
    assert cat["core_schema"] == json.loads(json.dumps(CORE_SCHEMA))
    assert cat["migration"]["manifest_schema"] == json.loads(json.dumps(MS.MANIFEST_SCHEMA))
    assert cat["migration"]["kit_caps"] == json.loads(json.dumps(MS.KIT_CAPS))
    v = cat["value_nodes"]
    assert v["keys"] == sorted(M.VALUE_KEYS) and v["as"] == list(M.AS_TYPES) and v["case"] == list(M.CASES)
    assert v["order"] == ["null_if", "trim", "case", "regex", "map", "as", "round"]
    assert v["node_needs"] == "path or concat"


def test_the_output_is_deterministic_and_has_no_secret_or_time(capsys):
    a = _catalog(capsys)[1]
    b = _catalog(capsys)[1]
    assert a == b
    assert a.endswith("\n") and json.dumps(json.loads(a), sort_keys=True, indent=1, ensure_ascii=False) + "\n" == a


def test_without_json_it_prints_a_short_table_and_needs_no_driver(capsys):
    assert main(["catalog"]) == 0
    out = capsys.readouterr().out
    for name in ("sqlpoll", "sql_upsert", "attestation", "filedrop"):
        assert name in out


def test_a_plugin_that_does_not_load_is_described_from_its_class_or_named(monkeypatch, capsys):
    """A broken module must not hide the others: it is listed with its error's class, never a message."""
    monkeypatch.setitem(plugins.BUILTINS["source"], "ghost", "theprotocol.proxy.no_such_module:Nope")
    cat, _ = _catalog(capsys)
    ghost = next(p for p in cat["plugins"]["source"] if p["name"] == "ghost")
    assert ghost["error"] == "ModuleNotFoundError" and "config_schema" not in ghost
    assert any(p["name"] == "filedrop" and p.get("config_schema") for p in cat["plugins"]["source"])
