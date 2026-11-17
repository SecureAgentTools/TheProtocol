"""V0664 (order gwo_9105add77686897bc940b870, found by session-watch, room seq 3992): the template check takes a secret field
that names a secret parameter, so the three starter kits the SDK ships can be published.

services/workflow_templates.check_kit refused all three: their secret fields hold ${NAME} for a parameter the manifest
declares secret: true, and only env:NAME or file:/path counted as a reference (the SDK fills the placeholder first, so
`tp-proxy migrate check` passed them). Now a secret field whose value is exactly one ${NAME} passes when the manifest declares
NAME secret: true; one naming any other name (a parameter not marked secret, or none) is refused with its own sentence; any
other value is a written-out credential, as before.
The kits are copied in tests/data/shipped_kits (SOURCE.md names their commit): this file reads nothing outside the repo.
Red on 1402ee756: the three kits are refused.
"""
from __future__ import annotations

import pathlib

import pytest

from agentvault_registry.services import workflow_templates as wt
from tests.test_workflow_templates_kit_v0664 import MANIFEST, PROXY, kit

KITS = pathlib.Path(__file__).resolve().parent / "data" / "shipped_kits"
NAMES = ("csv-to-postgres", "sql-to-postgres", "sql-to-rest")


def _files(name):
    root = KITS / name
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


# every file of each kit, as the SDK ships it (a file the repo ignores would silently leave a kit short: *.sql is ignored
# in this repo, so .gitignore names these fixtures back)
FILE_COUNTS = {"csv-to-postgres": 8, "sql-to-postgres": 8, "sql-to-rest": 6}


def test_the_three_kits_are_here_whole():
    assert (KITS / "SOURCE.md").is_file()
    assert {n: len(_files(n)) for n in NAMES} == FILE_COUNTS
    assert (KITS / "csv-to-postgres" / "fake" / "target_postgresql.sql").is_file()


@pytest.mark.parametrize("name", NAMES)
def test_a_kit_the_sdk_ships_passes_the_check(name):
    manifest = wt.check_kit(_files(name))
    assert manifest["schema"] == "theprotocol.migration/v1"


def _secret_field(value, params_extra=""):
    manifest = MANIFEST.replace("  TARGET_TABLE: {default: public.customers}\n",
                                "  TARGET_TABLE: {default: public.customers}\n" + params_extra)
    proxy = PROXY.replace('password: "env:SOURCE_PASSWORD"', f"password: {value!r}")
    assert proxy != PROXY
    return kit(**{"migration.yaml": manifest, "proxy.yaml": proxy})


def test_a_secret_field_naming_a_secret_parameter_is_a_reference():
    assert wt.check_kit(_secret_field("${SOURCE_PASSWORD}"))         # SOURCE_PASSWORD is declared secret: true


@pytest.mark.parametrize("value,params", [
    ("${SOURCE_ENGINE}", ""),                                          # a declared parameter, not marked secret
    ("${NOT_DECLARED}", ""),                                           # no such parameter
    ("${PLAIN_PW}", "  PLAIN_PW: {description: a password kept plain}\n"),
])
def test_a_secret_field_naming_any_other_name_is_refused_with_its_own_sentence(value, params):
    with pytest.raises(wt.KitRefused) as e:
        wt.check_kit(_secret_field(value, params))
    s = e.value.sentence
    assert "proxy.yaml:sources.customers.config.password" in s and "secret: true" in s, s
    assert "written out" not in s, "not the written-out sentence: it names the parameter rule"


@pytest.mark.parametrize("value", ["hunter2-plain", "${SOURCE_PASSWORD}x", "pre-${SOURCE_PASSWORD}", "${A}${B}"])
def test_anything_else_stays_a_written_out_credential(value):
    with pytest.raises(wt.KitRefused) as e:
        wt.check_kit(_secret_field(value))
    assert "written out" in e.value.sentence and "hunter2" not in e.value.sentence
