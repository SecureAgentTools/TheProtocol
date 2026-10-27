"""§MCPTEST30 (V0545) — overrides.yaml applies section by section; one null section never drops the rest.

`endpoints:` in api_tests/overrides.yaml holds only commented examples, which YAML reads as null. The loader's log line
called len(data.get('endpoints', {})), a present key returns its null rather than the default, the TypeError reached
the loader's except, and it returned {} for the whole file: the API tester's catalog lost its 15 excludes (among them
the cloud-operator provision and teardown routes and the recursive run-all), its auth prefix defaults and its tag
remaps, with an ERROR line on every load (three in 15 minutes on sbx-alpha during one MCP sweep).
"""
from __future__ import annotations

import logging

import pytest

from agentvault_registry.api_tests.core import catalog_sync as CS


def _load(tmp_path, monkeypatch, text):
    f = tmp_path / "overrides.yaml"
    f.write_text(text)
    monkeypatch.setattr(CS, "_OVERRIDES_PATH", f)
    return CS._load_overrides()


def test_a_null_section_is_an_empty_one_and_the_rest_apply(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=CS.logger.name)
    d = _load(tmp_path, monkeypatch, "paths_to_exclude:\n  - /admin/x/*\nendpoints:\n  # only an example\n"
                                     "auth_prefix_defaults:\n  /teg/: agent\n")
    assert d["paths_to_exclude"] == ["/admin/x/*"] and d["endpoints"] == {} and d["auth_prefix_defaults"] == {"/teg/": "agent"}
    assert d["tag_remap"] == {}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_section_of_the_wrong_shape_is_ignored_alone(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=CS.logger.name)
    d = _load(tmp_path, monkeypatch, "paths_to_exclude: /not-a-list\nendpoints: {}\n")
    assert d["paths_to_exclude"] == [] and d["endpoints"] == {}
    assert any("`paths_to_exclude` is a str" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)


def test_the_real_file_loads_whole_and_keeps_the_destructive_routes_out(caplog):
    caplog.set_level(logging.DEBUG, logger=CS.logger.name)
    d = CS._load_overrides()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], [r.getMessage() for r in caplog.records]
    globs = d["paths_to_exclude"]
    assert len(globs) >= 15 and isinstance(d["endpoints"], dict) and len(d["tag_remap"]) >= 60
    for path in ("/admin/cloud-operators/{application_id}/provision", "/admin/cloud-operators/{application_id}/teardown",
                 "/admin/api-test/run-all", "/mcp/rpc", "/oauth/token"):
        assert CS._is_excluded(path, globs), path
    assert not CS._is_excluded("/agent-cards/discover", globs), "a route nobody excluded stays in the catalog"


def test_a_file_that_is_not_a_mapping_is_named(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=CS.logger.name)
    assert _load(tmp_path, monkeypatch, "- just\n- a list\n") == {}
    assert any("not a mapping" in r.getMessage() for r in caplog.records)


@pytest.fixture(autouse=True)
def _no_cache():
    yield
