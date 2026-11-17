"""V0664 Migrate (M3): the kit (its caps, its manifest's schema, its content hash), the parameters, and a spec that needs
no identity. Red before M3: theprotocol.proxy.migrate does not exist, and spec.parse refuses a spec with no registry.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from theprotocol.proxy import spec as S
from theprotocol.proxy.migrate import KIT_CAPS, MANIFEST_SCHEMA, KitError, canonical, load_kit
from theprotocol.proxy.migrate import params as P
from theprotocol.proxy.migrate.schema import check_files, kit_from_files

MANIFEST = """schema: theprotocol.migration/v1
name: crm-customers
title: Customers
from: {kind: sql}
to: {kind: sql}
parameters:
  SOURCE_PATH: {default: legacy.db}
  TARGET_PASSWORD: {secret: true}
  MODE: {default: update, enum: [update, skip]}
load: {mappings: [customers]}
rollback: auto
"""
PROXY = "version: 1\nname: crm\nsources: {}\nmappings: []\n"


def _files(**over):
    files = {"migration.yaml": MANIFEST, "proxy.yaml": PROXY, "README.md": "# Customers\n"}
    files.update(over)
    return {k: v for k, v in files.items() if v is not None}


def _write(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ── the caps ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_caps_are_the_contracts():
    assert KIT_CAPS == {"max_files": 64, "max_file_bytes": 262144, "max_total_bytes": 2097152,
                        "path_pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$",
                        "encoding": "utf-8"}
    assert MANIFEST_SCHEMA["properties"]["schema"] == {"const": "theprotocol.migration/v1"}


def test_a_kit_inside_the_caps_loads(tmp_path):
    kit = load_kit(_write(tmp_path, _files()))
    assert kit.name == "crm-customers" and set(kit.files) == {"migration.yaml", "proxy.yaml", "README.md"}


@pytest.mark.parametrize("files, says", [
    ({f"sample/f{i}.csv": "a\n" for i in range(62)}, "at most 64"),
    ({"sample/big.csv": "x" * (256 * 1024 + 1)}, "at most 262144"),
    ({f"sample/b{i}.csv": "x" * (250 * 1024) for i in range(9)}, "at most 2097152"),
    ({"../evil": "x"}, "a path is"),
    ({".hidden": "x"}, "a path is"),
    ({"README.md": None}, "README.md: missing"),
])
def test_each_cap_refuses_naming_itself(files, says):
    raw = {k: v.encode() for k, v in _files(**files).items()}
    problems = check_files(raw)
    assert any(says in p for p in problems), problems


def test_non_utf8_is_refused():
    raw = {k: v.encode() for k, v in _files().items()}
    raw["sample/bin.csv"] = b"\xff\xfe\x00"
    assert any("not UTF-8" in p for p in check_files(raw))


def test_the_state_folder_is_not_part_of_the_kit(tmp_path):
    d = _write(tmp_path, _files())
    (d / ".migrate" / "reports").mkdir(parents=True)
    (d / ".migrate" / "reports" / "x.json").write_text("{}")
    assert ".migrate/reports/x.json" not in load_kit(d).files


def test_the_content_hash_is_sha256_of_the_canonical_manifest_and_files(tmp_path):
    import yaml
    files = _files()
    kit = load_kit(_write(tmp_path, files))
    want = hashlib.sha256(json.dumps({"manifest": yaml.safe_load(MANIFEST), "files": files}, sort_keys=True,
                                     separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    assert kit.content_hash == want
    assert canonical({"b": 1, "a": "ü"}) == '{"a":"ü","b":1}'.encode("utf-8")
    other = kit_from_files(_files(**{"README.md": "# Customers, changed\n"}))
    assert other.content_hash != kit.content_hash


@pytest.mark.parametrize("edit, says", [
    (("name: crm-customers", "name: Not A Slug"), "migration.name"),
    (("rollback: auto", "rollback: maybe"), "migration.rollback"),
    (("schema: theprotocol.migration/v1", "schema: theprotocol.migration/v2"), "migration.schema"),
    (("TARGET_PASSWORD: {secret: true}", "TARGET_PASSWORD: {secret: true, default: hunter22}"),
     "a secret parameter has no default"),
])
def test_the_manifest_schema_refuses(edit, says):
    with pytest.raises(KitError) as e:
        kit_from_files(_files(**{"migration.yaml": MANIFEST.replace(*edit)}))
    assert any(says in p for p in e.value.problems), e.value.problems


# ── the parameters ───────────────────────────────────────────────────────────────────────────────────────────────────

def _manifest():
    import yaml
    return yaml.safe_load(MANIFEST)


def test_parameters_fill_from_set_then_file_then_default(tmp_path):
    f = tmp_path / "p.env"
    f.write_text("# a comment\nSOURCE_PATH='from-file.db'\nTARGET_PASSWORD=env:PW\n")
    v = P.resolve_values(_manifest(), sets=P.parse_sets(["MODE=skip"]), file_values=P.read_params_file(str(f)),
                         needed=["SOURCE_PATH", "TARGET_PASSWORD", "MODE"])
    assert v == {"SOURCE_PATH": "from-file.db", "TARGET_PASSWORD": "env:PW", "MODE": "skip"}
    doc = P.fill({"a": "${SOURCE_PATH}", "b": "x-${MODE}-y", "c": [{"d": "${TARGET_PASSWORD}"}], "e": 3}, v)
    assert doc == {"a": "from-file.db", "b": "x-skip-y", "c": [{"d": "env:PW"}], "e": 3}
    assert P.fill("${N}", {"N": 30}) == 30     # a whole placeholder keeps the value's type


@pytest.mark.parametrize("kw, says", [
    ({"needed": ["NOPE"]}, "declares no parameter NOPE"),
    ({"needed": ["TARGET_PASSWORD"]}, "parameter TARGET_PASSWORD: no value"),
    ({"sets": {"TARGET_PASSWORD": "hunter2-literal"}}, "a secret is given as a reference"),
    ({"sets": {"MODE": "delete"}}, "parameter MODE: not one of"),
    ({"sets": {"EXTRA": "1"}}, "--set EXTRA: the manifest declares no parameter EXTRA"),
])
def test_parameter_refusals_name_the_parameter(kw, says):
    with pytest.raises(P.ParamError) as e:
        P.resolve_values(_manifest(), **kw)
    assert any(says in p for p in e.value.problems), e.value.problems
    assert not any("hunter2-literal" in p for p in e.value.problems)


def test_a_sample_run_needs_no_secret():
    v = P.resolve_values(_manifest(), needed=["TARGET_PASSWORD"], allow_unset_secrets=True)
    assert v["TARGET_PASSWORD"] == "env:TP_MIGRATE_UNSET_TARGET_PASSWORD"


# ── identity optional ────────────────────────────────────────────────────────────────────────────────────────────────

SYSTEM_TO_SYSTEM = {
    "version": 1, "name": "s2s",
    "sources": {"old": {"type": "filedrop", "config": {"path": "in"}}},
    "sinks": {"new": {"type": "file_out", "config": {"path": "out", "format": "jsonl"}}},
    "mappings": [{"name": "m", "version": 1, "from": "old", "to": "new", "fields": {"a": "$.payload.row"}}],
}


def test_a_system_to_system_spec_needs_no_registry_and_no_identity(tmp_path):
    spec = S.parse(SYSTEM_TO_SYSTEM, base=tmp_path)
    assert spec.registry == "" and spec.identity == {}
    from theprotocol.proxy.runtime import Proxy
    p = Proxy(spec, service=False)
    try:
        assert p.identity is None and p.client is None
        st = p.status()
        assert st["agent_did"] is None and st["identity"] is None and st["registry"] is None
    finally:
        p.close()


def test_a_spec_with_an_action_still_needs_both_and_is_told_which_action():
    doc = json.loads(json.dumps(SYSTEM_TO_SYSTEM))
    doc["actions"] = {"att": {"type": "attestation", "config": {"attestation_type": "x"}}}
    doc["mappings"].append({"name": "m2", "version": 1, "from": "old", "to": "att", "fields": {"a": 1}})
    with pytest.raises(S.SpecError) as e:
        S.parse(doc)
    text = " ".join(e.value.problems)
    assert "spec.registry: actions.att (attestation) calls TheProtocol" in text
    assert "spec.identity: actions.att (attestation) calls TheProtocol" in text


def test_a_theprotocol_events_source_still_needs_both():
    doc = json.loads(json.dumps(SYSTEM_TO_SYSTEM))
    doc["sources"]["ev"] = {"type": "theprotocol_events", "config": {}}
    with pytest.raises(S.SpecError) as e:
        S.parse(doc, check_plugins=False)
    assert any("sources.ev (theprotocol_events)" in p and "registry" in p for p in e.value.problems)


def test_a_parameter_whose_default_is_an_integer_or_a_boolean_takes_that_type():
    # session-tester seq 3844, session-lead seq 3855: `port: ${SOURCE_PORT}` must pass an integer schema
    import yaml
    m = yaml.safe_load(MANIFEST.replace("  MODE: {default: update, enum: [update, skip]}",
                                        "  MODE: {default: update, enum: [update, skip]}\n  PORT: {default: 5432}\n"
                                        "  STRICT: {default: false}"))
    v = P.resolve_values(m, sets={"PORT": "55442", "STRICT": "yes"}, needed=["PORT", "STRICT"])
    assert v["PORT"] == 55442 and v["STRICT"] is True
    assert P.resolve_values(m, needed=["PORT"])["PORT"] == 5432
    assert P.fill({"port": "${PORT}", "dsn": "h:${PORT}"}, v) == {"port": 55442, "dsn": "h:55442"}
    for bad, says in (({"PORT": "54x"}, "parameter PORT: its default is an integer"),
                      ({"STRICT": "maybe"}, "parameter STRICT: its default is a boolean")):
        with pytest.raises(P.ParamError) as e:
            P.resolve_values(m, sets=bad, needed=list(bad))
        assert any(says in p for p in e.value.problems), e.value.problems
    spec = S.parse({"version": 1, "name": "t",
                    "sources": {"s": {"type": "sqlpoll", "config": P.fill(
                        {"engine": "postgresql", "host": "db", "port": "${PORT}", "table": "t", "cursor": "id"}, v)}},
                    "mappings": []})
    assert spec.sources["s"].config["port"] == 55442
