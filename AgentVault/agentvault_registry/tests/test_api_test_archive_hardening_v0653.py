"""V0653 (am), items 11 and 12 (the hardening list in the sessions' room): the API tester's run archive.

Item 11: write_metadata copied every environment variable under the tester's prefixes WITH ITS VALUE into each archived
run's metadata.json, which sits on the registry's data volume and in its backups; the prefixes reach secrets. It
records the names now. Item 12: list_runs used the run_kind it was given (a query parameter of the archive route) as a
path without the name check its sibling _safe_run_dir makes; an unsafe one lists nothing now. On a tmp archive root,
the real module. BASE (a5ef48ddd, V0652): the planted value is in the file, and "../" lists the directory above.
"""
from __future__ import annotations

import json

import pytest

from agentvault_registry.api_tests.core import archive as A

SECRET = "planted-secret-value-0123456789abcdef"


@pytest.fixture()
def root(tmp_path, monkeypatch):
    r = tmp_path / "archive"
    r.mkdir()
    monkeypatch.setattr(A, "ARCHIVE_ROOT", r)
    return r


def test_the_metadata_names_the_settings_and_never_holds_their_values(root, monkeypatch):
    monkeypatch.setenv("API_TEST_FED_EU_PASSWORD", SECRET)
    monkeypatch.setenv("SANDBOX_RESET_SECRET", SECRET)
    monkeypatch.setenv("API_TEST_TARGET_URL", "https://sbx.example.test")
    monkeypatch.setenv("UNRELATED_SETTING", "x")
    run_dir = root / "baseline" / "run-1"
    run_dir.mkdir(parents=True)
    text = A.write_metadata(run_dir, {"note": "control"}).read_text()
    assert SECRET not in text and "sbx.example.test" not in text
    meta = json.loads(text)
    assert {"API_TEST_FED_EU_PASSWORD", "SANDBOX_RESET_SECRET", "API_TEST_TARGET_URL"} <= set(meta["env_names"])
    assert "UNRELATED_SETTING" not in meta["env_names"] and "env" not in meta
    assert meta["extra"] == {"note": "control"}


def test_an_unsafe_run_kind_lists_nothing(root, tmp_path):
    outside = tmp_path / "outside-run"                     # a run-shaped directory beside the archive: "../" lists it
    outside.mkdir()
    (outside / "summary.json").write_text(json.dumps({"passed": 1}))
    (root / "baseline" / "run-1").mkdir(parents=True)
    for bad in ("..", "../", "../archive", "baseline/../..", "/etc", ".hidden", "a" * 80):
        assert A.list_runs(run_kind=bad) == [], bad


def test_control_a_real_run_kind_still_lists_its_runs(root):
    d = root / "baseline" / "run-1"
    d.mkdir(parents=True)
    (d / "summary.json").write_text(json.dumps({"passed": 1}))
    runs = A.list_runs(run_kind="baseline")
    assert len(runs) == 1
