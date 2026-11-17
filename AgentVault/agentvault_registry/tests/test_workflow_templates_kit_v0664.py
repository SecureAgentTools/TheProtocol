"""V0664 "Migrate a system", M4 (order gwo_e97a483512cfaf2151f17b7a): the kit a migration template carries, checked at
upload (sessionlogs2026/DESIGN_2026-11-14_MIGRATION_TEMPLATES.md sections A and D).

  files      migration.yaml, proxy.yaml and README.md required; at most 64 files, each at most 256 KiB, 2 MiB in all;
             UTF-8 text; paths ^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$ (no "..", no leading "/" or ".")
  manifest   yaml.safe_load only, then the schema theprotocol.migration/v1 (MANIFEST_SCHEMA, M3's copied verbatim); a
             refusal names the field and the rule, never the value
  secrets    spec.py's SECRET_KEY and REF, copied: a key whose name says it holds a credential, with a value that is not
             an env:/file: reference, refuses the upload and names its path; a secret parameter's default too
  destinations (contract section D, DESTINATIONS, session-lead room seq 3820): a published kit names no destination of
             its own: every host, url and path in its sources and sinks is a ${PARAM} the manifest declares (a url may
             carry a /path after it, never a second host), and a default for one may only be local (localhost,
             127.0.0.1, ::1, a relative path inside the kit); anything else refuses the upload naming the path
  hash       content_hash = sha256 of the canonical JSON of {"manifest", "files"}
  structure  what anyone may see of a template: from and to, the parameter names, the steps, the mappings and field
             counts; never a file
The copies of the SDK's constants (MANIFEST_SCHEMA, KIT_CAPS, PATH_PATTERN, canonical(), SECRET_KEY, REF) are pinned
equal on the stack, where both trees are visible (scripts/distribution/check_migration_pins.py, run at release): this file
reads nothing outside the registry repo, so it runs the same in the tree, in CI (/w/tests) and in the image (/app/tests).
Red on v0663/cut b7ca684e9: the module does not exist.
"""
from __future__ import annotations

import hashlib
import json

import pytest

try:     # red as one failure per test, not a collection error
    from agentvault_registry.services import workflow_templates as wt
except ImportError:
    wt = None


MANIFEST = """\
schema: theprotocol.migration/v1
name: crm-customers-to-postgres
title: Customers from a CRM table to PostgreSQL
summary: One table to one table, upsert by the old id
from: {kind: sql, engines: [postgresql, mysql, sqlserver, sqlite], what: a customers table}
to: {kind: sql, engines: [postgresql], what: public.customers}
parameters:
  SOURCE_ENGINE: {description: the old database, default: sqlite, enum: [postgresql, mysql, sqlserver, sqlite]}
  SOURCE_PASSWORD: {description: a read-only login, secret: true}
  TARGET_TABLE: {default: public.customers}
load:
  mappings: [customers]
  batch_rows: 1000
reconcile:
  - mapping: customers
    source: {key: [id], fields: [name, email, created_at]}
    target: {key: [legacy_id], fields: [full_name, email, created]}
    pairs: {name: full_name, email: email, created_at: created}
sample:
  customers: {file: sample/customers.csv, format: csv}
cutover:
  checklist: [Stop writes to the old system, Load again, Reconcile again, Point the readers at the new system]
rollback: auto
workflow:
  - {key: dry-run, role: migration.runner, acceptance: a dry-run report whose verdict is pass, budget_share: 40}
  - {key: reconcile, role: migration.reconciler, input_from: dry-run, acceptance: a reconcile report whose verdict is pass, budget_share: 60}
"""
PROXY = """\
version: 1
sources:
  customers: {type: sqlpoll, config: {engine: "${SOURCE_ENGINE}", password: "env:SOURCE_PASSWORD", table: customers}}
sinks:
  crm: {type: sql_upsert, config: {engine: postgresql, password: "file:/run/secrets/target", table: "${TARGET_TABLE}"}}
mappings:
  customers: {source: customers, sink: crm, fields: {legacy_id: $.id, full_name: $.name, email: $.email}}
"""


def kit(**over):
    files = {"migration.yaml": MANIFEST, "proxy.yaml": PROXY, "README.md": "# Customers\n",
             "sample/customers.csv": "id,name,email,created_at\n1,Ada,ada@example.org,2026-01-01\n"}
    files.update(over)
    return {k: v for k, v in files.items() if v is not None}


def refused(files, *bits):
    with pytest.raises(wt.KitRefused) as e:
        wt.check_kit(files)
    for b in bits:
        assert b in e.value.sentence, (b, e.value.sentence)
    return e.value.sentence


def test_a_good_kit_passes_and_gives_its_manifest():
    m = wt.check_kit(kit())
    assert m["name"] == "crm-customers-to-postgres" and m["from"]["kind"] == "sql" and m["to"]["kind"] == "sql"


@pytest.mark.parametrize("missing", ["migration.yaml", "proxy.yaml", "README.md"])
def test_the_three_required_files(missing):
    refused(kit(**{missing: None}), missing)


@pytest.mark.parametrize("path", ["../x", "/abs", ".hidden", "a//b", "a/../b", "sample/.x", "a b"])
def test_a_path_outside_the_rule_is_refused(path):
    refused(kit(**{path: "x"}), "path")


def test_the_caps():
    refused(kit(**{f"f{i}.txt": "x" for i in range(61)}), "64 files")
    refused(kit(big="x" * (256 * 1024 + 1)), "256 KiB")
    refused(kit(**{f"p{i}.txt": "x" * (250 * 1024) for i in range(9)}), "2 MiB")
    refused(kit(**{"bin.dat": "a\x00b"}), "text")


def test_the_manifest_is_safe_loaded_and_checked_without_echoing_a_value():
    refused(kit(**{"migration.yaml": "!!python/object/apply:os.system ['echo hi']"}), "migration.yaml")
    s = refused(kit(**{"migration.yaml": MANIFEST.replace("crm-customers-to-postgres", "Has Upper Case SECRETVALUE")}),
                "migration.yaml", "name")
    assert "SECRETVALUE" not in s
    refused(kit(**{"migration.yaml": MANIFEST.replace("schema: theprotocol.migration/v1", "schema: other/v9")}), "schema")
    refused(kit(**{"migration.yaml": MANIFEST + "unknown_key: 1\n"}), "unknown_key")


def test_a_sample_the_manifest_names_must_be_in_the_kit():
    refused(kit(**{"sample/customers.csv": None}), "sample/customers.csv")


@pytest.mark.parametrize("bad,path", [
    (PROXY.replace('"env:SOURCE_PASSWORD"', "hunter2-plain"), "proxy.yaml:sources.customers.config.password"),
    (PROXY + "notify: {api_key: abcd1234}\n", "proxy.yaml:notify.api_key"),
])
def test_a_written_out_credential_refuses_the_upload_naming_its_path(bad, path):
    s = refused(kit(**{"proxy.yaml": bad}), path)
    assert "hunter2" not in s and "abcd1234" not in s


def test_a_secret_parameters_default_must_be_a_reference():
    bad = MANIFEST.replace("{description: a read-only login, secret: true}",
                           "{description: a read-only login, secret: true, default: plainpw}")
    s = refused(kit(**{"migration.yaml": bad}), "parameters.SOURCE_PASSWORD.default")
    assert "plainpw" not in s
    # M3's rule (theprotocol/proxy/migrate/schema.validate_manifest): a secret parameter has no default at all, a
    # reference included; it is given when the kit runs (the CLI refuses such a kit, so the library does too)
    ref = MANIFEST.replace("{description: a read-only login, secret: true}",
                           "{description: a read-only login, secret: true, default: 'env:SRC_PW'}")
    refused(kit(**{"migration.yaml": ref}), "parameters.SOURCE_PASSWORD")


def test_the_content_hash_is_the_canonical_sha256():
    files = kit()
    m = wt.check_kit(files)
    want = hashlib.sha256(json.dumps({"manifest": m, "files": files}, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()
    assert wt.content_hash(m, files) == want


def test_the_structure_shows_the_shape_and_never_a_file():
    s = wt.structure(wt.check_kit(kit()))
    assert s["from"]["kind"] == "sql" and s["to"]["engines"] == ["postgresql"]
    assert s["parameters"] == ["SOURCE_ENGINE", "SOURCE_PASSWORD", "TARGET_TABLE"]
    assert [x["key"] for x in s["steps"]] == ["dry-run", "reconcile"] and s["load_mappings"] == ["customers"]
    assert s["reconcile"] == [{"mapping": "customers", "fields": 3}]
    assert "files" not in s and "full_name" not in json.dumps(s)


def test_the_schema_is_a_json_schema():
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(wt.MANIFEST_SCHEMA)
    assert wt.MANIFEST_SCHEMA["properties"]["schema"]["const"] == "theprotocol.migration/v1"


# --- destinations (contract section D, DESTINATIONS) --------------------------------------------------------------------

def _with(proxy_extra, params_extra=""):
    manifest = MANIFEST.replace("  TARGET_TABLE: {default: public.customers}\n",
                                "  TARGET_TABLE: {default: public.customers}\n" + params_extra)
    return kit(**{"proxy.yaml": PROXY + proxy_extra, "migration.yaml": manifest})


@pytest.mark.parametrize("extra,path", [
    ("  api: {type: rest, config: {url: 'https://crm.example.org/in'}}\n", "proxy.yaml:sinks.api.config.url"),
    ("  out: {type: file_out, config: {path: '${OUT}', sftp: {host: files.example.org, user: u, path: '${OUT}'}}}\n",
     "proxy.yaml:sinks.out.config.sftp.host"),
    ("  api: {type: rest, config: {url: '${API}@evil.example.org/'}}\n", "proxy.yaml:sinks.api.config.url"),
    ("  api: {type: rest, config: {url: '${UNDECLARED}/x'}}\n", "UNDECLARED"),
])
def test_a_sink_that_names_its_own_destination_is_refused(extra, path):
    files = _with("", "  OUT: {default: out/files}\n  API: {description: the target api}\n")
    files["proxy.yaml"] = PROXY.replace("sinks:\n", "sinks:\n" + extra)
    s = refused(files, path)
    assert "example.org" not in s


def test_a_source_host_must_be_a_declared_parameter_with_a_local_default():
    src = "  legacy: {type: sqlpoll, config: {engine: postgresql, host: '${SRC_HOST}', database: '${SRC_DB}', table: t}}\n"
    def kit_with(params):
        files = _with("", params)
        files["proxy.yaml"] = PROXY.replace("sources:\n", "sources:\n" + src)
        return files
    assert wt.check_kit(kit_with("  SRC_HOST: {description: the old server}\n  SRC_DB: {default: crm}\n"))
    assert wt.check_kit(kit_with("  SRC_HOST: {default: 127.0.0.1}\n  SRC_DB: {default: crm}\n"))
    s = refused(kit_with("  SRC_HOST: {default: db.example.org}\n  SRC_DB: {default: crm}\n"),
                "migration.yaml:parameters.SRC_HOST.default")
    assert "db.example.org" not in s
    refused(kit_with("  SRC_DB: {default: crm}\n"), "SRC_HOST")


@pytest.mark.parametrize("default,ok", [
    ("out/files", True), ("sample", True), ("/var/out", False), ("../outside", False), ("~/out", False),
    ("C:/out", False),
])
def test_a_path_default_is_a_relative_path_inside_the_kit(default, ok):
    files = _with("", f"  OUT: {{default: '{default}'}}\n")
    files["proxy.yaml"] = PROXY.replace("sinks:\n", "sinks:\n  out: {type: file_out, config: {path: '${OUT}'}}\n")
    if ok:
        assert wt.check_kit(files)
    else:
        refused(files, "migration.yaml:parameters.OUT.default")


@pytest.mark.parametrize("default,ok", [
    ("http://localhost:9000", True), ("https://127.0.0.1/in", True), ("http://[::1]:8080", True),
    ("https://crm.example.org", False), ("http://localhost@evil.example.org", False),
])
def test_a_url_default_is_local(default, ok):
    files = _with("", f"  API: {{default: '{default}'}}\n")
    files["proxy.yaml"] = PROXY.replace("sinks:\n", "sinks:\n  api: {type: rest, config: {url: '${API}/customers/{id}'}}\n")
    if ok:
        assert wt.check_kit(files)
    else:
        refused(files, "migration.yaml:parameters.API.default")


# session-lead, room seq 3831: a url starts with its parameter, and what follows may only begin with / or ? (or nothing)
@pytest.mark.parametrize("url,ok", [
    ("${API}", True), ("${API}/customers/{id}", True), ("${API}?id={id}", True),
    ("${API}.evil.example", False), ("${API}:8080/in", False), ("${API}@evil.example", False),
])
def test_what_may_follow_a_urls_parameter(url, ok):
    files = _with("", "  API: {description: the target api}\n")
    files["proxy.yaml"] = PROXY.replace("sinks:\n", "sinks:\n  api: {type: rest, config: {url: '" + url + "'}}\n")
    if ok:
        assert wt.check_kit(files)
    else:
        assert "evil" not in refused(files, "proxy.yaml:sinks.api.config.url")


# session-lead, room seq 3843: a database NAME default is allowed (the host decides where data goes, and the host is a
# parameter); the local-only rule stays for hosts, urls and paths, sqlite database files included
@pytest.mark.parametrize("db_default", ["legacy", "app", "legacy:2019", "crm_prod"])
def test_a_database_names_default_is_allowed(db_default):
    src = "  legacy: {type: sqlpoll, config: {engine: postgresql, host: '${SRC_HOST}', database: '${SRC_DB}', table: t}}\n"
    files = _with("", f"  SRC_HOST: {{description: the old server}}\n  SRC_DB: {{default: '{db_default}'}}\n")
    files["proxy.yaml"] = PROXY.replace("sources:\n", "sources:\n" + src)
    assert wt.check_kit(files)


def test_a_sqlite_file_path_default_stays_local():
    src = "  legacy: {type: sqlpoll, config: {engine: sqlite, path: '${SRC_FILE}', table: t}}\n"
    files = _with("", "  SRC_FILE: {default: /var/lib/legacy.sqlite}\n")
    files["proxy.yaml"] = PROXY.replace("sources:\n", "sources:\n" + src)
    refused(files, "migration.yaml:parameters.SRC_FILE.default")


# --- the manifest is M3's (theprotocol/proxy/migrate/schema.py, copied verbatim; the stack's
# scripts/distribution/check_migration_pins.py pins the copy equal at release) ---------------------------------------

def test_the_kit_caps_are_m3s():
    assert wt.KIT_CAPS == {"max_files": 64, "max_file_bytes": 256 * 1024, "max_total_bytes": 2 * 1024 * 1024,
                           "path_pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$",
                           "encoding": "utf-8"}
    assert wt.MANIFEST_SCHEMA["$id"] == "theprotocol.migration/v1"


def _m(old, new):
    assert old in MANIFEST, old
    return kit(**{"migration.yaml": MANIFEST.replace(old, new)})


@pytest.mark.parametrize("files", [
    pytest.param(_m("reconcile:\n  - mapping: customers\n    source: {key: [id], fields: [name, email, created_at]}\n"
                    "    target: {key: [legacy_id], fields: [full_name, email, created]}\n"
                    "    pairs: {name: full_name, email: email, created_at: created}\n", ""), id="no reconcile"),
    pytest.param(_m("{file: sample/customers.csv, format: csv}", "{file: sample/customers.csv, format: json}"),
                 id="a json sample"),
    pytest.param(_m("{key: dry-run, role: migration.runner, acceptance: a dry-run report whose verdict is pass, "
                    "budget_share: 40}", "{key: dry-run, role: migration.runner, acceptance: a dry-run report whose "
                    "verdict is pass}"), id="a step without a budget share"),
])
def test_what_m3s_schema_allows_the_library_takes(files):
    assert wt.check_kit(files)["schema"] == "theprotocol.migration/v1"


def test_a_lowercase_parameter_is_a_parameter_for_the_destinations_rule_too():
    manifest = MANIFEST.replace("  TARGET_TABLE: {default: public.customers}\n",
                                "  TARGET_TABLE: {default: public.customers}\n  target_host: {description: the host}\n")
    proxy = PROXY + "  pg: {type: sql_upsert, config: {engine: postgresql, host: '${target_host}', table: t}}\n"
    assert wt.check_kit(kit(**{"migration.yaml": manifest, "proxy.yaml": proxy}))


@pytest.mark.parametrize("files,bit", [
    pytest.param(_m("rollback: auto\n", ""), "rollback", id="no rollback"),
    pytest.param(_m("pairs: {name: full_name, email: email, created_at: created}", "pairs: {}"), "reconcile",
                 id="reconcile pairs empty"),
    pytest.param(_m("default: sqlite, enum: [postgresql, mysql, sqlserver, sqlite]",
                    "default: oracle, enum: [postgresql, mysql, sqlserver, sqlite]"),
                 "parameters.SOURCE_ENGINE", id="a default outside its enum"),
    pytest.param(_m("input_from: dry-run", "input_from: nowhere"), "workflow.reconcile.input_from",
                 id="input_from names no step"),
    pytest.param(_m("target: {key: [legacy_id],", "target: {key: [legacy_id, region],"), "reconcile[0]",
                 id="keys of different widths"),
])
def test_what_m3s_checks_refuse_the_library_refuses(files, bit):
    refused(files, bit)
